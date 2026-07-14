from typing import List
try:
    from sumy.nlp.tokenizers import Tokenizer
    from sumy.parsers.plaintext import PlaintextParser
    from sumy.summarizers.text_rank import TextRankSummarizer
except Exception:
    Tokenizer = None

def _fallback(text: str) -> str:
    text = text or ""
    return (text[:800] + "...") if len(text) > 800 else text

def summarize(parts: List[str], sentences: int = 3) -> str:
    text = "\n".join([p for p in parts if isinstance(p, str)])
    if not text.strip():
        return "（未找到足夠資料）"
    try:
        if Tokenizer is None:
            return _fallback(text)
        parser = PlaintextParser.from_string(text, Tokenizer("english"))
        summarizer = TextRankSummarizer()
        sents = summarizer(parser.document, sentences)
        out = " ".join(str(s) for s in sents)
        return out.strip() or _fallback(text)
    except Exception:
        return _fallback(text)
