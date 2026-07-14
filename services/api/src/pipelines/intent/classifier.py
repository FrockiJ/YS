import re
_WINE_TERMS = [
    r"葡萄酒|紅酒|白酒|香檳|起泡|氣泡|酒款|年份|酒莊|產區|風土|風味|酸度|甜度|單寧|餘韻|酒體|釀造|桶|酵母|蘋果酸乳酸|MLF|劃渣|澄清|二次發酵|瓶陳|除渣|添糖|劑量|dosage|brut|sec|doux|熟成",
    r"布根地|勃艮第|波爾多|香檳區|夏布利|羅亞爾|隆河|Rioja|Toscana|Napa|Mendoza",
    r"黑皮諾|Pinot|霞多麗|Chardonnay|梅洛|Merlot|卡本內|Cabernet|西拉|Syrah|長相思|Sauvignon",
    r"(19|20)\d{2}\s*年"
]
def related_score(q: str) -> float:
    import re
    q = (q or "").strip()
    if not q: return 0.0
    score = sum(1 for pat in _WINE_TERMS if re.search(pat, q, flags=re.I))
    return min(1.0, score / 4.0)
def classify(q: str) -> str:
    q = (q or "").strip()
    if not q: return "unknown"
    return "wine_related" if related_score(q) >= 0.25 else "generic"