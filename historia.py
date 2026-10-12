"""Zapis cennika do CSV z historią cen (start_date / end_date).

Zasady:
- cena bez zmian            -> end_date aktualnego rekordu = dziś
- zmiana ceny               -> stary rekord: end_date = wczoraj, nowy rekord: start_date = end_date = dziś
- nowy wariant              -> nowy rekord: start_date = end_date = dziś
- wariant zniknął z cennika -> end_date = wczoraj
"""

import csv
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

FOLDER = Path(__file__).parent / "cenniki"
FOLDER.mkdir(exist_ok=True)
DATY = ["start_date", "end_date"]


def zapisz(nazwa, klucz, wiersze, dzis=None):
    """nazwa: nazwa pliku CSV, klucz: kolumny identyfikujące wariant, wiersze: lista słowników z cennika."""
    if not wiersze:
        raise ValueError("Pobrano pusty cennik - plik nie został zmieniony (zmiana struktury strony?)")

    dzis = dzis or date.today()
    wczoraj, dzis = (dzis - timedelta(days=1)).isoformat(), dzis.isoformat()
    plik = FOLDER / f"{nazwa}.csv"

    stare, kolumny = [], list(klucz)
    if plik.exists():
        with open(plik, newline="", encoding="utf-8-sig") as f:
            czytnik = csv.DictReader(f, delimiter=";")
            if not set(DATY) <= set(czytnik.fieldnames or []):
                raise ValueError(f"{plik.name} nie ma kolumn start_date/end_date (stary format) - usuń go lub zmień nazwę")
            stare = list(czytnik)
            kolumny += [k for k in czytnik.fieldnames if k not in kolumny and k not in DATY]

    nowe = {tuple(str(w[k]) for k in klucz): {k: str(v) for k, v in w.items()} for w in wiersze}
    if len(nowe) != len(wiersze):
        raise ValueError(f"Kolumny {klucz} nie identyfikują wariantów jednoznacznie")
    kolumny = list(dict.fromkeys(kolumny + [k for w in nowe.values() for k in w]))
    wartosci = [k for k in kolumny if k not in klucz]

    # rekordy obecne w ostatnim pobraniu = te z najpóźniejszym end_date
    ostatnie_pobranie = max((r["end_date"] for r in stare), default=None)
    otwarte = {tuple(r[k] for k in klucz): r for r in stare if r["end_date"] == ostatnie_pobranie}

    def zamknij(rekord):
        if rekord["start_date"] == dzis:  # rekord dodany dziś i już nieaktualny - usuwamy zamiast zamykać
            stare.remove(rekord)
        else:
            rekord["end_date"] = wczoraj

    zmiany = Counter()
    for k, w in nowe.items():
        rekord = otwarte.pop(k, None)
        if rekord and all(rekord.get(c, "") == w.get(c, "") for c in wartosci):
            rekord["end_date"] = dzis
            zmiany["bez zmian"] += 1
            continue
        if rekord:
            zamknij(rekord)
            zmiany["zmiana ceny"] += 1
        else:
            zmiany["nowe"] += 1
        stare.append({**w, "start_date": dzis, "end_date": dzis})

    for rekord in otwarte.values():
        zamknij(rekord)
        zmiany["usunięte"] += 1

    with open(plik, "w", newline="", encoding="utf-8-sig") as f:
        pisarz = csv.DictWriter(f, fieldnames=kolumny + DATY, delimiter=";", restval="")
        pisarz.writeheader()
        pisarz.writerows(stare)
    return dict(zmiany)
