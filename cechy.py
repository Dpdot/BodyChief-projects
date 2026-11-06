"""Budowa partii (wierszy treningowych/prognozowych) i cech modelu.

Cechy "poziomu" (sklepu, produktu) liczone są zawsze na stan
min(data - LUKA, koniec_historii). Dzięki temu w treningu model widzi
informację tak samo nieaktualną, jak w prawdziwej prognozie na 3 miesiące
naprzód — brak wycieku przyszłości i spójność trening/prognoza.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .kalendarz import Kalendarz, cechy_kalendarza

KATEGORIE = ["obiad", "male", "deser"]

CECHY = [
    # kalendarz / okno sprzedaży
    "dzien_tyg", "okno_dni", "okno_sobota", "okno_niedz_handl", "okno_wielka_sobota",
    "skrocone_przez_swieto", "konkurencja_partii", "dni_do_swieta", "dni_od_swieta",
    "swieta_w_3_dniach", "mostek", "okres_swiateczny", "miesiac", "dzien_miesiaca",
    "tydz_roku", "doy_sin", "doy_cos",
    # produkt
    "kategoria_kod", "cena", "koszt_wytworzenia", "marza_proc", "pop_produktu", "n_wystapien",
    # sklep
    "region_kod", "poz_sk_kat_182", "poz_sk_kat_56", "poz_sk_182", "trend_sk_kat",
    "cenz_sk_kat_182", "pop_sk_prod", "profil_sk_dtyg", "sezon_sk_rr",
]
CECHY_KATEGORYCZNE = ["dzien_tyg", "kategoria_kod", "region_kod"]


def _norm_kategoria(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip().str.lower()
    mapa = {"obiady": "obiad", "male danie": "male", "małe": "male", "małe danie": "male",
            "male dania": "male", "małe dania": "male", "desery": "deser"}
    return s.replace(mapa)


def dolacz_atrybuty(df: pd.DataFrame, produkty: pd.DataFrame, sklepy: pd.DataFrame,
                    kal: Kalendarz) -> pd.DataFrame:
    p = produkty.copy()
    p["kategoria"] = _norm_kategoria(p["kategoria"])
    p["marza_proc"] = (p["cena"] - p["koszt_wytworzenia"]) / p["cena"]
    kol = ["produkt_id", "kategoria", "cena", "koszt_wytworzenia", "marza_proc"]
    if "karton" in p:  # opcjonalna wielkość kartonu per produkt
        kol.append("karton")
    df = df.merge(p[kol], on="produkt_id", how="left")
    df = df.merge(sklepy[["sklep_id", "region"]], on="sklep_id", how="left")
    kat = {k: i for i, k in enumerate(KATEGORIE)}
    df["kategoria_kod"] = df["kategoria"].map(kat).fillna(len(kat)).astype(int)
    regiony = sorted(sklepy["region"].astype(str).unique())
    df["region_kod"] = df["region"].map({r: i for i, r in enumerate(regiony)}).fillna(-1).astype(int)
    cal = cechy_kalendarza(df["data"].unique(), kal)
    return df.merge(cal, on="data", how="left")


def przygotuj_historie(dostawy: pd.DataFrame, produkty: pd.DataFrame, sklepy: pd.DataFrame,
                       kal: Kalendarz) -> pd.DataFrame:
    df = dolacz_atrybuty(dostawy.copy(), produkty, sklepy, kal)
    df["sprzedaz"] = (df["dostarczono"] - df["zwrot"]).clip(lower=0)
    # zwrot == 0 -> partia wyprzedana: prawdziwy popyt >= dostarczono (dane ucięte)
    df["wyprzedane"] = (df["zwrot"] <= 0) & (df["dostarczono"] > 0)
    df["okno_dni"] = df["okno_dni"].clip(lower=1)
    df["sprz_dzien"] = df["sprzedaz"] / df["okno_dni"]
    # popularność względna: sprzedaż/dzień vs średnia kategorii w tym samym dniu
    # (usuwa wpływ kalendarza, zostaje "jak dobry jest ten produkt")
    sr_dnia = df.groupby(["data", "kategoria"])["sprz_dzien"].transform("mean")
    df["r_glob"] = df["sprz_dzien"] / sr_dnia.replace(0, np.nan)
    sr_sk_dnia = df.groupby(["data", "kategoria", "sklep_id"])["sprz_dzien"].transform("mean")
    df["r_sklep"] = df["sprz_dzien"] / sr_sk_dnia.replace(0, np.nan)
    df["jeden"] = 1.0
    df["wypr_f"] = df["wyprzedane"].astype(float)
    return df


def _sumy_do(zap: pd.DataFrame, hist: pd.DataFrame, klucze: list[str], kolumny: list[str],
             t: pd.Series, dl: int | None) -> np.ndarray:
    """Sumy `kolumny` z historii w oknie (t-dl, t] (dl=None -> od początku) dla każdego wiersza zap."""
    h = hist.dropna(subset=kolumny)
    d = h.groupby(klucze + ["data"], observed=True)[kolumny].sum().reset_index()
    d = d.sort_values("data")
    d[kolumny] = d.groupby(klucze, observed=True)[kolumny].cumsum()
    d = d.rename(columns={"data": "_t"})

    def lookup(tt: pd.Series) -> np.ndarray:
        q = zap[klucze].copy()
        q["_t"] = pd.to_datetime(tt.to_numpy()).astype("datetime64[ns]")
        q["_i"] = np.arange(len(q))
        q = q.sort_values("_t")
        dd = d.copy()
        dd["_t"] = dd["_t"].astype("datetime64[ns]")
        m = pd.merge_asof(q, dd, on="_t", by=klucze or None, direction="backward")
        m = m.sort_values("_i")
        return m[kolumny].fillna(0).to_numpy(dtype=float)

    hi = lookup(t)
    if dl is None:
        return hi
    return hi - lookup(t - pd.Timedelta(days=dl))


def dodaj_cechy_poziomu(zap: pd.DataFrame, hist: pd.DataFrame, koniec: pd.Timestamp,
                        luka_dni: int = 45) -> pd.DataFrame:
    """Dodaje cechy sklepu/produktu liczone z `hist` na stan min(data - luka, koniec)."""
    zap = zap.copy()
    hist = hist[hist["data"] <= koniec]
    t = (zap["data"] - pd.Timedelta(days=luka_dni)).clip(upper=koniec)

    for dl, nazwa in ((182, "poz_sk_kat_182"), (56, "poz_sk_kat_56")):
        s = _sumy_do(zap, hist, ["sklep_id", "kategoria"], ["sprzedaz", "okno_dni"], t, dl)
        zap[nazwa] = np.where(s[:, 1] > 0, s[:, 0] / np.maximum(s[:, 1], 1), np.nan)
    s = _sumy_do(zap, hist, ["sklep_id"], ["sprzedaz", "okno_dni"], t, 182)
    zap["poz_sk_182"] = np.where(s[:, 1] > 0, s[:, 0] / np.maximum(s[:, 1], 1), np.nan)
    zap["trend_sk_kat"] = zap["poz_sk_kat_56"] / zap["poz_sk_kat_182"]
    s = _sumy_do(zap, hist, ["sklep_id", "kategoria"], ["wypr_f", "jeden"], t, 182)
    zap["cenz_sk_kat_182"] = np.where(s[:, 1] > 0, s[:, 0] / np.maximum(s[:, 1], 1), np.nan)

    # popularność produktu (wszystkie sklepy), z wygładzeniem do 1.0
    s = _sumy_do(zap, hist, ["produkt_id"], ["r_glob", "jeden"], t, None)
    zap["pop_produktu"] = (s[:, 0] + 5 * 1.0) / (s[:, 1] + 5)
    zap["n_wystapien"] = s[:, 1]
    # dopasowanie produktu do konkretnego sklepu (silniej wygładzone)
    s = _sumy_do(zap, hist, ["sklep_id", "produkt_id"], ["r_sklep", "jeden"], t, None)
    zap["pop_sk_prod"] = (s[:, 0] + 3 * 1.0) / (s[:, 1] + 3)

    with np.errstate(divide="ignore", invalid="ignore"):
        # profil dnia tygodnia sklepu: sprzedaż/dzień w ten dzień tygodnia vs średnia sklepu (182 dni)
        s = _sumy_do(zap, hist, ["sklep_id", "dzien_tyg"], ["sprzedaz", "okno_dni"], t, 182)
        prof = np.where(s[:, 1] > 0, s[:, 0] / s[:, 1], np.nan)
        zap["profil_sk_dtyg"] = np.where(zap["poz_sk_182"] > 0, prof / zap["poz_sk_182"], np.nan)
        # sezon r/r: ten sam okres rok temu (8 tyg.) vs średnia roczna sklepu
        t_rok = (zap["data"] - pd.Timedelta(days=365 - 28)).clip(upper=koniec)
        s = _sumy_do(zap, hist, ["sklep_id"], ["sprzedaz", "okno_dni"], t_rok, 56)
        sr = _sumy_do(zap, hist, ["sklep_id"], ["sprzedaz", "okno_dni"], t_rok, 365)
        ok = (s[:, 1] > 0) & (sr[:, 1] > 0) & (sr[:, 0] > 0) & (s[:, 1] * 365 / 56 >= 0.8 * sr[:, 1])
        zap["sezon_sk_rr"] = np.where(ok, (s[:, 0] / s[:, 1]) / (sr[:, 0] / sr[:, 1]), np.nan)
    return zap
