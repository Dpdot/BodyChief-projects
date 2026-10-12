import requests
from bs4 import BeautifulSoup

import historia

NAZWA = "vikinga"
KLUCZ = ["Dieta", "Posiłki", "Kcal"]


def pobierz():
    odp = requests.get("https://kuchniavikinga.pl/cennik/", headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    odp.raise_for_status()
    wiersze = []
    for cennik in BeautifulSoup(odp.text, "html.parser").select(".price-list-slider"):
        dieta = cennik.find_parent(id=True).find("h2").get_text(strip=True)
        posilki = cennik.select_one(".price-list-slider__kcal small").get_text(strip=True)
        kolumny = cennik.select(".price-list-slider__kcal, .price-list-slider__col")
        tabela = list(zip(*[[c.get_text(" ", strip=True) for c in k.select(".price-list-slider__cell")] for k in kolumny]))
        naglowek = ["Kcal", *tabela[0][1:]]
        wiersze += [{"Dieta": dieta, "Posiłki": posilki, **dict(zip(naglowek, w))} for w in tabela[1:]]
    return wiersze


if __name__ == "__main__":
    print(historia.zapisz(NAZWA, KLUCZ, pobierz()))
