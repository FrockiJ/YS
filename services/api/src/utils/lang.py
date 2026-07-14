import re

def detect_lang(text: str) -> str:
    """Detect the answer language from the user's current message."""
    if not isinstance(text, str):
        return "en"
    normalized = text.strip()
    if not normalized:
        return "en"
    if re.search(r"[\u3040-\u30ff]", normalized):
        return "ja"
    if re.search(r"[\u4e00-\u9fff]", normalized):
        return "zh-Hant"
    return "en"

def hint_query_for_lang(text: str, lang: str) -> str:
    """Embed a lightweight instruction in the query to bias generator language
    without harming vector search (use original text for search; use hinted text for generation).
    """
    return text
