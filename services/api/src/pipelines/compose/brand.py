
from typing import List, Dict, Any, Tuple
import re

from ...core.store_profile import get_store_profile

_STORE_PROFILE = get_store_profile()
_STORE_PREFERRED_BRANDS = _STORE_PROFILE.get("preferred_brands") if isinstance(_STORE_PROFILE, dict) else None

PREFERRED_BRANDS_DEFAULT = (
    _STORE_PREFERRED_BRANDS
    if isinstance(_STORE_PREFERRED_BRANDS, list) and _STORE_PREFERRED_BRANDS
    else [
        "Decanter",
        "Jancis Robinson",
        "VDP",
        "WOSA",
        "Wine Australia",
        "The Wine Independent",
        "Wine-Searcher",
        "Vinfolio",
        "nzwine",
        "wosa.co.za",
        "vdp.de",
        "nzwine.com",
        "wineaustralia.com",
    ]
)

_BRAND_ALIASES = {
    "Decanter": [r"\bdecanter\b"],
    "Jancis Robinson": [r"\bjancis\b", r"\bjancis\s+robinson\b"],
    "VDP": [r"\bvdp\.?\.?de\b", r"\bvdp\b"],
    "WOSA": [r"\bwosa\b", r"wosa\.co\.za"],
    "Wine Australia": [r"wineaustralia\.com"],
    "The Wine Independent": [r"the\s+wine\s+independent"],
    "Wine-Searcher": [r"wine-searcher\.com", r"\bwine[-\s]?searcher\b"],
    "Vinfolio": [r"\bvinfolio\b"],
    "nzwine": [r"nzwine\.com", r"\bnz\s*wine\b"],
}

def canonical_brand(s: str) -> str:
    if not s:
        return ""
    s_low = s.lower()
    for brand, pats in _BRAND_ALIASES.items():
        for p in pats:
            if re.search(p, s_low):
                return brand
    m = re.search(r"https?://([^/\s]+)", s_low)
    if m:
        host = m.group(1)
        for brand in PREFERRED_BRANDS_DEFAULT:
            if brand.lower().split()[0] in host:
                return brand
        return host
    return s.strip()

def brand_of(source: str = "", title: str = "", text: str = "") -> str:
    for s in (source or "", title or "", text or ""):
        b = canonical_brand(s)
        if b and b != s:
            return b
    return canonical_brand(source or title)

def order_by_brand(evidence: List[Dict[str, Any]], preferred: List[str]) -> List[Dict[str, Any]]:
    idx = {b:i for i,b in enumerate(preferred)}
    def score(ev):
        b = brand_of(ev.get("source",""), ev.get("title",""), ev.get("excerpt",""))
        return (idx.get(b, len(preferred)), -len(ev.get("excerpt","")), ev.get("title","")[:6])
    return sorted(evidence, key=score)

def summarize_brand_counts(evidence: List[Dict[str, Any]]) -> List[Tuple[str, int]]:
    counts = {}
    for ev in evidence:
        b = brand_of(ev.get("source",""), ev.get("title",""), ev.get("excerpt","")) or "(unknown)"
        counts[b] = counts.get(b, 0) + 1
    return sorted(counts.items(), key=lambda x: (-x[1], x[0]))
