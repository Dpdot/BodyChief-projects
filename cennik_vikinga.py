import re

import requests
from bs4 import BeautifulSoup

import historia

NAZWA = "vikinga"
KLUCZ = ["Dieta", "Posiłki", "Kcal"]


def pobierz():
    odp = requests.get("https://kuchniavikinga.pl/cennik/", headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    odp.raise_for_status()
    ceny, rabaty = [], {}
    for cennik in BeautifulSoup(odp.text, "html.parser").select(".price-list-slider"):
        dieta = cennik.find_parent(id=True).find("h2").get_text(strip=True)
        posilki = cennik.select_one(".price-list-slider__kcal small").get_text(strip=True)
        kolumny = cennik.select(".price-list-slider__kcal, .price-list-slider__col")
        tabela = list(zip(*[[c.get_text(" ", strip=True) for c in k.select(".price-list-slider__cell")] for k in kolumny]))
        # kolumna 1 = cena standardowa, kolejne = ceny z rabatem za długość zamówienia
        ceny += [{"Dieta": dieta, "Posiłki": posilki, "Kcal": w[0], "Cena standardowa": w[1]} for w in tabela[1:]]
        for naglowek in tabela[0][2:]:
            m = re.search(r"(?:Największa oszczędność\s*)?(.*?)\s*Cena ze zniżką\s*(-?\s*\d+\s*%)", naglowek)
            rabat, wysokosc = (m.group(1), m.group(2).replace(" ", "")) if m else (naglowek, "")
            rabaty[rabat] = {"Zakres": "", "Rabat": rabat, "Wysokość": wysokosc}
    return ceny, list(rabaty.values())


if __name__ == "__main__":
    print(historia.aktualizuj(NAZWA, KLUCZ, *pobierz()))
