"""Kalendarz handlowy dla Polski + reguły dostaw i okien sprzedaży.

Okno sprzedaży = dni, w których partia dostarczona w dniu D leży na półce
(maks. 2 dni: D i D+1). Partia musi zniknąć przed pierwszym otwartym dniem
po D+1, więc odbiera ją ostatnia dostawa przed tym dniem (lub w tym dniu). Daje to:

    Pn, Wt, Śr -> D, D+1
    Czw        -> D (odbiór w pt) | D, D+1 przed niedzielą handlową (odbiór w sob)
    Pt         -> D, D+1 (sobota) | tylko D przed niedzielą handlową (odbiór w sob)
    Sob        -> D, D+1 (niedziela handlowa)

Dostawy: pn–pt + sobota przed niedzielą handlową + dostawa uzupełniająca w każdy
otwarty dzień (poza niedzielą), w którym inaczej nie byłoby towaru na półce
(np. sobota po świątecznym piątku). Z okna usuwane są dni, w które sklep jest
zamknięty. Dostawa nie odbywa się w dzień zamknięty.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

MAKS_DNI_NA_POLCE = 2
# nie planuj dostawy na dzień przed dniem wolnym, jeśli półkę zapełni towar z dnia poprzedniego
POMIJAJ_DOSTAWE_PRZED_WOLNYM = True


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
                 dodatkowe_niedziele_handlowe: set[date] | None = None,
                 historia_dostaw: set[date] | None = None):
        self.dod_zamkniete = dodatkowe_zamkniete or set()
        self.dod_nh = dodatkowe_niedziele_handlowe or set()
        # faktyczne dni dostaw z historii: do końca historii okna liczone są wg nich,
        # a nie wg reguł (reguły mogły się zmienić, np. pomijanie dostaw przed dniem wolnym)
        self.hist_dostaw = historia_dostaw or set()
        self.koniec_historii = max(self.hist_dostaw) if self.hist_dostaw else None

    def swieto(self, d: date) -> bool:
        return d in swieta_ustawowe(d.year) or d in self.dod_zamkniete

    def niedziela_handlowa(self, d: date) -> bool:
        return d.weekday() == 6 and (d in niedziele_handlowe(d.year) or d in self.dod_nh)

    def otwarty(self, d: date) -> bool:
        if self.swieto(d):
            return False
        return d.weekday() != 6 or self.niedziela_handlowa(d)

    def dostawa_bazowa(self, d: date) -> bool:
        """Pn–pt oraz sobota przed niedzielą handlową (tylko dni otwarte)."""
        if not self.otwarty(d) or d.weekday() == 6:
            return False
        if d.weekday() == 5:
            return self.niedziela_handlowa(d + timedelta(days=1))
        return True

    def pomin_przed_wolnym(self, d: date) -> bool:
        """Dzień przed dniem wolnym, gdy półkę zapełnia partia z dnia poprzedniego (leży 2 dni)."""
        return (POMIJAJ_DOSTAWE_PRZED_WOLNYM and not self.otwarty(d + timedelta(days=1))
                and self.dzien_dostawy(d - timedelta(days=1)))

    def dzien_dostawy(self, d: date) -> bool:
        if self.koniec_historii is not None and d <= self.koniec_historii:
            return d in self.hist_dostaw
        if self.dostawa_bazowa(d):
            return not self.pomin_przed_wolnym(d)
        if not self.otwarty(d) or d.weekday() == 6:
            return False
        # dostawa uzupełniająca: wczoraj nie było dostawy -> dziś półka byłaby pusta
        return not self.dzien_dostawy(d - timedelta(days=1))

    def okno_nominalne(self, d: date) -> list[date]:
        """Dni od dostawy do dnia przed odbiorem (łącznie z dniami zamkniętymi)."""
        waznosc = d + timedelta(days=MAKS_DNI_NA_POLCE - 1)  # ostatni dzień sprzedaży
        # pierwszy otwarty dzień po terminie — wtedy towaru już nie może być na półce
        termin = waznosc + timedelta(days=1)
        while not self.otwarty(termin) and (termin - d).days < 14:
            termin += timedelta(days=1)
        # odbiór = ostatnia dostawa w (D, termin]
        odbior = termin
        while odbior > d and not self.dzien_dostawy(odbior):
            odbior -= timedelta(days=1)
        if odbior == d:
            odbior = termin
        koniec = min(waznosc, odbior - timedelta(days=1))
        return [d + timedelta(days=i) for i in range((koniec - d).days + 1)]

    def okno(self, d: date) -> list[date]:
        return [x for x in self.okno_nominalne(d) if self.otwarty(x)]

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
            "skrocone_przez_swieto": int(any(kal.swieto(x) for x in kal.okno_nominalne(d))),
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
