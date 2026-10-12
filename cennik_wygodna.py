import requests
from bs4 import BeautifulSoup

import historia

NAZWA = "wygodna"
KLUCZ = ["Dieta", "Kaloryczność"]


def pobierz():
    odp = requests.get("https://www.wygodnadieta.pl/cennik", headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    odp.raise_for_status()
    wiersze = []
    for tabela in BeautifulSoup(odp.text, "html.parser").find_all("table"):
        dieta = tabela.find_parent(class_="product").select_one(".name").get_text(strip=True)
        naglowek = [th.get_text(strip=True) for th in tabela.find_all("th")]
        for tr in tabela.tbody.find_all("tr"):
            wiersze.append({"Dieta": dieta, **dict(zip(naglowek, (td.get_text(strip=True) for td in tr.find_all("td"))))})
    return wiersze


if __name__ == "__main__":
    print(historia.zapisz(NAZWA, KLUCZ, pobierz()))
