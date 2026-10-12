import uuid

import requests

import historia

NAZWA = "ntfy"
KLUCZ = ["Dieta", "Kcal"]
URL = "https://orion-api.ntfy.pl/api/v2.0/diet-offers?expansions__in=diets,diet_variants,diet_variant_groups"
NAGLOWKI = {
    "Api-Language": "pl",
    "Accept": "application/json",
    "Origin": "https://ntfy.pl",
    "Referer": "https://ntfy.pl/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
}


def pobierz():
    """Cena pełnego pakietu za dzień (z dostawą). Cennik ntfy nie zawiera rabatów."""
    odp = requests.get(URL, headers={**NAGLOWKI, "Trace-Id": str(uuid.uuid4())}, timeout=30)
    if "json" not in odp.headers.get("Content-Type", ""):
        raise RuntimeError(f"API nie zwróciło JSON (status {odp.status_code}): {odp.text[:300]}")
    inc = odp.json()["data"]["includes"]
    diety = {g["id"]: next(d["name"] for d in inc["diets"] if d["id"] == g["diet_id"]) for g in inc["diet_variant_groups"]}
    warianty = sorted(inc["diet_variants"], key=lambda w: (list(diety).index(w["diet_variant_group_id"]), w["position"]))
    ceny = [{"Dieta": diety[w["diet_variant_group_id"]], "Kcal": w["kcal"],
             "Cena standardowa": f"{w['price']:.2f} zł".replace(".", ",")} for w in warianty]
    return ceny, []


if __name__ == "__main__":
    print(historia.aktualizuj(NAZWA, KLUCZ, *pobierz()))
