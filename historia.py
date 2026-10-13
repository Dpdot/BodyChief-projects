"""Zapis cenników i rabatów do bazy SQL Server z historią obowiązywania (start_date / end_date).

Zasady:
- wartość bez zmian       -> end_date aktualnego rekordu = dziś
- zmiana wartości         -> stary rekord: end_date = wczoraj, nowy rekord: start_date = end_date = dziś
- nowa pozycja            -> nowy rekord: start_date = end_date = dziś
- pozycja zniknęła        -> end_date = wczoraj

Tabele zakładają się same przy pierwszym uruchomieniu:
- cennik_<nazwa>  - ceny standardowe danego cateringu
- rabaty          - rabaty wszystkich cateringów
- stan_pobran     - data ostatniego pobrania każdego cennika (potrzebna do poprawnej historii)
Połączenie konfiguruje plik db_config.ini (wzór: db_config.example.ini).
"""

import configparser
import re
import unicodedata
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

KATALOG = Path(__file__).parent
PLIK_KONFIGURACJI = KATALOG / "db_config.ini"
SCHEMAT = "dbo"
ID_DDL = "id INT IDENTITY(1,1) PRIMARY KEY"  # kolumna id w SQL Server


# ------------------------------------------------------------------ połączenie
def polacz():
    """Zwraca połączenie pyodbc na podstawie db_config.ini."""
    global SCHEMAT
    import pyodbc

    if not PLIK_KONFIGURACJI.exists():
        raise FileNotFoundError(f"Brak pliku {PLIK_KONFIGURACJI.name} - skopiuj db_config.example.ini i uzupełnij dane serwera")
    cfg = configparser.ConfigParser(interpolation=None)  # znak % w haśle bez specjalnego znaczenia
    cfg.read(PLIK_KONFIGURACJI, encoding="utf-8")
    db = cfg["sqlserver"]
    SCHEMAT = db.get("schema", "dbo") or "dbo"

    parametry = {
        "DRIVER": "{%s}" % db.get("driver", "ODBC Driver 18 for SQL Server"),
        "SERVER": db["server"],
        "DATABASE": db["database"],
        "TrustServerCertificate": db.get("trust_server_certificate", "yes"),
    }
    if db.get("user"):
        parametry |= {"UID": db["user"], "PWD": db.get("password", "")}
    else:
        parametry["Trusted_Connection"] = "yes"  # logowanie kontem Windows
    return pyodbc.connect(";".join(f"{k}={v}" for k, v in parametry.items()), autocommit=False)


# ------------------------------------------------------------------ pomocnicze
def nazwa_sql(tekst):
    """'Cena standardowa' -> 'cena_standardowa', 'Posiłki' -> 'posilki'."""
    tekst = unicodedata.normalize("NFKD", tekst.replace("ł", "l").replace("Ł", "L")).encode("ascii", "ignore").decode()
    return re.sub(r"[^0-9a-z]+", "_", tekst.lower()).strip("_")


def czy_cena(kolumna):
    return kolumna.startswith("cena")


def normalizuj(kolumna, wartosc):
    """Ceny -> Decimal z 2 miejscami, reszta -> tekst; puste -> None (tak samo dla danych ze strony i z bazy)."""
    if wartosc is None or str(wartosc).strip() == "":
        return None
    if czy_cena(kolumna):
        if not isinstance(wartosc, (int, float, Decimal)):
            wartosc = re.sub(r"[^\d,.\-]", "", str(wartosc)).replace(",", ".")
        return Decimal(str(wartosc)).quantize(Decimal("0.01"))
    return str(wartosc).strip()


def jako_data(wartosc):
    return wartosc if isinstance(wartosc, date) else date.fromisoformat(str(wartosc)[:10])


def tabela(nazwa):
    return f"[{SCHEMAT}].[{nazwa}]"


def przygotuj_tabele(kursor, nazwa, kolumny):
    """Tworzy tabelę, jeśli nie istnieje, i dodaje brakujące kolumny."""
    def typ(k):
        return "DECIMAL(10,2)" if czy_cena(k) else "NVARCHAR(255)"

    try:
        kursor.execute(f"SELECT * FROM {tabela(nazwa)} WHERE 1 = 0")
        istniejace = {d[0].lower() for d in kursor.description}
    except Exception:
        definicje = ", ".join([ID_DDL, *[f"[{k}] {typ(k)} NULL" for k in kolumny],
                               "[start_date] DATE NOT NULL", "[end_date] DATE NOT NULL"])
        kursor.execute(f"CREATE TABLE {tabela(nazwa)} ({definicje})")
        return
    for k in kolumny:
        if k not in istniejace:
            kursor.execute(f"ALTER TABLE {tabela(nazwa)} ADD [{k}] {typ(k)} NULL")


def przygotuj_stan(kursor):
    try:
        kursor.execute(f"SELECT nazwa FROM {tabela('stan_pobran')} WHERE 1 = 0")
    except Exception:
        kursor.execute(f"CREATE TABLE {tabela('stan_pobran')} ([nazwa] NVARCHAR(255) NOT NULL PRIMARY KEY, "
                       "[ostatnie_pobranie] DATE NOT NULL)")


# ------------------------------------------------------------------ zapis z historią
def zapisz(kursor, nazwa, klucz, wiersze, dzis, zakres=None, pusty_ok=False):
    """Aktualizuje tabelę <nazwa> z historią. Zwraca licznik zmian.

    klucz:    kolumny identyfikujące pozycję (np. Dieta, Kcal); pozostałe kolumny to śledzone wartości
    zakres:   słownik kolumna -> wartość; zmieniane są tylko rekordy z tego zakresu
              (np. {"Catering": "maczfit"} we wspólnej tabeli rabatów), reszta tabeli zostaje bez zmian
    pusty_ok: czy pusta lista oznacza "wszystko zniknęło" (rabaty), czy błąd pobierania (cenniki)
    """
    if not wiersze and not pusty_ok:
        raise ValueError("Pobrano pusty cennik - baza nie została zmieniona (zmiana struktury strony?)")
    wczoraj = dzis - timedelta(days=1)
    klucz = [nazwa_sql(k) for k in klucz]
    zakres = {nazwa_sql(k): v for k, v in (zakres or {}).items()}

    nowe = {}
    for w in wiersze:
        w = {**zakres, **{nazwa_sql(k): normalizuj(nazwa_sql(k), v) for k, v in w.items()}}
        nowe[tuple(w.get(k) for k in klucz)] = w
    if len(nowe) != len(wiersze):
        raise ValueError(f"Kolumny {klucz} nie identyfikują pozycji jednoznacznie")
    kolumny = list(dict.fromkeys([*klucz, *zakres, *(k for w in nowe.values() for k in w)]))
    przygotuj_tabele(kursor, nazwa, kolumny)
    przygotuj_stan(kursor)

    # rekordy z zakresu i data ostatniego pobrania
    kursor.execute(f"SELECT * FROM {tabela(nazwa)} WHERE 1 = 1" + "".join(f" AND [{k}] = ?" for k in zakres),
                   list(zakres.values()))
    nazwy = [d[0].lower() for d in kursor.description]
    stare = [dict(zip(nazwy, r)) for r in kursor.fetchall()]
    for r in stare:
        r["start_date"], r["end_date"] = jako_data(r["start_date"]), jako_data(r["end_date"])
        for k in nazwy:
            if k not in ("id", "start_date", "end_date"):
                r[k] = normalizuj(k, r[k])
    wartosci = [k for k in nazwy if k not in (*klucz, "id", "start_date", "end_date")]
    wartosci += [k for k in kolumny if k not in wartosci and k not in klucz]

    id_stanu = "|".join([nazwa, *map(str, zakres.values())])
    kursor.execute(f"SELECT ostatnie_pobranie FROM {tabela('stan_pobran')} WHERE nazwa = ?", [id_stanu])
    wiersz_stanu = kursor.fetchone()
    ostatnie = jako_data(wiersz_stanu[0]) if wiersz_stanu else max((r["end_date"] for r in stare), default=None)
    otwarte = {tuple(r.get(k) for k in klucz): r for r in stare if r["end_date"] == ostatnie}

    przedluz, zamknij, usun, dodaj = [], [], [], []
    zmiany = Counter()

    def zakoncz(rekord):
        (usun if rekord["start_date"] == dzis else zamknij).append(rekord["id"])  # dodany dziś -> usuwamy

    for k, w in nowe.items():
        rekord = otwarte.pop(k, None)
        if rekord and all(rekord.get(c) == w.get(c) for c in wartosci):
            przedluz.append(rekord["id"])
            zmiany["bez zmian"] += 1
            continue
        if rekord:
            zakoncz(rekord)
            zmiany["zmiana"] += 1
        else:
            zmiany["nowe"] += 1
        dodaj.append(w)
    for rekord in otwarte.values():
        zakoncz(rekord)
        zmiany["usunięte"] += 1

    if przedluz:
        kursor.executemany(f"UPDATE {tabela(nazwa)} SET end_date = ? WHERE id = ?", [(dzis, i) for i in przedluz])
    if zamknij:
        kursor.executemany(f"UPDATE {tabela(nazwa)} SET end_date = ? WHERE id = ?", [(wczoraj, i) for i in zamknij])
    if usun:
        kursor.executemany(f"DELETE FROM {tabela(nazwa)} WHERE id = ?", [(i,) for i in usun])
    if dodaj:
        lista = ", ".join(f"[{k}]" for k in kolumny)
        znaki = ", ".join("?" for _ in range(len(kolumny) + 2))
        kursor.executemany(f"INSERT INTO {tabela(nazwa)} ({lista}, [start_date], [end_date]) VALUES ({znaki})",
                           [[w.get(k) for k in kolumny] + [dzis, dzis] for w in dodaj])

    kursor.execute(f"UPDATE {tabela('stan_pobran')} SET ostatnie_pobranie = ? WHERE nazwa = ?", [dzis, id_stanu])
    if kursor.rowcount == 0:
        kursor.execute(f"INSERT INTO {tabela('stan_pobran')} (nazwa, ostatnie_pobranie) VALUES (?, ?)", [id_stanu, dzis])
    return dict(zmiany)


def aktualizuj(nazwa, klucz, ceny, rabaty, dzis=None, polaczenie=None):
    """Zapisuje cennik do tabeli cennik_<nazwa>, a jego rabaty do wspólnej tabeli rabaty - w jednej transakcji."""
    dzis = dzis or date.today()
    wlasne = polaczenie is None
    polaczenie = polaczenie or polacz()
    try:
        kursor = polaczenie.cursor()
        wynik = {
            "ceny": zapisz(kursor, f"cennik_{nazwa}", klucz, ceny, dzis),
            "rabaty": zapisz(kursor, "rabaty", ["Catering", "Zakres", "Rabat"], rabaty, dzis,
                             zakres={"Catering": nazwa}, pusty_ok=True),
        }
        polaczenie.commit()
        return wynik
    except Exception:
        polaczenie.rollback()  # błąd = baza zostaje bez zmian dla tego cateringu
        raise
    finally:
        if wlasne:
            polaczenie.close()
