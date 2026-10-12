"""Zapis cenników i rabatów do CSV z historią obowiązywania (start_date / end_date).

Zasady:
- wartość bez zmian       -> end_date aktualnego rekordu = dziś
- zmiana wartości         -> stary rekord: end_date = wczoraj, nowy rekord: start_date = end_date = dziś
- nowa pozycja            -> nowy rekord: start_date = end_date = dziś
- pozycja zniknęła        -> end_date = wczoraj
"""

import csv
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

FOLDER = Path(__file__).parent / "cenniki"
FOLDER.mkdir(exist_ok=True)
DATY = ["start_date", "end_date"]
PLIK_STANU = FOLDER / "stan.json"  # data ostatniego pobrania każdego cennika


def zapisz(nazwa, klucz, wiersze, dzis=None, zakres=None, pusty_ok=False):
    """Aktualizuje plik cenniki/<nazwa>.csv.

    klucz:    kolumny identyfikujące pozycję (np. Dieta, Kcal); pozostałe kolumny to śledzone wartości
    zakres:   słownik kolumna -> wartość; aktualizowane są tylko rekordy z tego zakresu
              (np. {"Catering": "maczfit"} we wspólnym pliku rabatów), reszta pliku zostaje bez zmian
    pusty_ok: czy pusta lista oznacza "wszystko zniknęło" (rabaty), czy błąd pobierania (cenniki)
    """
    zakres = zakres or {}
    if not wiersze and not pusty_ok:
        raise ValueError("Pobrano pusty cennik - plik nie został zmieniony (zmiana struktury strony?)")

    dzis = dzis or date.today()
    wczoraj, dzis = (dzis - timedelta(days=1)).isoformat(), dzis.isoformat()
    plik = FOLDER / f"{nazwa}.csv"
    id_stanu = "|".join([nazwa, *zakres.values()])

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
        raise ValueError(f"Kolumny {klucz} nie identyfikują pozycji jednoznacznie")
    kolumny = list(dict.fromkeys(kolumny + [k for w in nowe.values() for k in w]))
    wartosci = [k for k in kolumny if k not in klucz]

    # pozycje obecne w ostatnim pobraniu = rekordy z zakresu z end_date równym dacie tego pobrania
    w_zakresie = [r for r in stare if all(r.get(k) == v for k, v in zakres.items())]
    stan = json.loads(PLIK_STANU.read_text(encoding="utf-8")) if PLIK_STANU.exists() else {}
    ostatnie = stan.get(id_stanu) or max((r["end_date"] for r in w_zakresie), default=None)
    otwarte = {tuple(r[k] for k in klucz): r for r in w_zakresie if r["end_date"] == ostatnie}

    def zamknij(rekord):
        if rekord["start_date"] == dzis:  # dodany dziś i już nieaktualny - usuwamy zamiast zamykać
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
            zmiany["zmiana"] += 1
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
    stan[id_stanu] = dzis
    PLIK_STANU.write_text(json.dumps(stan, indent=2, ensure_ascii=False), encoding="utf-8")
    return dict(zmiany)


def aktualizuj(nazwa, klucz, ceny, rabaty, dzis=None):
    """Zapisuje cennik do cenniki/<nazwa>.csv, a jego rabaty do wspólnego cenniki/rabaty.csv."""
    zmiany_cen = zapisz(nazwa, klucz, ceny, dzis)
    zmiany_rabatow = zapisz("rabaty", ["Catering", "Zakres", "Rabat"],
                            [{"Catering": nazwa, **r} for r in rabaty],
                            dzis, zakres={"Catering": nazwa}, pusty_ok=True)
    return {"ceny": zmiany_cen, "rabaty": zmiany_rabatow}
