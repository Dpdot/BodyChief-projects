import csv
import uuid
from pathlib import Path

import requests

folder = Path(__file__).parent / "cenniki"
folder.mkdir(exist_ok=True)

url = ("https://orion-api.ntfy.pl/api/v2.0/diet-offers?expansions__in=diets,diet_variants,"
       "diet_variant_groups,diet_variant_meals,diet_variant_meal.diet_variant_meal_types")
dane = requests.get(url, headers={"Api-Language": "pl", "Trace-Id": str(uuid.uuid4())}).json()["data"]
inc = dane["includes"]

diety = {g["id"]: next(d["name"] for d in inc["diets"] if d["id"] == g["diet_id"]) for g in inc["diet_variant_groups"]}
posilki = {m["id"]: m["diet_variant_meal_type_id"] for m in inc["diet_variant_meals"]}
typy = {t["id"]: t["meal_name"]["value"] for t in inc["diet_variant_meal_types"]}
kolumny = list(dict.fromkeys(t["meal_name"]["value"] for t in sorted(inc["diet_variant_meal_types"], key=lambda t: t["meal_name"]["position"])))

ceny = {}  # wariant -> {posiłek: cena}
for r in dane["results"]:
    ceny.setdefault(r["diet_variant_id"], {})[typy[posilki[r["diet_variant_meal_id"]]]] = r["price"]


def zl(kwota):
    return f"{kwota:.2f} zł".replace(".", ",") if kwota is not None else ""


wiersze = [["Dieta", "Kcal", "Cena za dzień (z dostawą)", *kolumny]]
for w in sorted(inc["diet_variants"], key=lambda w: (list(diety).index(w["diet_variant_group_id"]), w["position"])):
    wiersze.append([diety[w["diet_variant_group_id"]], w["kcal"], zl(w["price"]), *[zl(ceny.get(w["id"], {}).get(k)) for k in kolumny]])

with open(folder / "ntfy.csv", "w", newline="", encoding="utf-8-sig") as f:
    csv.writer(f, delimiter=";").writerows(wiersze)
