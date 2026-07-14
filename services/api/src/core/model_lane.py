import os
from typing import Dict, Mapping, Optional


VALID_MODEL_LANES = {"base", "fine_tuned_canary", "fine_tuned"}
DEFAULT_STYLE_EVAL_VERSION = "phase3_style_eval_v1"


def _env_value(env: Mapping[str, str], name: str) -> str:
    return str(env.get(name) or "").strip()


def normalize_model_lane(value: Optional[str]) -> str:
    lane = str(value or "").strip().lower()
    return lane if lane in VALID_MODEL_LANES else "base"


def resolve_model_config(
    *,
    default_base_model: str = "gpt-5.5",
    env: Optional[Mapping[str, str]] = None,
) -> Dict[str, object]:
    source = env or os.environ
    requested_lane = normalize_model_lane(_env_value(source, "AI_MODEL_LANE"))
    base_model = _env_value(source, "OPENAI_CHAT_MODEL") or default_base_model
    configured_fallback = _env_value(source, "OPENAI_FALLBACK_CHAT_MODEL") or None
    fine_tuned_model = _env_value(source, "OPENAI_FINE_TUNED_CHAT_MODEL") or None

    active_lane = requested_lane
    primary_model = base_model
    using_fine_tuned = False
    if requested_lane in {"fine_tuned_canary", "fine_tuned"} and fine_tuned_model:
        primary_model = fine_tuned_model
        using_fine_tuned = True
        fallback_model = base_model if base_model != primary_model else configured_fallback
    else:
        active_lane = "base"
        fallback_model = configured_fallback

    if fallback_model == primary_model:
        fallback_model = None

    return {
        "requested_model_lane": requested_lane,
        "model_lane": active_lane,
        "primary_model": primary_model,
        "base_model": base_model,
        "fine_tuned_model": fine_tuned_model,
        "fallback_model": fallback_model,
        "using_fine_tuned_model": using_fine_tuned,
        "phase3_style_eval_version": (
            _env_value(source, "PHASE3_STYLE_EVAL_VERSION") or DEFAULT_STYLE_EVAL_VERSION
        ),
    }
