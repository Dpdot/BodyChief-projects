from decimal import Decimal

import requests
from bs4 import BeautifulSoup

import historia

NAZWA = "bodychief"
KLUCZ = ["Dieta", "Kcal", "Okres"]
URL_STRONY = "https://bodychief.pl/cennik/dieta"
URL_API = "https://webapi.bodychief.pl/bodychief_api/getPricelist"
CITY_ID = 1  # miasto, dla którego kalkulator na stronie pokazuje ceny domyślnie
# klucze cennika w API: "0" = dieta testowa, "1" = cena za dzień przy dowolnej liczbie dni,
# pozostałe ("10", "15", "20") = cena za dzień przy zamówieniu od tylu dni
OKRESY = {"0": "Testowa", "1": "Dowolna liczba dni"}


def zl(tekst):
    return f"{Decimal(tekst):.2f} zł".replace(".", ",")


def pobierz():
    sesja = requests.Session()
    sesja.headers.update({"User-Agent": "Mozilla/5.0", "Origin": "https://bodychief.pl", "Referer": URL_STRONY})
    strona = sesja.get(URL_STRONY, timeout=30)
    strona.raise_for_status()
    diety = [(o["value"], o.get_text(strip=True)) for o in BeautifulSoup(strona.text, "html.parser").find("select").find_all("option")]

    ceny, obnizki = [], {}  # obnizki: próg dni -> zbiór obniżek w %
    for id_diety, nazwa in diety:
        odp = sesja.post(URL_API, json={"lang": "pl", "data": {"city_id": CITY_ID, "dietcat": id_diety}}, timeout=30)
        odp.raise_for_status()
        dane = odp.json()
        if dane.get("type") != "success":
            raise RuntimeError(f"API zwróciło błąd dla diety {nazwa}: {dane.get('msg')}")
        cennik = dane["value"]["pricelist"]
        for wariant in dane["value"]["diets"]:
            p = cennik.get(wariant["id_diet"])
            if not p:
                continue
            if isinstance(p, list):  # API czasem zwraca ["47.00", "68.00"] zamiast {"0": ..., "1": ...}
                p = {str(i): c for i, c in enumerate(p)}
            kcal = wariant["kcal"].replace("kcal", "").strip()
            ceny += [{"Dieta": nazwa, "Kcal": kcal, "Okres": okres, "Cena standardowa": zl(p[k])}
                     for k, okres in OKRESY.items() if k in p]
            standard = Decimal(p["1"])
            for prog, cena in p.items():
                if prog not in OKRESY and Decimal(cena) < standard:
                    obnizki.setdefault(int(prog), set()).add(round((1 - Decimal(cena) / standard) * 100))

    rabaty = [{"Zakres": "", "Rabat": f"Zamówienie od {prog} dni",
               "Wysokość": f"-{min(r)}%" if len(r) == 1 else f"od -{min(r)}% do -{max(r)}%"}
              for prog, r in sorted(obnizki.items())]
    return ceny, rabaty


if __name__ == "__main__":
    print(historia.aktualizuj(NAZWA, KLUCZ, *pobierz()))
