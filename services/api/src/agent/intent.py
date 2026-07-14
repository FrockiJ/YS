import re
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

class IntentLabel:
    WINE_QA = "WINE_QA"
    VINTAGE_INFO = "VINTAGE_INFO"
    REGION_INFO = "REGION_INFO"
    PRODUCER_INFO = "PRODUCER_INFO"
    BOTTLE_INFO = "BOTTLE_INFO"
    PRICE_AVAILABILITY = "PRICE_AVAILABILITY"
    FOOD_PAIRING = "FOOD_PAIRING"
    STORAGE_SERVICE = "STORAGE_SERVICE"
    CHITCHAT = "CHITCHAT"
    NON_WINE = "NON_WINE"
    AMBIGUOUS = "AMBIGUOUS"
    AUTH_LOGIN = "AUTH_LOGIN"

REGION_ALIASES = {
    "勃根地": ["勃根地", "布根地", "Burgundy", "Bourgogne", "ブルゴーニュ"],
    "波爾多": ["波爾多", "Bordeaux", "ボルドー"],
    "香檳": ["香檳", "香槟", "シャンパーニュ", "Champagne"],
    "羅亞爾河": ["羅亞爾", "羅亞爾河", "Loire"],
    "隆河": ["隆河", "羅訥河", "Rhone", "Rhône"],
    "夜丘": ["夜丘", "Côte de Nuits"],
    "伯恩丘": ["伯恩丘", "Côte de Beaune"],
    "夏布利": ["夏布利", "Chablis"],
}

GRAPE_KEYWORDS = [
    "Pinot Noir", "黑皮諾", "黑皮诺",
    "Chardonnay", "夏多內", "霞多麗", "霞多丽",
    "Gamay", "佳美",
    "Cabernet Sauvignon", "卡本內蘇維濃", "卡本內",
    "Merlot", "梅洛",
    "Syrah", "西拉"
]

PRICE_TERMS = ["價", "價格", "多少錢", "售價", "報價", "入手", "買得到", "庫存", "現貨", "缺貨", "有沒有貨", "price"]
PAIRING_TERMS = ["搭餐", "配餐", "料理", "吃什麼", "配什麼", "pairing"]
STORAGE_TERMS = ["保存", "儲存", "存放", "溫度", "濕度", "醒酒", "運送", "配送", "運費", "包裝"]
LOGIN_TERMS = ["登入", "登录", "login", "sign in", "帳號", "账号", "密碼", "密码"]

@dataclass
class IntentResult:
    label: str
    score: float
    year: Optional[int] = None
    region: Optional[str] = None
    grape: Optional[str] = None
    producer: Optional[str] = None
    wine_name: Optional[str] = None
    tokens: Optional[List[str]] = None
    debug: Optional[Dict[str, Any]] = None

YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")

def find_year(text: str) -> Optional[int]:
    m = YEAR_RE.search(text)
    if m:
        y = int(m.group(1))
        if 1900 <= y <= 2100:
            return y
    return None

def find_region(text: str) -> Optional[str]:
    t = text.lower()
    for canon, arr in REGION_ALIASES.items():
        for a in arr:
            if a.lower() in t:
                return canon
    return None

def find_grape(text: str) -> Optional[str]:
    t = text.lower()
    for g in GRAPE_KEYWORDS:
        if g.lower() in t:
            return g
    return None

def rule_first(text: str) -> 'IntentResult':
    t = text.strip()
    tl = t.lower()

    if any(x in t for x in LOGIN_TERMS) or ("@" in t and (" 密碼" in t or " password" in tl)):
        return IntentResult(label=IntentLabel.AUTH_LOGIN, score=0.95, debug={"why":"login keywords"})

    if any(x in tl for x in ["手機", "保險", "旅遊", "機票", "股票", "程式碼", "安卓", "ios", "xcode"]):
        return IntentResult(label=IntentLabel.NON_WINE, score=0.95, debug={"why": "non-wine keyword"})

    is_winey = any(x in tl for x in ["酒", "葡萄酒", "紅酒", "白酒", "香檳", "氣泡", "champagne", "bourgogne", "bordeaux"])

    year = find_year(t)
    region = find_region(t)
    grape = find_grape(t)

    if any(x in t for x in PRICE_TERMS):
        return IntentResult(label=IntentLabel.PRICE_AVAILABILITY, score=0.9, year=year, region=region, grape=grape)
    if any(x in t for x in PAIRING_TERMS):
        return IntentResult(label=IntentLabel.FOOD_PAIRING, score=0.9, year=year, region=region, grape=grape)
    if any(x in t for x in STORAGE_TERMS):
        return IntentResult(label=IntentLabel.STORAGE_SERVICE, score=0.9, year=year, region=region, grape=grape)
    if year and is_winey:
        return IntentResult(label=IntentLabel.VINTAGE_INFO, score=0.85, year=year, region=region, grape=grape)
    if (region or grape) and is_winey:
        return IntentResult(label=IntentLabel.REGION_INFO, score=0.8, year=year, region=region, grape=grape)
    if is_winey:
        return IntentResult(label=IntentLabel.WINE_QA, score=0.7, year=year, region=region, grape=grape)

    if len(t) <= 2:
        return IntentResult(label=IntentLabel.AMBIGUOUS, score=0.5, debug={"why": "too short"})
    return IntentResult(label=IntentLabel.AMBIGUOUS, score=0.4)

def classify_intent(text: str) -> 'IntentResult':
    return rule_first(text)
