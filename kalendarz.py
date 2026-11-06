"""Kalendarz handlowy dla Polski + reguły dostaw i okien sprzedaży.

Okno sprzedaży = dni, w których partia dostarczona w dniu D leży na półce
(maks. 2 dni). Reguły (zgodnie z opisem procesu):

    Pn, Wt, Śr -> D, D+1
    Czw        -> tylko D (odbiór w piątek)
    Pt         -> D, D+1 (sobota)  |  tylko D, gdy w niedzielę D+2 jest handel
    Sob        -> D, D+1 (niedziela handlowa); dostawa tylko przed niedzielą handlową

Z okna usuwane są dni, w które sklep jest zamknięty (święta, niedziele
niehandlowe). Dostawa nie odbywa się w dzień zamknięty.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

# dzień tygodnia dostawy -> przesunięcia dni okna (0 = dzień dostawy)
REGULY_OKNA: dict[int, tuple[int, ...]] = {0: (0, 1), 1: (0, 1), 2: (0, 1), 3: (0,), 4: (0, 1), 5: (0, 1)}
# piątek przed niedzielą handlową: towar odbierany w sobotę
REGULA_PIATEK_PRZED_NH: tuple[int, ...] = (0,)


def wielkanoc(rok: int) -> date:
    """Niedziela Wielkanocna (algorytm Meeusa/Jonesa/Butchera)."""
    a, b, c = rok % 19, rok // 100, rok % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    miesiac = (h + l - 7 * m + 114) // 31
    dzien = (h + l - 7 * m + 114) % 31 + 1
    return date(rok, miesiac, dzien)


@lru_cache(maxsize=None)
def swieta_ustawowe(rok: int) -> dict[date, str]:
    """Dni ustawowo wolne od pracy (sklepy zamknięte)."""
    e = wielkanoc(rok)
    s = {
        date(rok, 1, 1): "Nowy Rok",
        date(rok, 1, 6): "Trzech Króli",
        e: "Wielkanoc",
        e + timedelta(days=1): "Poniedziałek Wielkanocny",
        date(rok, 5, 1): "Święto Pracy",
        date(rok, 5, 3): "Święto Konstytucji 3 Maja",
        e + timedelta(days=49): "Zielone Świątki",
        e + timedelta(days=60): "Boże Ciało",
        date(rok, 8, 15): "Wniebowzięcie NMP",
        date(rok, 11, 1): "Wszystkich Świętych",
        date(rok, 11, 11): "Narodowe Święto Niepodległości",
        date(rok, 12, 25): "Boże Narodzenie",
        date(rok, 12, 26): "Drugi dzień Bożego Narodzenia",
    }
    if rok >= 2025:  # Wigilia wolna od pracy od 2025 r.
        s[date(rok, 12, 24)] = "Wigilia"
    return s


def _ostatnia_niedziela(rok: int, miesiac: int) -> date:
    nast = date(rok + (miesiac == 12), miesiac % 12 + 1, 1)
    d = nast - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - 6) % 7)


@lru_cache(maxsize=None)
def niedziele_handlowe(rok: int) -> frozenset[date]:
    """Niedziele handlowe wg ustawy o ograniczeniu handlu (stan od 2025 r.)."""
    e = wielkanoc(rok)
    s = {_ostatnia_niedziela(rok, 1), e - timedelta(days=7),
         _ostatnia_niedziela(rok, 6), _ostatnia_niedziela(rok, 8)}
    kwiecien = _ostatnia_niedziela(rok, 4)
    if kwiecien == e:  # ostatnia niedziela kwietnia = Wielkanoc -> tydzień wcześniej
        kwiecien -= timedelta(days=7)
    s.add(kwiecien)
    wig = date(rok, 12, 24)
    przed = wig - timedelta(days=((wig.weekday() + 1) % 7) or 7)  # niedziela przed Wigilią
    for i in range(3 if rok >= 2025 else 2):
        s.add(przed - timedelta(days=7 * i))
    return frozenset(x for x in s if x not in swieta_ustawowe(rok))


class Kalendarz:
    """Kalendarz z możliwością nadpisania dni (np. z pliku)."""

    def __init__(self, dodatkowe_zamkniete: set[date] | None = None,
                 dodatkowe_niedziele_handlowe: set[date] | None = None):
        self.dod_zamkniete = dodatkowe_zamkniete or set()
        self.dod_nh = dodatkowe_niedziele_handlowe or set()

    def swieto(self, d: date) -> bool:
        return d in swieta_ustawowe(d.year) or d in self.dod_zamkniete

    def niedziela_handlowa(self, d: date) -> bool:
        return d.weekday() == 6 and (d in niedziele_handlowe(d.year) or d in self.dod_nh)

    def otwarty(self, d: date) -> bool:
        if self.swieto(d):
            return False
        return d.weekday() != 6 or self.niedziela_handlowa(d)

    def dzien_dostawy(self, d: date) -> bool:
        if not self.otwarty(d) or d.weekday() == 6:
            return False
        if d.weekday() == 5:
            return self.niedziela_handlowa(d + timedelta(days=1))
        return True

    def okno(self, d: date) -> list[date]:
        wd = d.weekday()
        przes = REGULY_OKNA.get(wd, (0,))
        if wd == 4 and self.niedziela_handlowa(d + timedelta(days=2)):
            przes = REGULA_PIATEK_PRZED_NH
        return [d + timedelta(days=p) for p in przes if self.otwarty(d + timedelta(days=p))]

    def dni_dostaw(self, start: date, koniec: date) -> list[date]:
        n = (koniec - start).days + 1
        return [start + timedelta(days=i) for i in range(n) if self.dzien_dostawy(start + timedelta(days=i))]


def cechy_kalendarza(daty_dostaw: list[date] | pd.DatetimeIndex, kal: Kalendarz) -> pd.DataFrame:
    """Cechy kalendarzowe dla każdej daty dostawy (partii)."""
    daty = sorted({pd.Timestamp(d).date() for d in daty_dostaw})
    if not daty:
        return pd.DataFrame()
    lo, hi = daty[0] - timedelta(days=40), daty[-1] + timedelta(days=40)
    zamkniete_swieta = sorted(d for r in range(lo.year, hi.year + 1)
                              for d in swieta_ustawowe(r) if lo <= d <= hi)
    zs = np.array([np.datetime64(d) for d in zamkniete_swieta])

    okna = {d: kal.okno(d) for d in daty}
    # ile partii leży na półce każdego dnia -> konkurencja między partiami
    na_polce: dict[date, int] = {}
    for d, ok in okna.items():
        for x in ok:
            na_polce[x] = na_polce.get(x, 0) + 1

    wiersze = []
    for d in daty:
        ok = okna[d]
        dn = np.datetime64(d)
        przyszle = zs[zs > dn]
        przeszle = zs[zs < dn]
        do_sw = int((przyszle[0] - dn).astype(int)) if len(przyszle) else 40
        od_sw = int((dn - przeszle[-1]).astype(int)) if len(przeszle) else 40
        # zamknięcia (nie licząc zwykłych niedziel) w ciągu 3 kolejnych dni -> zakupy "na zapas"
        zamk_3 = sum(1 for i in range(1, 4) if kal.swieto(d + timedelta(days=i)))
        # dni robocze "pomiędzy" (mostek) — dzień roboczy otoczony wolnymi
        prev_wolny = not kal.otwarty(d - timedelta(days=1)) or (d - timedelta(days=1)).weekday() >= 5
        next_wolny = not kal.otwarty(d + timedelta(days=1)) or (d + timedelta(days=1)).weekday() >= 5
        mostek = int(prev_wolny and next_wolny and d.weekday() < 5)
        doy = d.timetuple().tm_yday
        wiersze.append({
            "data": pd.Timestamp(d),
            "dzien_tyg": d.weekday(),
            "okno_dni": len(ok),
            "okno_sobota": int(any(x.weekday() == 5 for x in ok)),
            "okno_niedz_handl": int(any(x.weekday() == 6 for x in ok)),
            "okno_wielka_sobota": int(any(x == wielkanoc(x.year) - timedelta(days=1) for x in ok)),
            "skrocone_przez_swieto": int(len(ok) < len(REGULY_OKNA.get(d.weekday(), (0,)))
                                         and any(kal.swieto(d + timedelta(days=p))
                                                 for p in REGULY_OKNA.get(d.weekday(), (0,)))),
            "konkurencja_partii": float(np.mean([na_polce[x] - 1 for x in ok])) if ok else 0.0,
            "dni_do_swieta": min(do_sw, 40),
            "dni_od_swieta": min(od_sw, 40),
            "swieta_w_3_dniach": zamk_3,
            "mostek": mostek,
            "okres_swiateczny": int((d.month == 12 and d.day >= 18) or (d.month == 1 and d.day <= 6)),
            "miesiac": d.month,
            "dzien_miesiaca": d.day,
            "tydz_roku": d.isocalendar().week,
            "doy_sin": np.sin(2 * np.pi * doy / 365.25),
            "doy_cos": np.cos(2 * np.pi * doy / 365.25),
        })
    return pd.DataFrame(wiersze)
