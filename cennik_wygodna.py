from decimal import Decimal

import requests
from bs4 import BeautifulSoup

import historia

NAZWA = "wygodna"
KLUCZ = ["Dieta", "Kaloryczność"]


def kwota(tekst):
    return Decimal(tekst.replace("zł", "").replace(" ", "").replace(",", "."))


def zl(wartosc):
    return f"{wartosc:.2f} zł".replace(".", ",")


def pobierz():
    odp = requests.get("https://www.wygodnadieta.pl/cennik", headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    odp.raise_for_status()
    ceny, roznice = [], {}  # roznice: nazwa rabatu -> zbiór obniżek w zł
    for tabela in BeautifulSoup(odp.text, "html.parser").find_all("table"):
        dieta = tabela.find_parent(class_="product").select_one(".name").get_text(strip=True)
        naglowek = [th.get_text(strip=True) for th in tabela.find_all("th")]
        for tr in tabela.tbody.find_all("tr"):
            kcal, standard, *z_rabatem = [td.get_text(strip=True) for td in tr.find_all("td")]
            ceny.append({"Dieta": dieta, "Kaloryczność": kcal, "Cena standardowa": standard})
            for nazwa, cena in zip(naglowek[2:], z_rabatem):
                roznice.setdefault(nazwa.replace("Cena za dzień", "").strip(), set()).add(kwota(standard) - kwota(cena))
    rabaty = []
    for nazwa, r in roznice.items():
        wysokosc = f"-{zl(min(r))}/dzień" if len(r) == 1 else f"od -{zl(min(r))} do -{zl(max(r))}/dzień"
        rabaty.append({"Zakres": "", "Rabat": nazwa, "Wysokość": wysokosc})
    return ceny, rabaty


if __name__ == "__main__":
    print(historia.aktualizuj(NAZWA, KLUCZ, *pobierz()))
