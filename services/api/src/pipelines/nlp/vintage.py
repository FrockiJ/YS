import re
def extract_vintages(q: str):
    if not q: return []
    yrs = set(int(y) for y in re.findall(r"(18|19|20)\d{2}", q))
    # 限合理年份
    return sorted(y for y in yrs if 1800 <= y <= 2025)