from typing import List
import re

def summarize(texts: List[str], sentences: int = 6) -> str:
    text = "\n".join([t for t in texts if t]).strip()
    if not text: return "（未找到足夠資料）"
    sents = re.split(r"(?<=[。！？.!?])\s+", text)
    return " ".join(sents[:sentences])