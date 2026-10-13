"""Aktualizuje wszystkie cenniki naraz i zapisuje przebieg do cenniki/log.txt."""

import importlib
import logging

import historia

SKRYPTY = ["cennik_vikinga", "cennik_brokul", "cennik_wygodna", "cennik_maczfit", "cennik_ntfy", "cennik_bodychief"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(historia.FOLDER / "log.txt", encoding="utf-8"), logging.StreamHandler()],
)

logging.info("=== Start aktualizacji ===")
for nazwa in SKRYPTY:
    try:
        modul = importlib.import_module(nazwa)
        zmiany = historia.aktualizuj(modul.NAZWA, modul.KLUCZ, *modul.pobierz())
        opis = " | ".join(f"{plik}: " + (", ".join(f"{k} {v}" for k, v in z.items()) or "brak") for plik, z in zmiany.items())
        logging.info("%-15s OK   %s", nazwa, opis)
    except Exception:
        logging.exception("%-15s BŁĄD", nazwa)  # błąd jednego cennika nie zatrzymuje pozostałych
logging.info("=== Koniec aktualizacji ===")
