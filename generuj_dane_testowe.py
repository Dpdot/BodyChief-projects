"""Generuje syntetyczne dane w formacie wejściowym (do testów pipeline'u).

python generuj_dane_testowe.py --katalog dane_testowe
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from prognoza.kalendarz import Kalendarz

ap = argparse.ArgumentParser()
ap.add_argument("--katalog", default="dane_testowe")
ap.add_argument("--sklepy", type=int, default=40)
ap.add_argument("--od", default="2024-11-01")
ap.add_argument("--do", default="2026-10-31")
a = ap.parse_args()
rng = np.random.default_rng(7)
kal = Kalendarz()
out = Path(a.katalog)
out.mkdir(exist_ok=True)

# produkty: cykl 15 dni dostaw (~3 tygodnie) -> 30 obiadów, 30 małych, 15 deserów (+ zapas na sobotę)
prod = []
for kat, n, cena, koszt in (("obiad", 32, 24.0, 11.0), ("male", 32, 14.0, 6.0), ("deser", 16, 9.0, 3.5)):
    for i in range(n):
        c = round(cena * rng.uniform(0.85, 1.15), 2)
        prod.append({"produkt_id": f"{kat[0].upper()}{i:03d}", "kategoria": kat, "cena": c,
                     "koszt_wytworzenia": round(koszt * rng.uniform(0.85, 1.15), 2)})
produkty = pd.DataFrame(prod)
pop = dict(zip(produkty["produkt_id"], rng.lognormal(0, 0.3, len(produkty))))

regiony = ["Mazowsze", "Malopolska", "Slask", "Pomorze"]
sklepy = pd.DataFrame({"sklep_id": [f"S{i:03d}" for i in range(a.sklepy)],
                       "region": rng.choice(regiony, a.sklepy),
                       "koszt_obslugi_dostawa": rng.uniform(35, 70, a.sklepy).round(2)})
wielkosc = dict(zip(sklepy["sklep_id"], rng.lognormal(1.6, 0.45, a.sklepy)))
afin = {(s, p): rng.lognormal(0, 0.15) for s in sklepy["sklep_id"] for p in produkty["produkt_id"]}
pd.DataFrame({"region": regiony, "koszt_dostawy": [900, 750, 820, 680]}).to_csv(out / "regiony.csv", index=False)

udzial_kat = {"obiad": 1.0, "male": 0.8, "deser": 0.6}
dzien_f = [0.95, 1.0, 1.0, 1.05, 1.15, 0.85, 0.7]
listy = {k: produkty.loc[produkty["kategoria"] == k, "produkt_id"].tolist() for k in udzial_kat}

def mnoznik_dnia(d: date) -> float:
    f = dzien_f[d.weekday()]
    if kal.swieto(d + timedelta(days=1)) or kal.swieto(d + timedelta(days=2)):
        f *= 1.2
    if kal.swieto(d - timedelta(days=1)):
        f *= 0.9
    pw = not kal.otwarty(d - timedelta(days=1)) or (d - timedelta(days=1)).weekday() >= 5
    nw = not kal.otwarty(d + timedelta(days=1)) or (d + timedelta(days=1)).weekday() >= 5
    if pw and nw and d.weekday() < 5:
        f *= 0.7  # mostek
    if (d.month == 12 and d.day >= 22) or (d.month == 1 and d.day <= 6):
        f *= 0.65
    if d.month in (7, 8):
        f *= 0.85
    return f

start, koniec = date.fromisoformat(a.od), date.fromisoformat(a.do)
daty = kal.dni_dostaw(start, koniec)
wiersze = []
for idx, d in enumerate(daty):
    okno = kal.okno(d)
    trend = 1 + 0.10 * (d - start).days / 730
    for kat, lim in (("obiad", 2), ("male", 2), ("deser", 1)):
        lst = listy[kat]
        cyc = (idx * lim) % (len(lst) - (lim if kat != "deser" else 1))
        menu = lst[cyc:cyc + lim]
        for s in sklepy["sklep_id"]:
            for p in menu:
                lam = sum(mnoznik_dnia(x) * (1.0 if i == 0 else 0.55) for i, x in enumerate(okno))
                lam *= wielkosc[s] * udzial_kat[kat] * pop[p] * afin[(s, p)] * trend / lim * 1.6
                popyt = rng.negative_binomial(4, 4 / (4 + lam)) if lam > 0 else 0
                # historyczna, prosta polityka: średnia sklepu x 1.15 z szumem
                base = wielkosc[s] * udzial_kat[kat] / lim * 1.6 * (1.55 if len(okno) == 2 else 1.0)
                dost = max(1, int(round(base * 1.15 * rng.uniform(0.85, 1.15))))
                wiersze.append((d, s, p, dost, max(dost - popyt, 0), lam))

dost = pd.DataFrame(wiersze, columns=["data", "sklep_id", "produkt_id", "dostarczono", "zwrot", "lam"])
dost.pop("lam").to_frame().assign(data=dost["data"], sklep_id=dost["sklep_id"], produkt_id=dost["produkt_id"]).to_csv(out.parent / (out.name + "_prawda.csv"), index=False)
dost.to_csv(out / "dostawy.csv", index=False)
produkty.to_csv(out / "produkty.csv", index=False)
sklepy.to_csv(out / "sklepy.csv", index=False)
print(f"{len(dost):,} partii; zwroty {dost['zwrot'].sum() / dost['dostarczono'].sum():.1%}; "
      f"wyprzedane {(dost['zwrot'] == 0).mean():.1%}")
