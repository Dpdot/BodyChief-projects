import json
import re

import requests

import historia

NAZWA = "maczfit"
KLUCZ = ["Kategoria", "Dieta", "Kcal"]


def pobierz():
    odp = requests.get("https://maczfit.pl/cennik", headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    odp.raise_for_status()
    dane = json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', odp.text, re.S).group(1))
    cennik = next(b for b in dane["props"]["pageProps"]["page"]["layout"] if b["blockType"] == "pricingTable")
    ceny, rabaty = [], []
    for kat in cennik["categories"]:
        for dieta in kat["diets"]:
            ceny += [{"Kategoria": kat["label"], "Dieta": dieta["name"], "Kcal": c["calories"],
                      "Cena standardowa": f"{c['price']:.2f} zł".replace(".", ",")} for c in dieta["prices"]]
        rabaty += [{"Zakres": kat["label"], "Rabat": p["label"], "Wysokość": f"-{p['discountPercent']}%"}
                   for p in kat["discountTiers"]]
    return ceny, rabaty


if __name__ == "__main__":
    print(historia.aktualizuj(NAZWA, KLUCZ, *pobierz()))
