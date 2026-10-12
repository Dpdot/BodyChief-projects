import uuid

import requests

import historia

NAZWA = "ntfy"
KLUCZ = ["Dieta", "Kcal"]
URL = ("https://orion-api.ntfy.pl/api/v2.0/diet-offers?expansions__in=diets,diet_variants,"
       "diet_variant_groups,diet_variant_meals,diet_variant_meal.diet_variant_meal_types")
NAGLOWKI = {
    "Api-Language": "pl",
    "Accept": "application/json",
    "Origin": "https://ntfy.pl",
    "Referer": "https://ntfy.pl/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
}


def zl(kwota):
    return f"{kwota:.2f} zł".replace(".", ",")


def pobierz():
    odp = requests.get(URL, headers={**NAGLOWKI, "Trace-Id": str(uuid.uuid4())}, timeout=30)
    if "json" not in odp.headers.get("Content-Type", ""):
        raise RuntimeError(f"API nie zwróciło JSON (status {odp.status_code}): {odp.text[:300]}")
    dane = odp.json()["data"]
    inc = dane["includes"]

    diety = {g["id"]: next(d["name"] for d in inc["diets"] if d["id"] == g["diet_id"]) for g in inc["diet_variant_groups"]}
    posilki = {m["id"]: m["diet_variant_meal_type_id"] for m in inc["diet_variant_meals"]}
    typy = {t["id"]: t["meal_name"]["value"] for t in inc["diet_variant_meal_types"]}

    ceny = {}  # wariant -> {posiłek: cena}
    for r in dane["results"]:
        ceny.setdefault(r["diet_variant_id"], {})[typy[posilki[r["diet_variant_meal_id"]]]] = zl(r["price"])

    warianty = sorted(inc["diet_variants"], key=lambda w: (list(diety).index(w["diet_variant_group_id"]), w["position"]))
    return [{"Dieta": diety[w["diet_variant_group_id"]], "Kcal": w["kcal"],
             "Cena za dzień (z dostawą)": zl(w["price"]), **ceny.get(w["id"], {})} for w in warianty]


if __name__ == "__main__":
    print(historia.zapisz(NAZWA, KLUCZ, pobierz()))
