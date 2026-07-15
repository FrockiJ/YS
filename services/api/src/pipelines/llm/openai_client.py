import asyncio
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from threading import Lock
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


@dataclass
class LLMRequestBudget:
    """Counts real provider requests, not logical helper invocations."""

    limit: int = 2
    used: int = 0
    planner_calls: int = 0
    final_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    blocked_retries: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def reserve(self, role: str) -> None:
        with self._lock:
            if self.used >= self.limit:
                self.blocked_retries += 1
                raise RuntimeError("LLM request budget exhausted")
            self.used += 1
            if role == "planner":
                self.planner_calls += 1
            elif role == "final":
                self.final_calls += 1

    def add_usage(self, usage: Dict[str, Any]) -> None:
        with self._lock:
            self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
            self.completion_tokens += int(usage.get("completion_tokens") or 0)
            self.total_tokens += int(usage.get("total_tokens") or 0)

    def snapshot(self) -> Dict[str, int]:
        return {
            "limit": self.limit,
            "used": self.used,
            "planner_calls": self.planner_calls,
            "final_calls": self.final_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "blocked_retries": self.blocked_retries,
        }


@dataclass(frozen=True)
class ChatCompletionResult:
    content: str
    usage: Dict[str, int]
    model: Optional[str]


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
    max_completion_tokens: Optional[int] = None,
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
    if max_completion_tokens is not None:
        payload["max_completion_tokens"] = max(1, int(max_completion_tokens))
    return payload


def _request_chat_completion(
    payload: Dict[str, object],
    trace: Optional[Dict[str, Any]] = None,
) -> ChatCompletionResult:
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
        return ChatCompletionResult(
            content=f"[Offline] OPENAI_API_KEY is not configured, unable to generate an answer.\n\n{head}",
            usage={},
            model=str(payload.get("model") or "") or None,
        )

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
    usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else {}
    return ChatCompletionResult(
        content=str(obj["choices"][0]["message"]["content"] or ""),
        usage={
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        },
        model=str(obj.get("model") or payload.get("model") or "") or None,
    )


def _sync_chat_complete_result(
    system: str,
    user: str,
    history: list = None,
    temperature: float = 0.7,
    trace: Optional[Dict[str, Any]] = None,
    response_format: Optional[Dict[str, Any]] = None,
    max_completion_tokens: Optional[int] = None,
    budget: Optional[LLMRequestBudget] = None,
    role: str = "general",
    allow_model_fallback: bool = True,
) -> ChatCompletionResult:
    primary_model, fallback_model = _resolve_models()
    errors: list[str] = []
    attempts = _model_attempts(primary_model, fallback_model if allow_model_fallback else None)
    for model in attempts:
        payload = _build_payload(
            model,
            system,
            user,
            history,
            temperature,
            response_format,
            max_completion_tokens,
        )
        if trace is not None:
            trace["llm_request_payload"] = payload
            trace["llm_request_messages"] = payload.get("messages") or []
            trace["llm_model_attempted"] = model
            trace["llm_called"] = True
            trace["generation_type"] = "llm_generation"
            trace["no_llm_reason"] = None
        try:
            if budget is not None and os.getenv("OPENAI_API_KEY"):
                budget.reserve(role)
            raw_result = _request_chat_completion(payload, trace=trace)
            result = (
                raw_result
                if isinstance(raw_result, ChatCompletionResult)
                else ChatCompletionResult(content=str(raw_result or ""), usage={}, model=model)
            )
            if budget is not None:
                budget.add_usage(result.usage)
            return result
        except urllib.error.HTTPError as exc:
            errors.append(f"{model}: HTTP {exc.code}")
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            if allow_model_fallback and fallback_model and model != fallback_model:
                continue
            raise OpenAIChatHTTPError(model=model, status=int(exc.code), body=body) from exc
        except Exception as exc:
            errors.append(f"{model}: {type(exc).__name__}")
            if allow_model_fallback and fallback_model and model != fallback_model:
                continue
            raise
    raise RuntimeError("; ".join(errors) or "OpenAI call failed")


def _sync_chat_complete(
    system: str,
    user: str,
    history: list = None,
    temperature: float = 0.7,
    trace: Optional[Dict[str, Any]] = None,
    response_format: Optional[Dict[str, Any]] = None,
    max_completion_tokens: Optional[int] = None,
    budget: Optional[LLMRequestBudget] = None,
    role: str = "general",
    allow_model_fallback: bool = True,
) -> str:
    return _sync_chat_complete_result(
        system,
        user,
        history,
        temperature,
        trace,
        response_format,
        max_completion_tokens,
        budget,
        role,
        allow_model_fallback,
    ).content


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
    max_completion_tokens: Optional[int] = None,
    budget: Optional[LLMRequestBudget] = None,
    role: str = "general",
    allow_model_fallback: bool = True,
) -> str:
    result = await asyncio.to_thread(
        _sync_chat_complete_result,
        system,
        user,
        history,
        temperature,
        trace,
        response_format,
        max_completion_tokens,
        budget,
        role,
        allow_model_fallback,
    )
    return result.content


async def chat_complete_result(
    system: str,
    user: str,
    history: list = None,
    temperature: float = 0.7,
    trace: Optional[Dict[str, Any]] = None,
    response_format: Optional[Dict[str, Any]] = None,
    max_completion_tokens: Optional[int] = None,
    budget: Optional[LLMRequestBudget] = None,
    role: str = "general",
    allow_model_fallback: bool = True,
) -> ChatCompletionResult:
    return await asyncio.to_thread(
        _sync_chat_complete_result,
        system,
        user,
        history,
        temperature,
        trace,
        response_format,
        max_completion_tokens,
        budget,
        role,
        allow_model_fallback,
    )
