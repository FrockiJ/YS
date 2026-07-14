import re
from typing import Iterable, Iterator, List


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.\!\?。！？；;])\s+")


def simple_chunks(text: str, max_len: int = 1200) -> Iterator[str]:
    text = (text or "").replace("\r", "")
    paras = re.split(r"\n\s*\n", text)
    yield from _merge_paragraphs(paras, max_len=max_len)


def guided_pdf_chunks(text: str, max_len: int = 1000) -> Iterator[str]:
    normalized = (text or "").replace("\r", "")
    paras = [_normalize_paragraph(paragraph) for paragraph in re.split(r"\n\s*\n", normalized)]
    buffer: List[str] = []
    size = 0
    for paragraph in paras:
        if not paragraph:
            continue
        if _looks_like_heading(paragraph) and buffer:
            yield "\n\n".join(buffer)
            buffer, size = [], 0
        if len(paragraph) > max_len:
            if buffer:
                yield "\n\n".join(buffer)
                buffer, size = [], 0
            for fragment in _split_long_text(paragraph, max_len=max_len):
                if fragment:
                    yield fragment
            continue
        if size and size + len(paragraph) + 2 > max_len:
            yield "\n\n".join(buffer)
            buffer, size = [paragraph], len(paragraph)
            continue
        buffer.append(paragraph)
        size += len(paragraph) + 2
    if buffer:
        yield "\n\n".join(buffer)


def _merge_paragraphs(paragraphs: Iterable[str], *, max_len: int) -> Iterator[str]:
    buffer: List[str] = []
    size = 0
    for paragraph in paragraphs:
        normalized = _normalize_paragraph(paragraph)
        if not normalized:
            continue
        if len(normalized) > max_len:
            if buffer:
                yield "\n\n".join(buffer)
                buffer, size = [], 0
            for fragment in _split_long_text(normalized, max_len=max_len):
                if fragment:
                    yield fragment
            continue
        if size and size + len(normalized) + 2 > max_len:
            yield "\n\n".join(buffer)
            buffer, size = [normalized], len(normalized)
            continue
        buffer.append(normalized)
        size += len(normalized) + 2
    if buffer:
        yield "\n\n".join(buffer)


def _normalize_paragraph(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _looks_like_heading(paragraph: str) -> bool:
    compact = paragraph.strip()
    if not compact:
        return False
    if len(compact) <= 90 and re.fullmatch(r"[A-Z0-9 \-,'/&:]+", compact):
        return True
    if len(compact) <= 60 and re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9：:、，,\- ]+", compact):
        word_count = len(compact.split())
        return word_count <= 10
    return False


def _split_long_text(text: str, *, max_len: int) -> Iterator[str]:
    sentences = [sentence.strip() for sentence in _SENTENCE_SPLIT_RE.split(text or "") if sentence.strip()]
    if not sentences:
        compact = (text or "").strip()
        if compact:
            for index in range(0, len(compact), max_len):
                yield compact[index:index + max_len].strip()
        return

    buffer: List[str] = []
    size = 0
    for sentence in sentences:
        if len(sentence) > max_len:
            if buffer:
                yield " ".join(buffer).strip()
                buffer, size = [], 0
            for index in range(0, len(sentence), max_len):
                fragment = sentence[index:index + max_len].strip()
                if fragment:
                    yield fragment
            continue
        if size and size + len(sentence) + 1 > max_len:
            yield " ".join(buffer).strip()
            buffer, size = [sentence], len(sentence)
            continue
        buffer.append(sentence)
        size += len(sentence) + 1
    if buffer:
        yield " ".join(buffer).strip()
