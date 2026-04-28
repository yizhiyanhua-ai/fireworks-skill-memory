"""Unified distiller interface and runtime-agnostic backends."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DistillResult:
    text: str
    backend: str
    model: str | None = None
    error: str | None = None
    raw_preview: str | None = None


class Distiller(Protocol):
    def distill(self, prompt: str, *, timeout: int = 30) -> DistillResult: ...


def _distiller_log_path() -> Path | None:
    value = os.environ.get("SKILLS_DISTILLER_LOG")
    if value:
        return Path(os.path.expanduser(value))
    debug_flag = os.environ.get("SKILLS_DISTILLER_DEBUG", "").strip().lower()
    if debug_flag in {"1", "true", "yes", "on"}:
        return Path.home() / ".claude" / "skill-memory-distiller.log"
    return None


def _log_distiller_event(backend: str, message: str) -> None:
    path = _distiller_log_path()
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} | {backend} | {message}\n")
    except Exception:
        pass


class ClaudeCliDistiller:
    def __init__(self, primary_model: str | None = None) -> None:
        self.primary_model = primary_model or os.environ.get(
            "SKILLS_KNOWLEDGE_MODEL",
            "claude-haiku-4-5",
        )

    def _candidate_models(self) -> list[str]:
        fallback_models = [
            self.primary_model,
            "claude-haiku-4-5",
            "claude-haiku-4-5-20251001",
            "claude-haiku-3-5",
        ]
        seen: set[str] = set()
        models: list[str] = []
        for model in fallback_models:
            if model and model not in seen:
                seen.add(model)
                models.append(model)
        return models

    def distill(self, prompt: str, *, timeout: int = 30) -> DistillResult:
        for model in self._candidate_models():
            try:
                result = subprocess.run(
                    ["claude", "-p", prompt, "--model", model],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return DistillResult(
                        text=result.stdout.strip(),
                        backend="claude-cli",
                        model=model,
                    )
            except Exception:
                continue
        return DistillResult(
            text="SKIP",
            backend="claude-cli",
            model=None,
            error="no Claude CLI candidate model returned usable output",
        )


class OpenAIDistiller:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = (
            base_url
            or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        ).rstrip("/")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-5.4")

    def _extract_error_message(self, data: object) -> str | None:
        if not isinstance(data, dict):
            return None

        error = data.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
        if isinstance(error, dict):
            pieces: list[str] = []
            for key in ("message", "type", "code", "param"):
                value = error.get(key)
                if isinstance(value, str) and value.strip():
                    pieces.append(f"{key}={value.strip()}")
            if pieces:
                return ", ".join(pieces)
        return None

    def _extract_message_text(self, data: dict) -> tuple[str, str | None]:
        direct_output_text = data.get("output_text")
        if isinstance(direct_output_text, str) and direct_output_text.strip():
            return direct_output_text.strip(), None

        choices = data.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            content = message.get("content", "")

            if isinstance(content, str):
                return content.strip(), None

            if isinstance(content, list):
                text, error = self._extract_content_parts(content)
                if text:
                    return text, None
                if error:
                    return "", error

        output_blocks = data.get("output", [])
        if isinstance(output_blocks, list):
            text_parts: list[str] = []
            for block in output_blocks:
                if not isinstance(block, dict):
                    continue
                content = block.get("content")
                if isinstance(content, str) and content.strip():
                    text_parts.append(content.strip())
                    continue
                if isinstance(content, list):
                    text, _ = self._extract_content_parts(content)
                    if text:
                        text_parts.append(text)
            combined = "\n".join(part for part in text_parts if part).strip()
            if combined:
                return combined, None

        error_message = self._extract_error_message(data)
        if error_message:
            return "", f"api error: {error_message}"
        if not choices:
            return "", "response contained no choices or output blocks"
        return "", "could not extract text from OpenAI response content"

    def _extract_content_parts(self, content: list[object]) -> tuple[str, str | None]:
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            item_type = item.get("type", "")
            if item_type in {"text", "output_text", "input_text"} and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
                continue
            if item_type in {"output_text", "text"} and isinstance(item.get("value"), str):
                text_parts.append(item["value"])
                continue
            inner_text = item.get("text")
            if isinstance(inner_text, dict):
                value = inner_text.get("value")
                if isinstance(value, str):
                    text_parts.append(value)
                    continue
            for key in ("content", "value"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    text_parts.append(value.strip())
                    break
        combined = "\n".join(part.strip() for part in text_parts if part.strip()).strip()
        if combined:
            return combined, None
        return "", "content parts contained no usable text fragments"

    def _raw_preview(self, data: object, limit: int = 600) -> str:
        try:
            preview = json.dumps(data, ensure_ascii=False)
        except Exception:
            preview = str(data)
        return preview[:limit]

    def distill(self, prompt: str, *, timeout: int = 30) -> DistillResult:
        if not self.api_key:
            _log_distiller_event("openai", f"config error: missing OPENAI_API_KEY | model={self.model}")
            return DistillResult(
                text="SKIP",
                backend="openai",
                model=self.model,
                error="OPENAI_API_KEY is not set",
            )

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        }
        _log_distiller_event(
            "openai",
            f"request start | model={self.model} base_url={self.base_url} prompt_chars={len(prompt)}",
        )
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                data = json.loads(body)
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            parsed_message = None
            if body:
                try:
                    parsed_message = self._extract_error_message(json.loads(body))
                except Exception:
                    parsed_message = None
            message = f"http {exc.code}: {parsed_message or body[:300] or exc.reason}"
            _log_distiller_event("openai", f"{message} | body={body[:600]}")
            return DistillResult(
                text="SKIP",
                backend="openai",
                model=self.model,
                error=message,
                raw_preview=body[:600] if body else None,
            )
        except urllib.error.URLError as exc:
            message = f"url error: {exc.reason}"
            _log_distiller_event("openai", message)
            return DistillResult(
                text="SKIP",
                backend="openai",
                model=self.model,
                error=message,
            )
        except TimeoutError:
            message = f"timeout after {timeout}s"
            _log_distiller_event("openai", message)
            return DistillResult(
                text="SKIP",
                backend="openai",
                model=self.model,
                error=message,
            )
        except json.JSONDecodeError as exc:
            message = f"invalid json response: {exc}"
            _log_distiller_event("openai", f"{message} | body={body[:600] if 'body' in locals() else ''}")
            return DistillResult(
                text="SKIP",
                backend="openai",
                model=self.model,
                error=message,
            )

        text, extraction_error = self._extract_message_text(data)
        preview = self._raw_preview(data)
        if not text:
            message = extraction_error or "empty response content"
            _log_distiller_event("openai", f"{message} | preview={preview}")
            return DistillResult(
                text="SKIP",
                backend="openai",
                model=self.model,
                error=message,
                raw_preview=preview,
            )
        _log_distiller_event(
            "openai",
            f"success model={self.model} chars={len(text)} preview={text[:160].replace(chr(10), ' ')}",
        )
        return DistillResult(
            text=text,
            backend="openai",
            model=self.model,
            raw_preview=preview,
        )


class NullDistiller:
    def distill(self, prompt: str, *, timeout: int = 30) -> DistillResult:
        del prompt, timeout
        return DistillResult(
            text="SKIP",
            backend="null",
            model=None,
            error="null distiller selected",
        )


def get_distiller_from_env() -> Distiller:
    backend = os.environ.get("SKILLS_DISTILLER_BACKEND", "claude-cli").strip().lower()
    if backend == "openai":
        return OpenAIDistiller()
    if backend == "null":
        return NullDistiller()
    return ClaudeCliDistiller()
