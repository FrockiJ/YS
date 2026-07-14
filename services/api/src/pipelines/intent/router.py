def route_domain(q: str) -> str:
    t = (q or "").lower()
    burg = ["burgundy","bourgogne","勃艮第","布根地","布艮地","布爾岡"]
    cham = ["champagne","香檳","香槟","起泡酒","氣泡酒","bubbles"]
    if any(k in t for k in burg): return "burgundy"
    if any(k in t for k in cham): return "champagne"
    return "auto"

def bias_queries_for_domain(queries: list[str], domain: str) -> list[str]:
    if domain == "burgundy":
        return [f"{q} Burgundy" if "burgundy" not in q.lower() else q for q in queries]
    if domain == "champagne":
        return [f"{q} Champagne" if "champagne" not in q.lower() else q for q in queries]
    return queries