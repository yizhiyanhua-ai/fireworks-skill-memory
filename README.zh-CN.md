<div align="center">

<img src="https://raw.githubusercontent.com/yizhiyanhua-ai/fireworks-skill-memory/main/docs/logo.svg" alt="fireworks-skill-memory" width="80" />

# fireworks-skill-memory

**为 Claude Code 与 Codex Skills 提供持久化经验记忆。**

共享 memory core，运行时适配器分离，按 skill 渐进加载。

[![Version](https://img.shields.io/badge/version-4.0.0-orange.svg)](https://github.com/yizhiyanhua-ai/fireworks-skill-memory/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-compatible-8A2BE2)](https://claude.ai/code)
[![Codex](https://img.shields.io/badge/Codex-compatible-111111)](https://openai.com)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/yizhiyanhua-ai/fireworks-skill-memory/pulls)

[English](README.md) · [提交 Bug](https://github.com/yizhiyanhua-ai/fireworks-skill-memory/issues) · [功能建议](https://github.com/yizhiyanhua-ai/fireworks-skill-memory/issues)

</div>

---

## 问题

每次 coding agent 会话都从零开始。同样的错误一遍遍重复——错误的 API 参数、错误的调用顺序、被遗忘的代理配置——因为运行时在会话之间没有持久 skill 记忆。

```
第 1 次：  「记住，飞书块的 index 要从单块接口取」  ✓ 成功
第 2 次：  同样的错误再次发生                       ✗ 忘了
第 3 次：  同样的错误再次发生                       ✗ 又忘了
```

## 解决方案

`fireworks-skill-memory` 给 Claude Code 和 Codex 一套持续积累、按 skill 分类的记忆。知识存储层共享，hook 与 flush 流程由各自 runtime adapter 负责。

```
第 1 次：  出错 → 教训自动保存
第 2 次：  Claude 回答前先注入教训                  ✓ 不再重复
第 3 次：  教训还在，还在继续积累                   ✓ 持续进化
```

---

## 安装

### Claude Code

在 Claude Code 里直接说：

> *"帮我从 https://github.com/yizhiyanhua-ai/fireworks-skill-memory 安装 fireworks-skill-memory"*

或者在终端直接运行：

```bash
curl -fsSL https://raw.githubusercontent.com/yizhiyanhua-ai/fireworks-skill-memory/main/install.sh | bash
```

然后在 Claude Code 中输入 `/hooks` 激活。无需手动编辑任何配置文件。

### Codex

Codex 不使用 Claude 风格 hooks。当前推荐的接入方式是显式命令：

```bash
python3 cli/skill_memory.py inject --skill lark-sync
python3 cli/skill_memory.py checkpoint --skill lark-sync --note "..."
python3 cli/skill_memory.py flush --skill lark-sync --summary-file ./session-summary.md
```

Codex 默认把记忆写到：

```text
$CODEX_HOME/memories/fireworks-skill-memory/
```

---

## 架构

### 完整流程图

<img src="https://raw.githubusercontent.com/yizhiyanhua-ai/fireworks-skill-memory/main/docs/architecture.svg" alt="架构图" width="100%"/>

两个 runtime，一套共享 memory core：

| Hook | 触发时机 | 职责 |
|------|---------|------|
| `PreToolUse` (Skill) | Skill 调用前 | **执行前**注入历史教训——Claude 在规划阶段就能看到经验，而不是犯错之后 |
| `PostToolUse` (Read) | Claude 读取任意 `SKILL.md` 时 | 将历史教训注入上下文——**< 5ms，纯文件读取** |
| `PostToolUse` (所有工具) | 每次工具调用后 | 捕获错误信号写入 session 级种子文件——**覆盖更广** |
| `Stop` (async) | 会话结束时 | 用 haiku 从 transcript 提炼 1–3 条新教训——**不阻塞** |
| `Stop` (async, 每日一次) | 每天会话结束时 | 检查远程仓库是否有更新，有则在下次 `SessionStart` 时提示 |
| `SessionStart` | 会话开始时 | 显示定时任务通知 + 版本更新提醒 |

Codex 当前通过显式命令工作：

| Runtime | 入口 | 职责 |
|---------|------|------|
| `Codex` | `inject` | 在任务前按 skill 注入高优先级 lessons |
| `Codex` | `checkpoint` | 把原始笔记存到 skill 目录下，等待后续提炼 |
| `Codex` | `flush` | 从 summary / session 输入中提炼 lessons，回写 `KNOWLEDGE.md` |

### 运行时拆分

```text
memory_core/
  store.py           # skill/global knowledge 存储、merge、淘汰
  transcript.py      # transcript 解析辅助

runtimes/
  claude_runtime.py  # Claude transcript provider + Claude CLI distiller
  codex_runtime.py   # Codex checkpoint/flush provider

scripts/             # 轻量 Claude hook 适配层
cli/                 # 轻量 Codex/手工适配层
```

现在蒸馏已经走统一 distiller interface。Claude runtime 当前默认使用 `ClaudeCliDistiller`；Codex 的显式流程仍然保持本地化，直到你额外挂接模型后端。

backend selector 在 `memory_core/distiller.py`。`OpenAIDistiller` 现在也补了更强的真实联调能力：支持更多 OpenAI 兼容响应结构解析、记录带 body 的 HTTP 错误，并通过 `SKILLS_DISTILLER_DEBUG` 或 `SKILLS_DISTILLER_LOG` 输出 raw preview。

**v4 harness 优化（2026-04-05，无需修改配置）：**
- 可观测性 — 每次 Stop hook 执行结果写入 `~/.claude/skill-memory.log`（时间戳、session、skills、结果）
- 更广的错误覆盖 — 新增 `error-seed-capture.py`，捕获所有工具调用的错误，不再局限于 SKILL.md 读取时
- 更早的注入时机 — 新增 `pre-skill-inject.py`，在 `PreToolUse` 触发，Claude 规划阶段就能看到历史教训
- 模型 fallback 链 — 主模型废弃时自动尝试下一个可用模型，不再静默失败
- 跨会话使用频率统计 — `skill-usage-stats.json` 记录每个 skill 的使用次数，为淘汰策略提供数据
- 知识库容量扩展 — `SKILL_MAX` / `GLOBAL_MAX` 从 30/20 扩展到 100 条
- 上下文高效注入 — 主动调用时按 HIT 计数排序注入 top-20，不再全量注入

### Harness 工程模式

<img src="https://raw.githubusercontent.com/yizhiyanhua-ai/fireworks-skill-memory/main/docs/harness-pattern.svg" alt="Harness 工程模式图" width="100%"/>

Claude Code 的 **Harness（线束）** 是模型与外部世界之间的编排层——模型只负责推理，Harness 负责所有 I/O：工具调用、文件访问、子进程执行、权限管控。`fireworks-skill-memory` 是一个纯 Harness 层扩展：它不修改模型，不干预用户 prompt，不拦截任何输入。

它只在 Harness 暴露的两个生命周期钩子点上工作：
- **`PostToolUse` on `Read`** — 当任意 `SKILL.md` 被读取时触发，通过 `additionalContext` 向模型上下文注入历史经验
- **`Stop` with `async: true`** — 每次会话结束后触发，在后台运行蒸馏流水线，不阻塞任何用户操作

这是扩展 Claude Code 的正确工程模式：挂载到 Harness 生命周期，而不是修改模型本身。

---

## 知识库结构

```text
<memory-home>/
├── global/KNOWLEDGE.md          ← 全局跨 skill 通用准则
└── skills/
    ├── browser-use/
    │   ├── KNOWLEDGE.md         ← distilled 的 skill 专属 lessons
    │   └── CHECKPOINTS.md       ← 原始 runtime 笔记，默认不注入
    └── {任意 skill}/
        ├── KNOWLEDGE.md
        └── CHECKPOINTS.md

Claude legacy 运行时状态仍保留在 `~/.claude/`：
~/.claude/skills/<skill>/KNOWLEDGE.md
~/.claude/error-seeds/<session_id>.txt
~/.claude/skill-memory.log
~/.claude/skill-usage-stats.json
```

**两层设计：**
- **全局层** — 对所有 skill 都有帮助的通用原则
- **Skill 层** — 只和这个 skill 相关的精确操作教训

注入时只加载当前 skill 的知识，不污染模型上下文窗口。

---

## 会积累哪些内容

经过几次真实使用后，知识文件大概长这样：

```markdown
# browser-use — 经验库

- [state 优先] 每次 click 前必须先运行 browser-use state——
  每次页面交互后索引都会变化，不能复用旧索引。
- [守护进程] 用完要运行 browser-use close。
  守护进程会一直开着占用资源，不会自动关闭。
- [Profile 登录] 用 --profile "Default" 访问已登录的网站。
  无头 Chromium 没有保存的 cookie。
```

---

## 内置初始知识

Claude Code 官方 skill 的经验文件仍然开箱即用。Codex 也可以通过 shared memory core 或 Claude fallback 路径读取同一批 lessons。

| Skill | 预置内容 |
|-------|----------|
| `find-skills` | CLI 命令、安装路径、网络错误规律 |
| `skills-updater` | 两个更新来源、版本追踪、语言检测 |
| `voice` | agent-voice 安装、认证流程、ask vs say 语义 |
| `browser-use` | state 优先原则、守护进程生命周期、Profile 认证 |
| `skill-adoption-planner` | 快速评估输入、阻力诊断 |
| `skill-knowledge-extractor` | 无脚本模式、模式类型 |
| `skill-roi-calculator` | 最小数据集、对比模式 |
| `hookify` | 规则格式、正则字段、命名规范 |
| `superpowers` | 强制调用规则、用户指令优先级 |

---

## 隐私与安全

| | 说明 |
|--|------|
| 📍 **数据位置** | 全部在本机，不上传，不联网 |
| 📄 **Transcript 访问** | Claude runtime 读取本地 Claude JSONL transcript；Codex runtime 当前使用显式 summary / session 输入 |
| 🔑 **敏感信息** | 提炼 prompt 明确排除凭证和个人数据 |
| 🤖 **API 调用** | Claude 的蒸馏走本机已有 Claude Code 认证；Codex 显式流程默认不联网，除非你额外接模型后端 |

---

## Codex Runtime

共享存储默认在：

```text
$CODEX_HOME/memories/fireworks-skill-memory/   # 在 Codex 中运行时
~/.ai-memory/                                  # 其他环境默认
```

目录结构：

```text
<memory-home>/
├── global/KNOWLEDGE.md
└── skills/
    └── <skill>/KNOWLEDGE.md
```

Claude 的 legacy skill knowledge 仍然会从 `~/.claude/skills/<skill>/KNOWLEDGE.md` fallback 读取。

直接使用 CLI：

```bash
python3 cli/skill_memory.py inject --skill lark-sync
python3 cli/skill_memory.py checkpoint --skill lark-sync --note "Feishu local image embeds must be uploaded first"
python3 cli/skill_memory.py flush --skill lark-sync --summary-file ./session-summary.md
python3 cli/skill_memory.py flush --skill lark-sync --session-file ./codex-session.jsonl
cat session-summary.md | python3 cli/skill_memory.py flush --skill lark-sync --stdin
python3 cli/skill_memory.py show --skill lark-sync
```

推荐的 `flush` summary 模板：

```md
# Session Summary

## Lessons

- Verify effective scopes before wiki writes
- `docs +create` does not resolve Obsidian local image embeds
- Replace `![[...]]` with `<image token="..."/>` before overwrite sync
```

当前命令：

- `inject` — 为 Codex 任务输出按 skill 渐进加载的经验上下文
- `checkpoint` — 把原始 session 笔记写入 skill 目录，供后续提炼
- `flush` — 从 summary 文件、session 导出或 stdin 中提炼最多 3 条 lesson 到 `KNOWLEDGE.md`；只识别 `## Lessons`、`## Takeaways`、`## 经验沉淀` 这类 section。除非显式传 `--include-checkpoints`，否则不会把 `CHECKPOINTS.md` 直接并进知识库
- `show` — 输出当前 skill 的 `KNOWLEDGE.md`

完整安全策略详见 [SECURITY.md](SECURITY.md)。

---

## 配置项

全部可选，在 `~/.claude/settings.json` 的 `"env"` 字段中设置：

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `SKILLS_KNOWLEDGE_MODEL` | `claude-haiku-4-5` | Claude CLI distiller backend 的默认模型（废弃时自动 fallback） |
| `SKILLS_DISTILLER_BACKEND` | `claude-cli` | distiller backend 选择器：`claude-cli`、`openai` 或 `null` |
| `SKILLS_DISTILLER_DEBUG` | 未设置 | 设为 `1`/`true` 时，把 backend 调试日志写到 `~/.claude/skill-memory-distiller.log` |
| `SKILLS_DISTILLER_LOG` | 未设置 | 可选的 distiller 调试日志显式路径 |
| `SKILL_MAX` | `100` | 每个 skill 文件最大条目数 |
| `GLOBAL_MAX` | `100` | 全局文件最大条目数 |
| `TRANSCRIPT_LINES` | `300` | 分析 transcript 的最后 N 行 |
| `SKILLS_KNOWLEDGE_DIR` | `~/.claude/skills` | skill 目录根路径 |
| `SKILLS_INJECT_TOP` | `20` | 主动调用时按 HIT 排序注入的最大条数 |
| `SKILLS_SEEDS_DIR` | `~/.claude/error-seeds` | session 级错误种子文件目录 |
| `SKILLS_STATS_FILE` | `~/.claude/skill-usage-stats.json` | 跨会话 skill 使用频率统计文件 |
| `SKILLS_MEMORY_LOG` | `~/.claude/skill-memory.log` | Stop hook 执行日志路径 |

如果使用 `openai` backend，还需要设置：

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `OPENAI_API_KEY` | 无 | OpenAI distiller backend 的 API key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容 chat completions 的 base URL |
| `OPENAI_MODEL` | `gpt-5.4` | OpenAI distiller backend 的模型名 |

真实联调时，建议额外开启其一：

- `SKILLS_DISTILLER_DEBUG=1`
- `SKILLS_DISTILLER_LOG=/absolute/path/to/distiller.log`

---

## 贡献

非常欢迎为常用 skill 贡献新的 `KNOWLEDGE.md` 初始文件。

1. Fork 并创建分支：`git checkout -b feat/skill-name-knowledge`
2. 在 `examples/skill-knowledge/` 中添加文件
3. 提交 PR，简单说明包含哪些教训以及为什么重要

---

## License

MIT © 2026 [yizhiyanhua-ai](https://github.com/yizhiyanhua-ai)
