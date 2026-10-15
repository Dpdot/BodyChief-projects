"""Aktualizuje wszystkie cenniki naraz w bazie SQL Server, zapisuje przebieg do log.txt
i wysyła mail, jeśli u któregoś źródła zmieniły się ceny."""

import importlib
import logging
import sys
from datetime import date

import historia
import powiadomienia

SKRYPTY = ["cennik_vikinga", "cennik_brokul", "cennik_wygodna", "cennik_maczfit", "cennik_ntfy", "cennik_bodychief"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(historia.KATALOG / "log.txt", encoding="utf-8"), logging.StreamHandler()],
)

logging.info("=== Start aktualizacji ===")
dzis = date.today()
try:
    polaczenie = historia.polacz()
except Exception:
    logging.exception("Nie udało się połączyć z bazą - aktualizacja przerwana")
    sys.exit(1)

zmiany_cen = {}  # źródło -> liczba indeksów ze zmianą ceny
try:
    for nazwa in SKRYPTY:
        try:
            modul = importlib.import_module(nazwa)
            wynik = historia.aktualizuj(modul.NAZWA, modul.KLUCZ, *modul.pobierz(), dzis=dzis, polaczenie=polaczenie)
            if wynik["ceny"].get("zmiana"):
                zmiany_cen[modul.NAZWA] = wynik["ceny"]["zmiana"]
            opis = " | ".join(f"{t}: " + (", ".join(f"{k} {v}" for k, v in z.items()) or "brak") for t, z in wynik.items())
            logging.info("%-17s OK   %s", nazwa, opis)
        except Exception:
            logging.exception("%-17s BŁĄD", nazwa)  # błąd jednego cennika nie zatrzymuje pozostałych
finally:
    polaczenie.close()

try:
    logging.info("Powiadomienie: %s", powiadomienia.wyslij_powiadomienie(zmiany_cen, dzis))
except Exception:
    logging.exception("Nie udało się wysłać maila z powiadomieniem")  # dane w bazie są już zapisane
logging.info("=== Koniec aktualizacji ===")
