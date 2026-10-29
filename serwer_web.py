"""
serwer_web.py
--------------
Serwer Flask dla webowej wersji przegladarki cen BodyChief. Caly ciezar
logiki (filtrowanie, sortowanie, przeliczanie cen, eksport do Excela)
pozostaje w niezmienionych modulach logika_widoku.py / drob_scraper.py /
kurs_eur_pln.py / kategorie.py / przelicznik.py - ten plik jest tylko
cienka warstwa API (JSON) ponad nimi, zasilajaca front w static/app.js.

Serwer wiaze sie wylacznie z 127.0.0.1 (brak dostepu z sieci) - zgodnie z
pierwotnym, lokalnym/offline charakterem aplikacji desktopowej, ktora ta
wersja zastapila.

PRZYCISK "ODŚWIEŻ DANE" (/api/owoce/odswiez_csv + /api/restart):
Po kliknieciu front najpierw woła stary endpoint odswiez_csv (ponowne
wczytanie CSV do pamieci bez restartu procesu - zachowanie bez zmian), a
nastepnie POST /api/restart, ktory faktycznie ubija caly proces serwera.
Na serwerze Linux proces jest zarzadzany przez systemd z "Restart=on-failure"
w pliku jednostki (patrz scraper-web.service) - systemd sam odpala nowy,
czysty proces natychmiast po tym, jak ten sie zakonczy. Dzieki temu NIE
potrzeba tu zadnej logiki re-exec (jak os.execv na Windows) ani wlasnego
retry-loopa przy bindowaniu portu - systemd gwarantuje, ze cos na porcie
PORT znow odpowie w ciagu sekundy/dwoch.
"""

from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys
import tempfile
import threading
import time

from flask import Flask, jsonify, request, send_file, send_from_directory

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import drob_scraper
import kurs_eur_pln
from logika_widoku import (
    eksportuj_do_excela,
    grupuj_produkty_wg_kategorii,
    wczytaj_rekordy,
    wczytaj_zapisane_widoki,
    zapisz_zapisane_widoki,
    zbuduj_widok,
)

KATALOG_SKRYPTU = pathlib.Path(__file__).resolve().parent
KATALOG_DANYCH = KATALOG_SKRYPTU / "dane"
PLIK_WIDOKOW = KATALOG_DANYCH / "zapisane_widoki.json"
PLIK_OSTATNIEGO_WIDOKU = KATALOG_DANYCH / "ostatni_widok.json"
PLIK_PRODUKTOW_DOMYSLNYCH = KATALOG_DANYCH / "produkty_domyslne.json"
PLIKI_CEN_OWOCE_WARZYWA = ("ceny_bronisze.csv", "ceny_poznan.csv")

PORT = 5321

app = Flask(__name__, static_folder="static", template_folder="templates")

# ------------------------------------------------------------------
# STAN W PAMIECI (odpowiednik atrybutow self.* z dawnej klasy Tkinter)
# ------------------------------------------------------------------
rekordy_owoce: list[dict] = []
rekordy_drobiu: list[dict] = []
kurs_eur_pln_cache: dict | None = None
status_drobiu: dict = {"stan": "oczekiwanie", "tekst": ""}

# Uchwyt do uruchomionego serwera HTTP (ustawiany w main()). Przy restarcie
# na Linuksie poprzez os._exit() nie jest juz potrzebny do niczego - zostaje
# jako defensywny punkt rozszerzenia (np. gdyby serwer dzialal kiedys bez
# systemd i trzeba bylo wrocic do wariantu z make_server()+os.execv jak na
# Windows).
_serwer_http = None


def _wszystkie_gieldy() -> list[str]:
    return sorted({r["gielda"] for r in rekordy_owoce})


def _wszystkie_daty() -> list[str]:
    return sorted({r["data"] for r in rekordy_owoce})


def _tekst_ostatniej_aktualizacji() -> str:
    najnowsze = []
    for nazwa in PLIKI_CEN_OWOCE_WARZYWA:
        plik = KATALOG_DANYCH / nazwa
        if plik.exists():
            najnowsze.append(dt.datetime.fromtimestamp(plik.stat().st_mtime))
    if not najnowsze:
        return "Brak danych."
    return "Ostatnia aktualizacja plików: " + max(najnowsze).strftime("%Y-%m-%d %H:%M")


def _wczytaj_produkty_domyslne() -> list[str]:
    if not PLIK_PRODUKTOW_DOMYSLNYCH.exists():
        return []
    import json

    try:
        with PLIK_PRODUKTOW_DOMYSLNYCH.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _zapisz_produkty_domyslne(produkty: list[str]) -> None:
    import json

    PLIK_PRODUKTOW_DOMYSLNYCH.parent.mkdir(parents=True, exist_ok=True)
    with PLIK_PRODUKTOW_DOMYSLNYCH.open("w", encoding="utf-8") as f:
        json.dump(produkty, f, ensure_ascii=False, indent=2)


def _odswiez_drob_w_tle() -> None:
    global rekordy_drobiu, status_drobiu
    status_drobiu = {"stan": "odswiezanie", "tekst": "Odświeżanie cen drobiu..."}
    try:
        drob_scraper.odswiez_dane()
        rekordy_drobiu = drob_scraper.wczytaj_rekordy()
        status_drobiu = {"stan": "gotowe", "tekst": ""}
    except Exception as blad:  # pragma: no cover - zalezne od sieci
        status_drobiu = {"stan": "blad", "tekst": f"Nie udało się odświeżyć cen drobiu: {blad}"}


def _pobierz_kurs() -> dict | None:
    global kurs_eur_pln_cache
    if kurs_eur_pln_cache is None:
        try:
            kurs_eur_pln_cache = kurs_eur_pln.pobierz_kurs_eur_pln()
        except Exception:
            kurs_eur_pln_cache = None
    return kurs_eur_pln_cache


def _wykonaj_restart() -> None:
    """Wywolywane w osobnym watku daemon przez POST /api/restart. Czeka
    chwile, zeby odpowiedz HTTP dla tego zadania zdolala sie wyslac do
    klienta, a potem po prostu konczy caly proces.

    Na serwerze Linux proces jest pod nadzorem systemd (patrz
    scraper-web.service, Restart=on-failure) - systemd automatycznie
    odpali nowy, czysty proces w ciagu sekundy/dwoch. Celowo os._exit(1)
    a nie sys.exit()/raise - os._exit() pomija wszelkie finally/atexit,
    ktore mogly by sie zawiesic, i gwarantuje natychmiastowe zakonczenie
    procesu niezaleznie od tego, co jeszcze robi Flask/Werkzeug w innych
    watkach."""
    time.sleep(0.3)
    os._exit(1)


@app.route("/api/restart", methods=["POST"])
def api_restart():
    threading.Thread(target=_wykonaj_restart, daemon=True).start()
    return jsonify({"restartuje": True})


# ------------------------------------------------------------------
# STRONA GLOWNA / STATYKA
# ------------------------------------------------------------------
@app.route("/")
def strona_glowna():
    from flask import render_template

    return render_template("index.html")


@app.route("/static/<path:nazwa>")
def statyka(nazwa):
    return send_from_directory(app.static_folder, nazwa)


# ------------------------------------------------------------------
# OWOCE I WARZYWA
# ------------------------------------------------------------------
@app.route("/api/owoce/stan_startowy")
def owoce_stan_startowy():
    gieldy = _wszystkie_gieldy()
    ostatni_widok = None
    if PLIK_OSTATNIEGO_WIDOKU.exists():
        import json

        try:
            with PLIK_OSTATNIEGO_WIDOKU.open(encoding="utf-8") as f:
                ostatni_widok = json.load(f)
        except (OSError, ValueError):
            ostatni_widok = None

    return jsonify({
        "gieldy": gieldy,
        "zakresDat": (
            f"{min(_wszystkie_daty())} – {max(_wszystkie_daty())}" if rekordy_owoce else "—"
        ),
        "liczbaWierszyHistorii": len(rekordy_owoce),
        "ostatniaAktualizacja": _tekst_ostatniej_aktualizacji(),
        "ostatniWidok": ostatni_widok,
        "produktyDomyslne": _wczytaj_produkty_domyslne(),
    })


@app.route("/api/owoce/odswiez_csv", methods=["POST"])
def owoce_odswiez_csv():
    global rekordy_owoce
    rekordy_owoce = wczytaj_rekordy(KATALOG_DANYCH)
    return jsonify({
        "zakresDat": (
            f"{min(_wszystkie_daty())} – {max(_wszystkie_daty())}" if rekordy_owoce else "—"
        ),
        "liczbaWierszyHistorii": len(rekordy_owoce),
        "ostatniaAktualizacja": _tekst_ostatniej_aktualizacji(),
    })


@app.route("/api/owoce/produkty", methods=["POST"])
def owoce_produkty():
    dane = request.get_json(force=True) or {}
    gieldy = dane.get("gieldy", [])
    szukaj = (dane.get("szukaj") or "").strip().lower()

    grupy = grupuj_produkty_wg_kategorii(rekordy_owoce, gieldy)
    wynik = []
    for kategoria, produkty in grupy:
        if szukaj:
            produkty = [p for p in produkty if szukaj in p.lower()]
            if not produkty:
                continue
        wynik.append({"kategoria": kategoria, "produkty": produkty, "rozwinieta": bool(szukaj)})
    return jsonify({"grupy": wynik})


@app.route("/api/owoce/widok", methods=["POST"])
def owoce_widok():
    dane = request.get_json(force=True) or {}
    gieldy = dane.get("gieldy", [])
    produkty = dane.get("produkty", [])
    dni = dane.get("dni", [])

    if not gieldy or not dni or not produkty:
        return jsonify({"brakWyboru": True})

    wiersze, kolumny_cenowe = zbuduj_widok(
        rekordy_owoce, gieldy, produkty, dni,
        bool(dane.get("znormalizowane", True)),
        bool(dane.get("pokazMin", True)),
        bool(dane.get("pokazMaks", True)),
    )

    sort_kolumna = dane.get("sortKolumna") or "kategoria"
    odwrocone = bool(dane.get("sortOdwrocone", False))
    wiersze.sort(key=lambda w: (w.get(sort_kolumna) is None, w.get(sort_kolumna)), reverse=odwrocone)

    _zapisz_ostatni_widok(dane)

    return jsonify({
        "brakWyboru": False,
        "wiersze": wiersze,
        "kolumnyCenowe": kolumny_cenowe,
        "liczbaWierszy": len(wiersze),
    })


def _zapisz_ostatni_widok(stan_filtrow: dict) -> None:
    import json

    PLIK_OSTATNIEGO_WIDOKU.parent.mkdir(parents=True, exist_ok=True)
    with PLIK_OSTATNIEGO_WIDOKU.open("w", encoding="utf-8") as f:
        json.dump(stan_filtrow, f, ensure_ascii=False, indent=2)


@app.route("/api/owoce/produkty_domyslne", methods=["POST"])
def owoce_produkty_domyslne():
    dane = request.get_json(force=True) or {}
    _zapisz_produkty_domyslne(dane.get("produkty", []))
    return jsonify({"zapisano": True})


@app.route("/api/owoce/widoki")
def owoce_widoki():
    widoki = wczytaj_zapisane_widoki(PLIK_WIDOKOW)
    return jsonify({"nazwy": sorted(widoki.keys())})


@app.route("/api/owoce/widoki", methods=["POST"])
def owoce_zapisz_widok():
    dane = request.get_json(force=True) or {}
    nazwa = dane.get("nazwa")
    if not nazwa:
        return jsonify({"blad": "Brak nazwy widoku."}), 400
    widoki = wczytaj_zapisane_widoki(PLIK_WIDOKOW)
    widoki[nazwa] = dane.get("stan", {})
    zapisz_zapisane_widoki(PLIK_WIDOKOW, widoki)
    return jsonify({"zapisano": True})


@app.route("/api/owoce/widoki/<nazwa>")
def owoce_wczytaj_widok(nazwa):
    widoki = wczytaj_zapisane_widoki(PLIK_WIDOKOW)
    if nazwa not in widoki:
        return jsonify({"blad": "Nie znaleziono widoku."}), 404
    return jsonify({"stan": widoki[nazwa]})


@app.route("/api/owoce/widoki/<nazwa>", methods=["DELETE"])
def owoce_usun_widok(nazwa):
    widoki = wczytaj_zapisane_widoki(PLIK_WIDOKOW)
    widoki.pop(nazwa, None)
    zapisz_zapisane_widoki(PLIK_WIDOKOW, widoki)
    return jsonify({"usunieto": True})


@app.route("/api/owoce/eksport", methods=["POST"])
def owoce_eksport():
    dane = request.get_json(force=True) or {}
    wiersze, kolumny_cenowe = zbuduj_widok(
        rekordy_owoce,
        dane.get("gieldy", []),
        dane.get("produkty", []),
        dane.get("dni", []),
        bool(dane.get("znormalizowane", True)),
        bool(dane.get("pokazMin", True)),
        bool(dane.get("pokazMaks", True)),
    )
    sort_kolumna = dane.get("sortKolumna") or "kategoria"
    odwrocone = bool(dane.get("sortOdwrocone", False))
    wiersze.sort(key=lambda w: (w.get(sort_kolumna) is None, w.get(sort_kolumna)), reverse=odwrocone)

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        sciezka_tmp = pathlib.Path(tmp.name)
    eksportuj_do_excela(wiersze, kolumny_cenowe, bool(dane.get("znormalizowane", True)), sciezka_tmp)
    return send_file(sciezka_tmp, as_attachment=True, download_name="eksport.xlsx")


# ------------------------------------------------------------------
# DRÓB PL/DE
# ------------------------------------------------------------------
@app.route("/api/drob/stan_startowy")
def drob_stan_startowy():
    return jsonify({
        "kraje": drob_scraper.KRAJE,
        "produkty": drob_scraper.PRODUKTY,
        "status": status_drobiu,
    })


@app.route("/api/drob/status")
def drob_status():
    return jsonify(status_drobiu)


def _widok_drobiu(dane: dict) -> dict:
    kraje = dane.get("kraje", [])
    produkty = dane.get("produkty", [])
    waluta = dane.get("waluta", "EUR")

    kurs_info = None
    kurs_blad = None
    kurs = None
    if waluta == "PLN":
        info = _pobierz_kurs()
        if info is None:
            kurs_blad = "Brak internetu / NBP - nie udało się pobrać kursu EUR/PLN. Pokazuję ceny w EUR."
        else:
            kurs_info = info
            kurs = info["kurs"]

    przeliczone = drob_scraper.przelicz_rekordy(rekordy_drobiu, kraje, produkty, kurs)
    wiersze_tabeli = drob_scraper.sortuj_domyslnie(przeliczone)

    sort_kolumna = dane.get("sortKolumna")
    if sort_kolumna:
        odwrocone = bool(dane.get("sortOdwrocone", False))
        wiersze_tabeli = sorted(wiersze_tabeli, key=lambda w: w[sort_kolumna], reverse=odwrocone)

    kombinacje, wiersze_siatki = drob_scraper.zbuduj_siatke(przeliczone, kraje, produkty)
    jednostka = "PLN" if kurs is not None else "EUR"

    return {
        "tabela": {"wiersze": wiersze_tabeli},
        "siatka": {"kombinacje": kombinacje, "wiersze": wiersze_siatki},
        "jednostka": jednostka,
        "liczbaWierszy": len(wiersze_tabeli),
        "kursInfo": kurs_info,
        "kursBlad": kurs_blad,
    }


@app.route("/api/drob/widok", methods=["POST"])
def drob_widok():
    dane = request.get_json(force=True) or {}
    return jsonify(_widok_drobiu(dane))


@app.route("/api/drob/eksport", methods=["POST"])
def drob_eksport():
    dane = request.get_json(force=True) or {}
    widok = _widok_drobiu(dane)
    jednostka = widok["jednostka"]

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        sciezka_tmp = pathlib.Path(tmp.name)

    if dane.get("widok") == "siatka":
        drob_scraper.eksportuj_siatke_do_excela(
            widok["siatka"]["kombinacje"], widok["siatka"]["wiersze"], jednostka, sciezka_tmp
        )
    else:
        drob_scraper.eksportuj_tabele_do_excela(widok["tabela"]["wiersze"], jednostka, sciezka_tmp)

    return send_file(sciezka_tmp, as_attachment=True, download_name="eksport_drob.xlsx")


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
def main() -> int:
    global rekordy_owoce, rekordy_drobiu

    rekordy_owoce = wczytaj_rekordy(KATALOG_DANYCH)
    rekordy_drobiu = drob_scraper.wczytaj_rekordy()

    threading.Thread(target=_odswiez_drob_w_tle, daemon=True).start()

    # Prosty app.run() wystarczy - restart procesu (POST /api/restart) nie
    # jest juz "w miejscu" (jak os.execv na Windows), tylko pelnym
    # zakonczeniem procesu, ktore odtwarza systemd (Restart=on-failure w
    # scraper-web.service). Nie trzeba wiec wlasnego retry-loopa przy
    # bindowaniu portu - systemd sam pilnuje, zeby na porcie PORT zawsze
    # cos odpowiadalo.
    app.run(host="127.0.0.1", port=PORT, debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
