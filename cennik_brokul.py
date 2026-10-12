import requests
from bs4 import BeautifulSoup

import historia

NAZWA = "brokul"
KLUCZ = ["Kategoria", "Dieta"]


def pobierz():
    odp = requests.get("https://dietyodbrokula.pl/cennik", headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    odp.raise_for_status()
    soup = BeautifulSoup(odp.text, "html.parser")
    kategorie = [t.get_text(strip=True) for t in soup.select(".pricing-tabs__title")]
    wiersze = []
    for kategoria, tabela in zip(kategorie, soup.select("table.pricing-table")):
        tr = [[c.get_text(" ", strip=True) for c in r.find_all(["th", "td"])] for r in tabela.find_all("tr")]
        naglowek = ["Dieta", *tr[0][1:]]
        wiersze += [{"Kategoria": kategoria, **dict(zip(naglowek, w))} for w in tr[1:]]
    return wiersze


if __name__ == "__main__":
    print(historia.zapisz(NAZWA, KLUCZ, pobierz()))
