import requests
from bs4 import BeautifulSoup

import historia

NAZWA = "brokul"
KLUCZ = ["Kategoria", "Dieta", "Okres"]


def pobierz():
    """Brokuł nie podaje rabatów - każdy okres (dzień próbny, 5 dni, 20 dni...) to osobny pakiet z własną ceną."""
    odp = requests.get("https://dietyodbrokula.pl/cennik", headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    odp.raise_for_status()
    soup = BeautifulSoup(odp.text, "html.parser")
    kategorie = [t.get_text(strip=True) for t in soup.select(".pricing-tabs__title")]
    ceny = []
    for kategoria, tabela in zip(kategorie, soup.select("table.pricing-table")):
        tr = [[c.get_text(" ", strip=True) for c in r.find_all(["th", "td"])] for r in tabela.find_all("tr")]
        okresy = tr[0][1:]
        for dieta, *wartosci in tr[1:]:
            ceny += [{"Kategoria": kategoria, "Dieta": dieta, "Okres": o, "Cena standardowa": c} for o, c in zip(okresy, wartosci)]
    return ceny, []


if __name__ == "__main__":
    print(historia.aktualizuj(NAZWA, KLUCZ, *pobierz()))
