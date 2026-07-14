from pdfminer.high_level import extract_text, extract_pages
from pdfminer.layout import LTTextContainer
def extract_pdf_text(path: str) -> str:
    try: return extract_text(path) or ""
    except Exception: return ""
def iter_pages_text(path: str):
    try:
        for pi, page_layout in enumerate(extract_pages(path)):
            parts=[]
            for el in page_layout:
                if isinstance(el, LTTextContainer): parts.append(el.get_text())
            yield pi+1, "".join(parts)
    except Exception:
        yield None, extract_pdf_text(path)
