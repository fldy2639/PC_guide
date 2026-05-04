from __future__ import annotations

import json
import re
from typing import Any

import httpx

from pc_build_agent.config import settings


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        return m.group(1).strip()
    return text


def _append_trace(
    sink: list[dict[str, Any]],
    *,
    step: str,
    model: str,
    payload_request: dict[str, Any],
    http_status: int,
    response_data: dict[str, Any],
    parse_error: str | None = None,
    parsed_json: dict[str, Any] | None = None,
) -> None:
    choice0 = (response_data.get("choices") or [{}])[0]
    msg = choice0.get("message") if isinstance(choice0, dict) else {}
    if not isinstance(msg, dict):
        msg = {}
    sink.append(
        {
            "step": step,
            "model": model,
            "request": payload_request,
            "http_status": http_status,
            "usage": response_data.get("usage"),
            "finish_reason": choice0.get("finish_reason") if isinstance(choice0, dict) else None,
            # 上游若为推理模型，常见字段：reasoning_content（思维过程）；普通对话模型通常仅有 content
            "assistant_message": {
                "role": msg.get("role"),
                "content": msg.get("content"),
                "reasoning_content": msg.get("reasoning_content"),
            },
            "parse_error": parse_error,
            "parsed_json_preview": parsed_json,
        }
    )


class DeepSeekClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.deepseek_api_key
        self.base_url = (base_url or settings.deepseek_base_url).rstrip("/")
        self.model = model or settings.deepseek_model
        self.timeout_s = timeout_s

    def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        *,
        trace_sink: list[dict[str, Any]] | None = None,
        step: str = "chat_json",
    ) -> dict:
        if not self.api_key:
            raise RuntimeError("缺少 DEEPSEEK_API_KEY，请在环境变量或 .env 中配置")

        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        parse_error: str | None = None
        parsed: dict[str, Any] | None = None

        with httpx.Client(timeout=self.timeout_s) as client:
            r = client.post(url, headers=headers, json=payload)
            http_status = r.status_code
            r.raise_for_status()
            data = r.json()

        content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        raw = _strip_json_fence(content)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            parse_error = str(exc)
            if trace_sink is not None:
                req_snapshot = {
                    "model": payload["model"],
                    "temperature": payload["temperature"],
                    "response_format": payload["response_format"],
                    "messages": messages,
                }
                _append_trace(
                    trace_sink,
                    step=step,
                    model=self.model,
                    payload_request=req_snapshot,
                    http_status=http_status,
                    response_data=data,
                    parse_error=parse_error,
                    parsed_json=None,
                )
            raise

        if trace_sink is not None:
            req_snapshot = {
                "model": payload["model"],
                "temperature": payload["temperature"],
                "response_format": payload["response_format"],
                "messages": messages,
            }
            preview = parsed
            if isinstance(parsed, dict) and len(json.dumps(parsed, ensure_ascii=False)) > 8000:
                preview = {"_truncated": True, "keys": list(parsed.keys())}
            _append_trace(
                trace_sink,
                step=step,
                model=self.model,
                payload_request=req_snapshot,
                http_status=http_status,
                response_data=data,
                parse_error=None,
                parsed_json=preview,
            )

        return parsed

    def chat_text(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.4,
        *,
        trace_sink: list[dict[str, Any]] | None = None,
        step: str = "chat_text",
    ) -> str:
        if not self.api_key:
            raise RuntimeError("缺少 DEEPSEEK_API_KEY")

        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        with httpx.Client(timeout=self.timeout_s) as client:
            r = client.post(url, headers=headers, json=payload)
            http_status = r.status_code
            r.raise_for_status()
            data = r.json()

        msg = (data.get("choices") or [{}])[0].get("message") or {}
        text = (msg.get("content") or "").strip()

        if trace_sink is not None:
            req_snapshot = {
                "model": payload["model"],
                "temperature": payload["temperature"],
                "messages": messages,
            }
            _append_trace(
                trace_sink,
                step=step,
                model=self.model,
                payload_request=req_snapshot,
                http_status=http_status,
                response_data=data,
                parse_error=None,
                parsed_json=None,
            )

        return text


def get_client() -> DeepSeekClient:
    return DeepSeekClient()
