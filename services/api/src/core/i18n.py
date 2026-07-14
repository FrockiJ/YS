import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_LANG = "zh-Hant"
SUPPORTED_LANGS = {"zh-Hant", "en", "ja"}
LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"


def normalize_lang(lang: Optional[str]) -> str:
    if not lang:
        return DEFAULT_LANG
    value = str(lang).strip()
    if not value:
        return DEFAULT_LANG
    lower = value.lower()
    if lower.startswith("zh"):
        return "zh-Hant"
    if lower.startswith("en"):
        return "en"
    if lower.startswith("ja") or lower.startswith("jp"):
        return "ja"
    return DEFAULT_LANG


def _resolve_key(payload: Dict[str, Any], key: str) -> Optional[Any]:
    node: Any = payload
    for part in key.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


@lru_cache(maxsize=8)
def _load_locale(lang: str) -> Dict[str, Any]:
    normalized = lang.strip().lower()
    if normalized in {"zh-hant", "zh_tw", "zh-tw"}:
        lang = "zh-tw"
    elif normalized in {"ja", "ja-jp", "jp"}:
        lang = "ja"
    path = LOCALES_DIR / f"{lang}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def t(key: str, lang: Optional[str] = None, **kwargs: Any) -> str:
    resolved_lang = normalize_lang(lang)
    payload = _load_locale(resolved_lang)
    value = _resolve_key(payload, key)
    if value is None and resolved_lang != "en":
        value = _resolve_key(_load_locale("en"), key)
    if value is None:
        return key
    if isinstance(value, str) and kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, ValueError):
            return value
    return str(value)
