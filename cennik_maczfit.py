import json
import re
from decimal import ROUND_HALF_UP, Decimal

import requests

import historia

NAZWA = "maczfit"
KLUCZ = ["Kategoria", "Dieta", "Kcal"]


def zl(kwota):
    return f"{kwota.quantize(Decimal('0.01'), ROUND_HALF_UP)} zł".replace(".", ",")


def pobierz():
    odp = requests.get("https://maczfit.pl/cennik", headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    odp.raise_for_status()
    dane = json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', odp.text, re.S).group(1))
    cennik = next(b for b in dane["props"]["pageProps"]["page"]["layout"] if b["blockType"] == "pricingTable")
    wiersze = []
    for kat in cennik["categories"]:
        for dieta in kat["diets"]:
            for c in dieta["prices"]:
                cena = Decimal(str(c["price"]))
                wiersz = {"Kategoria": kat["label"], "Dieta": dieta["name"], "Kcal": c["calories"],
                          kat["standardTier"]["label"].strip(): zl(cena)}
                wiersz |= {p["label"]: zl(cena * (100 - p["discountPercent"]) / 100) for p in kat["discountTiers"]}
                wiersze.append(wiersz)
    return wiersze


if __name__ == "__main__":
    print(historia.zapisz(NAZWA, KLUCZ, pobierz()))
