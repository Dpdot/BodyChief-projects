"""Aktualizuje wszystkie cenniki naraz w bazie SQL Server i zapisuje przebieg do log.txt."""

import importlib
import logging
import sys

import historia

SKRYPTY = ["cennik_vikinga", "cennik_brokul", "cennik_wygodna", "cennik_maczfit", "cennik_ntfy", "cennik_bodychief"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(historia.KATALOG / "log.txt", encoding="utf-8"), logging.StreamHandler()],
)

logging.info("=== Start aktualizacji ===")
try:
    polaczenie = historia.polacz()
except Exception:
    logging.exception("Nie udało się połączyć z bazą - aktualizacja przerwana")
    sys.exit(1)

try:
    for nazwa in SKRYPTY:
        try:
            modul = importlib.import_module(nazwa)
            zmiany = historia.aktualizuj(modul.NAZWA, modul.KLUCZ, *modul.pobierz(), polaczenie=polaczenie)
            opis = " | ".join(f"{t}: " + (", ".join(f"{k} {v}" for k, v in z.items()) or "brak") for t, z in zmiany.items())
            logging.info("%-17s OK   %s", nazwa, opis)
        except Exception:
            logging.exception("%-17s BŁĄD", nazwa)  # błąd jednego cennika nie zatrzymuje pozostałych
finally:
    polaczenie.close()
logging.info("=== Koniec aktualizacji ===")
