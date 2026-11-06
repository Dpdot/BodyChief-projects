"""Uruchomienie:  python -m prognoza --dane dane --wyniki wyniki [opcje]

Domyślnie: backtest na ostatnich 90 dniach historii, a potem prognoza
dostaw na 3 miesiące od dnia następnego po końcu historii.
"""
from __future__ import annotations

import argparse
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .cechy import dodaj_cechy_poziomu, dolacz_atrybuty, przygotuj_historie
from .dane import Dane, wczytaj
from scipy import stats

from .model import ModelPopytu, _nb, oczekiwana_sprzedaz, optymalne_ilosci

DNI = ["pon", "wt", "śr", "czw", "pt", "sob", "niedz"]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def trenuj(hist: pd.DataFrame, koniec: pd.Timestamp, luka: int, walidacja_dni: int = 60,
           iteracje: int = 4) -> ModelPopytu:
    """Trening: (1) model na danych bez ostatnich `walidacja_dni`, kalibracja dyspersji
    na tych dniach; (2) model końcowy na całości z tą dyspersją."""
    tr = dodaj_cechy_poziomu(hist, hist, koniec, luka)
    tr = tr[tr["data"] >= tr["data"].min() + pd.Timedelta(days=luka + 28)]  # rozgrzewka cech
    granica = koniec - pd.Timedelta(days=walidacja_dni)
    czesc = tr[tr["data"] <= granica]
    wal = dodaj_cechy_poziomu(hist[hist["data"] > granica], hist, granica, luka)
    m0 = ModelPopytu(iteracje_cenzury=iteracje).fit(czesc)
    alpha = m0.kalibruj_alpha(wal)
    log("  dyspersja NB (alpha): " + ", ".join(f"{k}={v:.3f}" for k, v in sorted(alpha.items())))
    return ModelPopytu(iteracje_cenzury=iteracje).fit(tr, alpha_start=alpha)


def backtest(hist: pd.DataFrame, dni: int, luka: int, kara: float, min_ilosc: int) -> str:
    koniec = hist["data"].max()
    granica = koniec - pd.Timedelta(days=dni)
    log(f"Backtest: trening do {granica.date()}, test {dni} dni")
    model = trenuj(hist[hist["data"] <= granica], granica, luka)
    test = dodaj_cechy_poziomu(hist[hist["data"] > granica], hist, granica, luka)
    mu = model.predict(test)
    a = model._alpha_wiersze(test["kategoria"])
    pol = optymalne_ilosci(test, mu, a, kara, min_ilosc)
    q = pol["ilosc"].to_numpy()
    d = test["dostarczono"].to_numpy()
    s = test["sprzedaz"].to_numpy()
    uc = test["wyprzedane"].to_numpy()
    cena, koszt = test["cena"].to_numpy(), test["koszt_wytworzenia"].to_numpy()
    # sprzedaż przy nowej polityce: dokładna, gdy popyt znany; dolna granica dla partii wyprzedanych
    s_pol = np.where(uc, np.minimum(q, d), np.minimum(q, s))
    z_pol = q - s_pol
    # estymacja: dla wyprzedanych partii, gdy model dał więcej niż historia, dokładamy
    # E[min(D,q) - d | D >= d] z rozkładu modelu (warunkowo na tym, że popyt >= dostawa)
    m_up = uc & (q > d)
    s_est = s_pol.astype(float).copy()
    if m_up.any():
        n_, p_ = _nb(mu[m_up], a[m_up])
        dod = oczekiwana_sprzedaz(mu[m_up], a[m_up], q[m_up]) - oczekiwana_sprzedaz(mu[m_up], a[m_up], d[m_up])
        s_est[m_up] = d[m_up] + dod / np.maximum(stats.nbinom.sf(d[m_up] - 1, n_, p_), 1e-9)
    z_est = q - s_est

    linie = [
        f"BACKTEST {granica.date() + timedelta(days=1)} – {koniec.date()} ({len(test):,} partii)",
        f"  śr. prognozowany popyt/partię {mu.mean():.2f} vs śr. sprzedaż {s.mean():.2f} "
        f"(popyt > sprzedaż, bo {uc.mean():.0%} partii wyprzedano)",
        f"  {'':<26}{'historia':>14}{'model':>14}",
        f"  {'dostarczono':<26}{d.sum():>14,.0f}{q.sum():>14,.0f}",
        f"  {'sprzedaż (model: min.)':<26}{s.sum():>14,.0f}{s_pol.sum():>14,.0f}",
        f"  {'zwroty':<26}{(d - s).sum():>14,.0f}{z_pol.sum():>14,.0f}",
        f"  {'zwroty % dostaw':<26}{(d - s).sum() / d.sum():>14.1%}{z_pol.sum() / max(q.sum(), 1):>14.1%}",
        f"  {'koszt zwrotów':<26}{((d - s) * koszt).sum():>14,.0f}{(z_pol * koszt).sum():>14,.0f}",
        f"  {'marża (model: min.)':<26}{(cena * s - koszt * d).sum():>14,.0f}{(cena * s_pol - koszt * q).sum():>14,.0f}",
        f"  {'sprzedaż (model: estym.)':<26}{'':>14}{s_est.sum():>14,.0f}",
        f"  {'zwroty % (model: estym.)':<26}{'':>14}{z_est.sum() / max(q.sum(), 1):>14.1%}",
        f"  {'marża (model: estym.)':<26}{'':>14}{(cena * s_est - koszt * q).sum():>14,.0f}",
        f"  Partie wyprzedane w historii: {uc.mean():.1%}. Dla nich prawdziwy popyt jest nieznany:",
        "  'min.' = wariant pesymistyczny (sprzedaż nie wyższa niż historyczna dostawa),",
        "  'estym.' = dodatkowa sprzedaż oszacowana z rozkładu popytu modelu.",
    ]
    for k in sorted(test["kategoria"].unique()):
        m = (test["kategoria"] == k).to_numpy()
        linie.append(f"  {k:<8} zwroty hist {(d[m] - s[m]).sum() / d[m].sum():6.1%} -> model "
                     f"{z_pol[m].sum() / max(q[m].sum(), 1):6.1%};  sprzedaż {s[m].sum():>10,.0f} -> {s_pol[m].sum():>10,.0f}")
    return "\n".join(linie)


def plan_menu(dane: Dane, hist: pd.DataFrame, daty: list[date], cykl_dni: int = 21) -> pd.DataFrame:
    """Jakie produkty idą w które dni. Z menu.csv albo z cyklu ~3 tygodni z historii."""
    if dane.menu is not None:
        m = dane.menu[dane.menu["data"].isin(pd.to_datetime(daty))]
        brak = sorted(set(pd.to_datetime(daty)) - set(m["data"]))
        if brak:
            log(f"  UWAGA: menu.csv nie obejmuje {len(brak)} dni dostaw (np. {brak[0].date()}) — uzupełniam z cyklu")
        else:
            return m
    # najczęstszy zestaw produktów każdego dnia historii (top wg liczby sklepów, limit na kategorię)
    limity = {"obiad": 2, "male": 2, "deser": 1}
    cnt = hist.groupby(["data", "kategoria", "produkt_id"]).size().rename("n").reset_index()
    cnt = cnt.sort_values(["data", "kategoria", "n"], ascending=[True, True, False])
    cnt["rank"] = cnt.groupby(["data", "kategoria"]).cumcount()
    cnt = cnt[cnt["rank"] < cnt["kategoria"].map(limity).fillna(1)]
    menu: dict[date, list[str]] = {d.date(): g["produkt_id"].tolist() for d, g in cnt.groupby("data")}
    for d in sorted(daty):
        if d in menu:
            continue
        zrodlo = None
        for tyg in range(cykl_dni // 7, cykl_dni // 7 + 12):  # ten sam dzień tygodnia, cofając się
            c = d - timedelta(days=7 * tyg)
            if c in menu:
                zrodlo = c
                break
        if zrodlo is None:  # np. sobota przed niedzielą handlową — najbliższy dzień z menu
            kand = [c for c in menu if c < d]
            zrodlo = min(kand, key=lambda c: abs((d - c).days - cykl_dni))
        menu[d] = menu[zrodlo]
    wiersze = [(pd.Timestamp(d), p) for d in daty if d in menu for p in menu[d]]
    return pd.DataFrame(wiersze, columns=["data", "produkt_id"])


def prognoza(dane: Dane, hist: pd.DataFrame, od: date, do: date, luka: int, kara: float,
             min_ilosc: int) -> pd.DataFrame:
    koniec = hist["data"].max()
    log(f"Trening modelu końcowego na całej historii (do {koniec.date()})")
    model = trenuj(hist, koniec, luka)
    daty = dane.kalendarz.dni_dostaw(od, do)
    menu = plan_menu(dane, hist, daty)
    aktywne = hist.loc[hist["data"] > koniec - pd.Timedelta(days=28), "sklep_id"].unique()
    sk = pd.DataFrame({"sklep_id": aktywne})
    if "sklep_id" in menu.columns:
        plan = menu[menu["sklep_id"].isin(aktywne)]
    else:
        plan = menu.merge(sk, how="cross")
    plan = dolacz_atrybuty(plan[["data", "sklep_id", "produkt_id"]], dane.produkty, dane.sklepy, dane.kalendarz)
    plan["okno_dni"] = plan["okno_dni"].clip(lower=1)
    plan = dodaj_cechy_poziomu(plan, hist, koniec, luka)
    mu = model.predict(plan)
    wynik = optymalne_ilosci(plan, mu, model._alpha_wiersze(plan["kategoria"]), kara, min_ilosc)
    out = pd.concat([plan[["data", "dzien_tyg", "sklep_id", "region", "produkt_id", "kategoria",
                           "okno_dni", "cena", "koszt_wytworzenia"]], wynik], axis=1)
    out["dzien_tyg"] = out["dzien_tyg"].map(dict(enumerate(DNI)))
    out["okno_sprzedazy"] = out["data"].map(
        lambda d: " + ".join(x.strftime("%d.%m") for x in dane.kalendarz.okno(d.date())))
    return out.sort_values(["data", "sklep_id", "kategoria", "produkt_id"]).reset_index(drop=True)


def podsumowanie_sklepow(out: pd.DataFrame, dane: Dane, koszty_stale: float) -> pd.DataFrame:
    g = out.groupby(["sklep_id", "region"]).agg(
        dni_dostaw=("data", "nunique"), ilosc=("ilosc", "sum"), oczek_sprzedaz=("oczek_sprzedaz", "sum"),
        oczek_zwrot=("oczek_zwrot", "sum"), marza_pokrycia=("oczek_marza", "sum")).reset_index()
    g["zwrot_proc"] = (g["oczek_zwrot"] / g["ilosc"].clip(lower=1)).round(3)
    miesiace = out["data"].dt.to_period("M").nunique()
    if dane.regiony is not None and "koszt_dostawy" in dane.regiony:
        # koszt dostawy regionu na dzień dzielony po równo między sklepy regionu
        n_sk = g.groupby("region")["sklep_id"].transform("count")
        kd = g["region"].map(dane.regiony.set_index("region")["koszt_dostawy"]).fillna(0)
        g["koszt_dostawy"] = (kd * g["dni_dostaw"] / n_sk).round(2)
    if "koszt_obslugi_mies" in dane.sklepy:
        g["koszt_obslugi"] = g["sklep_id"].map(
            dane.sklepy.set_index("sklep_id")["koszt_obslugi_mies"]).fillna(0) * miesiace
    if koszty_stale:
        g["udzial_kosztow_stalych"] = round(koszty_stale * miesiace / len(g), 2)
    kosztowe = [c for c in ("koszt_dostawy", "koszt_obslugi", "udzial_kosztow_stalych") if c in g]
    g["wynik"] = (g["marza_pokrycia"] - g[kosztowe].sum(axis=1)).round(2)
    return g.sort_values("wynik")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Prognoza ilości dostaw dań do sklepów")
    ap.add_argument("--dane", default="dane", help="katalog z plikami CSV")
    ap.add_argument("--wyniki", default="wyniki")
    ap.add_argument("--od", type=date.fromisoformat, help="początek prognozy (domyślnie dzień po końcu historii)")
    ap.add_argument("--do", type=date.fromisoformat, help="koniec prognozy (ma pierwszeństwo przed --miesiace)")
    ap.add_argument("--miesiace", type=int, default=3)
    ap.add_argument("--backtest-dni", type=int, default=90, help="0 = bez backtestu")
    ap.add_argument("--luka", type=int, default=45,
                    help="nieaktualność cech poziomu w treningu (dni); ~połowa horyzontu")
    ap.add_argument("--kara-braku", type=float, default=0.0,
                    help="dodatkowy koszt (zł/szt.) braku towaru ponad utraconą marżę — podnosi dostawy")
    ap.add_argument("--min-ilosc", type=int, default=0, help="minimalna ilość każdego dania w sklepie")
    ap.add_argument("--koszty-stale-mies", type=float, default=0.0, help="globalne koszty stałe / miesiąc (raport)")
    a = ap.parse_args(argv)

    wyn = Path(a.wyniki)
    wyn.mkdir(parents=True, exist_ok=True)
    log(f"Wczytywanie danych z {a.dane}")
    dane = wczytaj(a.dane)
    hist = przygotuj_historie(dane.dostawy, dane.produkty, dane.sklepy, dane.kalendarz)
    log(f"  {len(hist):,} partii, {hist['sklep_id'].nunique()} sklepów, {hist['produkt_id'].nunique()} produktów, "
        f"{hist['data'].min().date()} – {hist['data'].max().date()}, wyprzedane: {hist['wyprzedane'].mean():.1%}")

    raport = []
    if a.backtest_dni:
        bt = backtest(hist, a.backtest_dni, a.luka, a.kara_braku, a.min_ilosc)
        print(bt)
        raport.append(bt)

    od = a.od or (hist["data"].max() + pd.Timedelta(days=1)).date()
    do = a.do or (pd.Timestamp(od) + pd.DateOffset(months=a.miesiace) - pd.Timedelta(days=1)).date()
    out = prognoza(dane, hist, od, do, a.luka, a.kara_braku, a.min_ilosc)
    out.to_csv(wyn / "prognoza_dostaw.csv", index=False, sep=";", decimal=",", encoding="utf-8-sig")
    sk = podsumowanie_sklepow(out, dane, a.koszty_stale_mies)
    sk.to_csv(wyn / "podsumowanie_sklepy.csv", index=False, sep=";", decimal=",", encoding="utf-8-sig")
    dzien = out.groupby(["data", "dzien_tyg", "okno_sprzedazy"], as_index=False)[
        ["ilosc", "oczek_sprzedaz", "oczek_zwrot", "oczek_marza"]].sum()
    dzien.to_csv(wyn / "podsumowanie_dni.csv", index=False, sep=";", decimal=",", encoding="utf-8-sig")

    tot = out[["ilosc", "oczek_sprzedaz", "oczek_zwrot", "oczek_marza"]].sum()
    podsum = (f"PROGNOZA {od} – {do}: {out['data'].nunique()} dni dostaw, {out['sklep_id'].nunique()} sklepów\n"
              f"  dostawy {tot['ilosc']:,.0f} szt., oczek. sprzedaż {tot['oczek_sprzedaz']:,.0f}, "
              f"zwroty {tot['oczek_zwrot']:,.0f} ({tot['oczek_zwrot'] / max(tot['ilosc'], 1):.1%}), "
              f"marża pokrycia {tot['oczek_marza']:,.0f} zł\n"
              f"  sklepy z ujemnym wynikiem po kosztach stałych: {(sk['wynik'] < 0).sum()}")
    print(podsum)
    raport.append(podsum)
    (wyn / "raport.txt").write_text("\n\n".join(raport), encoding="utf-8")
    log(f"Zapisano wyniki w {wyn.resolve()}")


if __name__ == "__main__":
    main()
