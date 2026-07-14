from typing import List, Dict, Any, Tuple
import json, re
from collections import Counter

def _norm_meta(m) -> Dict[str, Any]:
    if isinstance(m, dict): return m
    if isinstance(m, str):
        try: return json.loads(m)
        except: return {}
    return {}

def _mk_citations(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cites = []
    for h in hits or []:
        m = _norm_meta(h.get("meta"))
        src = h.get("filename") or m.get("filename") or "doc"
        page = h.get("page") or m.get("page")
        frag = h.get("chunk_idx")
        href = None
        if src and page:
            # 讓前端直接渲染成可點連結（/console 的檢視錨點）
            href = f"/console?file={src}#page={page}"
        cites.append({"source": src, "page": page, "frag": frag, "href": href})
    # 去重
    uniq, seen = [], set()
    for c in cites:
        key = (c.get("source"), c.get("page"), c.get("frag"))
        if key in seen: continue
        seen.add(key); uniq.append(c)
    return uniq

def _extract_points(hits: List[Dict[str, Any]], limit=5) -> List[str]:
    """從 RAG 片段抽出較完整的句子當『要點』。"""
    sents = []
    for h in hits or []:
        t = (h.get("summary") or h.get("text") or "").strip()
        # 拆成句子（中文/英文混合）
        parts = re.split(r"[。！？!?\n]+", t)
        for p in parts:
            p = p.strip()
            if 6 <= len(p) <= 120:
                sents.append(p)
    # 去重與選前幾條
    uniq, seen = [], set()
    for s in sents:
        k = s
        if k in seen: continue
        seen.add(k); uniq.append(s)
        if len(uniq) >= limit: break
    return uniq

def _short_conclusion(points: List[str]) -> str:
    if not points:
        return "目前索引裡沒有足夠的依據可回答這題。"
    # 用最具代表性的前一句做短評骨架
    s = points[0]
    # 簡單加上『整體』語氣
    return f"整體來看，{s}。"

def _keywords(hits: List[Dict[str, Any]]) -> Tuple[str, List[str]]:
    bag = []
    for h in hits or []:
        t = (h.get("text") or "")
        bag += re.findall(r"[A-Za-z\u4e00-\u9fff]{2,}", t)
    cnt = Counter([w.lower() for w in bag if len(w) <= 12])
    top = [w for w, _ in cnt.most_common(6)]
    # 假裝一個『風格/建議』模板：若有酸度/礦物/果香等詞頻
    tips = []
    kw = "、".join(top[:4]) if top else ""
    if any(k in cnt for k in ["酸度","acidity","酸"]):
        tips.append("酸度表現明顯，建議搭配海鮮或鹹點。")
    if any(k in cnt for k in ["礦物","mineral"]):
        tips.append("礦物感突出，風格偏向清爽挺直。")
    if any(k in cnt for k in ["熟成","mature","autolysis","麵包","奶油"]):
        tips.append("有熟成發展與二次風味，適合細口杯慢飲。")
    return kw, tips[:2]

def generate_answer(q: str, hits: List[Dict[str, Any]], ctx: Dict[str, Any] | None = None, lang: str = "zh-TW") -> Dict[str, Any]:
    points = _extract_points(hits, limit=5)
    cites = _mk_citations(hits)
    if points:
        conclusion = _short_conclusion(points)
        kw, tips = _keywords(hits)
        bullets = "\n".join([f"• {p}" for p in points[:4]])
        extra = ("\n\n**適飲建議**：\n- " + "\n- ".join(tips)) if tips else ""
        kwline = f"\n\n（關鍵詞：{kw}）" if kw else ""
        text = f"{conclusion}\n\n**重點整理**：\n{bullets}{extra}{kwline}"
        conf = 0.72
    else:
        text = "抱歉，目前沒有可靠依據可回覆這題。若能提供產品、品牌、分類或型號，我可以更精準地回答。"
        conf = 0.35

    return {
        "text": text,
        "cards": [],
        "citations": cites,
        "confidence": conf
    }
