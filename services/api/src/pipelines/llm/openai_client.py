import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, Optional, Tuple

from ...core.model_lane import resolve_model_config

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
ALLOW_TEMPERATURE_OVERRIDE = os.getenv("ALLOW_TEMPERATURE_OVERRIDE", "false").lower() in ("true", "1", "t")


class OpenAIChatHTTPError(RuntimeError):
    def __init__(self, *, model: str, status: int, body: str) -> None:
        super().__init__(f"{model}: HTTP {status}")
        self.model = model
        self.status = status
        self.body = body


def _resolve_models() -> Tuple[str, Optional[str]]:
    config = resolve_model_config(default_base_model="gpt-5.5")
    return str(config["primary_model"]), config["fallback_model"]  # type: ignore[return-value]


def _build_payload(
    model: str,
    system: str,
    user: str,
    history: list | None,
    temperature: float,
    response_format: Optional[Dict[str, Any]] = None,
) -> Dict[str, object]:
    messages = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    else:
        messages.append({"role": "user", "content": user})
    payload: Dict[str, object] = {
        "model": model,
        "messages": messages,
    }
    if ALLOW_TEMPERATURE_OVERRIDE:
        try:
            payload["temperature"] = float(temperature)
        except (TypeError, ValueError):
            pass
    if response_format:
        payload["response_format"] = response_format
    return payload


def _request_chat_completion(payload: Dict[str, object], trace: Optional[Dict[str, Any]] = None) -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        head = (str((payload.get("messages") or [{"content": ""}])[-1].get("content")) or "")[:400]
        if trace is not None:
            trace["llm_response_json"] = {
                "offline": True,
                "reason": "OPENAI_API_KEY is not configured",
            }
            trace["llm_called"] = False
            trace["generation_type"] = "offline_no_llm"
            trace["no_llm_reason"] = "OPENAI_API_KEY is not configured"
        return f"[Offline] OPENAI_API_KEY is not configured, unable to generate an answer.\n\n{head}"

    url = OPENAI_BASE_URL.rstrip("/") + "/chat/completions"
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        body = response.read()
    obj = json.loads(body.decode("utf-8"))
    if trace is not None:
        trace["llm_response_json"] = obj
    return obj["choices"][0]["message"]["content"]


def _sync_chat_complete(
    system: str,
    user: str,
    history: list = None,
    temperature: float = 0.7,
    trace: Optional[Dict[str, Any]] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> str:
    primary_model, fallback_model = _resolve_models()
    errors: list[str] = []
    for model in _model_attempts(primary_model, fallback_model):
        payload = _build_payload(model, system, user, history, temperature, response_format)
        if trace is not None:
            trace["llm_request_payload"] = payload
            trace["llm_request_messages"] = payload.get("messages") or []
            trace["llm_model_attempted"] = model
            trace["llm_called"] = True
            trace["generation_type"] = "llm_generation"
            trace["no_llm_reason"] = None
        try:
            return _request_chat_completion(payload, trace=trace)
        except urllib.error.HTTPError as exc:
            errors.append(f"{model}: HTTP {exc.code}")
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            if fallback_model and model != fallback_model:
                continue
            raise OpenAIChatHTTPError(model=model, status=int(exc.code), body=body) from exc
        except Exception as exc:
            errors.append(f"{model}: {type(exc).__name__}")
            if fallback_model and model != fallback_model:
                continue
            raise
    raise RuntimeError("; ".join(errors) or "OpenAI call failed")


def _model_attempts(primary: str, fallback: Optional[str]) -> Iterable[str]:
    yield primary
    if fallback and fallback != primary:
        yield fallback


async def chat_complete(
    system: str,
    user: str,
    history: list = None,
    temperature: float = 0.7,
    trace: Optional[Dict[str, Any]] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> str:
    return await asyncio.to_thread(
        _sync_chat_complete,
        system,
        user,
        history,
        temperature,
        trace,
        response_format,
    )
