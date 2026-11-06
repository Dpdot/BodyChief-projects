"""Wczytywanie danych wejściowych (CSV). Format opisany w README.md."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .kalendarz import Kalendarz


@dataclass
class Dane:
    dostawy: pd.DataFrame          # data, sklep_id, produkt_id, dostarczono, zwrot
    produkty: pd.DataFrame         # produkt_id, kategoria, cena, koszt_wytworzenia
    sklepy: pd.DataFrame           # sklep_id, region[, koszt_obslugi_dostawa]
    regiony: pd.DataFrame | None   # region, koszt_dostawy (za jeden dzień dostaw)
    menu: pd.DataFrame | None      # data, produkt_id[, sklep_id] — plan na okres prognozy
    kalendarz: Kalendarz


def _csv(p: Path) -> pd.DataFrame:
    # sep=None -> automatyczne wykrycie ; lub ,
    return pd.read_csv(p, sep=None, engine="python", encoding="utf-8-sig")


def wczytaj(katalog: str | Path) -> Dane:
    k = Path(katalog)
    dostawy = _csv(k / "dostawy.csv")
    dostawy["data"] = pd.to_datetime(dostawy["data"]).dt.normalize()
    dostawy["zwrot"] = dostawy["zwrot"].fillna(0)
    for c in ("sklep_id", "produkt_id"):
        dostawy[c] = dostawy[c].astype(str)
    # jedna partia = sklep x produkt x dzień dostawy
    dostawy = (dostawy.groupby(["data", "sklep_id", "produkt_id"], as_index=False)
               [["dostarczono", "zwrot"]].sum())

    produkty = _csv(k / "produkty.csv")
    produkty["produkt_id"] = produkty["produkt_id"].astype(str)
    sklepy = _csv(k / "sklepy.csv")
    sklepy["sklep_id"] = sklepy["sklep_id"].astype(str)
    sklepy["region"] = sklepy["region"].astype(str)

    regiony = _csv(k / "regiony.csv") if (k / "regiony.csv").exists() else None
    if regiony is not None:
        regiony["region"] = regiony["region"].astype(str)

    menu = None
    if (k / "menu.csv").exists():
        menu = _csv(k / "menu.csv")
        menu["data"] = pd.to_datetime(menu["data"]).dt.normalize()
        menu["produkt_id"] = menu["produkt_id"].astype(str)
        if "sklep_id" in menu:
            menu["sklep_id"] = menu["sklep_id"].astype(str)

    # Dni specjalne (opcjonalnie): data, typ = zamkniete | niedziela_handlowa
    zamk, nh = set(), set()
    if (k / "dni_specjalne.csv").exists():
        ds = _csv(k / "dni_specjalne.csv")
        for _, r in ds.iterrows():
            d = pd.Timestamp(r["data"]).date()
            (nh if str(r["typ"]).strip().lower().startswith("niedz") else zamk).add(d)
    # Historia: dostawa w sobotę oznacza, że kolejna niedziela była handlowa
    # (chyba że to sobota po zamkniętym piątku — wtedy to dostawa uzupełniająca)
    tmp = Kalendarz(zamk, set())
    for d in dostawy.loc[dostawy["data"].dt.weekday == 5, "data"].unique():
        if tmp.otwarty((pd.Timestamp(d) - pd.Timedelta(days=1)).date()):
            nh.add((pd.Timestamp(d) + pd.Timedelta(days=1)).date())

    brak = set(dostawy["produkt_id"]) - set(produkty["produkt_id"])
    if brak:
        raise ValueError(f"Produkty bez ceny/kosztu w produkty.csv: {sorted(brak)[:10]}")
    hist_dni = {pd.Timestamp(d).date() for d in dostawy["data"].unique()}
    return Dane(dostawy, produkty, sklepy, regiony, menu, Kalendarz(zamk, nh, hist_dni))
