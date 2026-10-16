"""
Ktora zmienna najbardziej wplywa na liczbe zwrotow?
Dane: sprzedaz per sklep per dzien.

Instalacja:  pip install pandas numpy statsmodels scikit-learn

DOSTOSUJ sekcje KONFIGURACJA do nazw kolumn w swoich danych.
"""
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

# ===================== KONFIGURACJA =====================
PLIK = "sprzedaz.csv"            # albo pd.read_sql(...) / pd.read_excel(...)
KOL_DATA = "data"
KOL_SKLEP = "sklep_id"
KOL_ZWROTY = "liczba_zwrotow"    # zmienna objasniana (liczba zwrotow)
KOL_SPRZEDAZ = "liczba_sprzedanych"  # ekspozycja: im wiecej sprzedazy, tym wiecej zwrotow
# zmienne, ktorych wplyw chcesz sprawdzic:
ZMIENNE_LICZBOWE = ["srednia_cena", "rabat_proc", "udzial_online"]
ZMIENNE_KATEGORYCZNE = ["region", "kategoria_glowna"]
# ========================================================

df = pd.read_csv(PLIK, parse_dates=[KOL_DATA])
df = df[df[KOL_SPRZEDAZ] > 0].copy()

# Cechy kalendarzowe – czesto mocno wplywaja na zwroty
df["dzien_tyg"] = df[KOL_DATA].dt.dayofweek.astype(str)
df["miesiac"] = df[KOL_DATA].dt.month.astype(str)
KATEG = ZMIENNE_KATEGORYCZNE + ["dzien_tyg", "miesiac"]

# Standaryzacja zmiennych liczbowych -> wspolczynniki porownywalne miedzy soba
for c in ZMIENNE_LICZBOWE:
    df[c + "_z"] = (df[c] - df[c].mean()) / df[c].std()

# ---------- 1) Regresja ujemna dwumianowa (dane zliczeniowe) ----------
# offset = log(sprzedazy) -> modelujemy WSKAZNIK zwrotow, nie sama liczbe
# (inaczej "najwazniejsza zmienna" bylaby po prostu wielkosc sklepu)
# C(sklep) = efekty stale sklepu: kontrolujemy stale roznice miedzy sklepami
wzor = (f"{KOL_ZWROTY} ~ " + " + ".join(c + "_z" for c in ZMIENNE_LICZBOWE)
        + " + " + " + ".join(f"C({c})" for c in KATEG) + f" + C({KOL_SKLEP})")
nb = smf.glm(wzor, data=df, family=sm.families.NegativeBinomial(),
             offset=np.log(df[KOL_SPRZEDAZ])).fit(
    cov_type="cluster", cov_kwds={"groups": pd.factorize(df[KOL_SKLEP])[0]})

wyn = pd.DataFrame({
    "IRR (zmiana wsk. zwrotow przy +1 odch. std.)": np.exp(nb.params),
    "p-value": nb.pvalues,
}).loc[[c + "_z" for c in ZMIENNE_LICZBOWE]]
print("=== Regresja ujemna dwumianowa ===")
print(wyn.sort_values("p-value").round(4))
print("IRR 1.15 = +15% zwrotow na kazde +1 odchylenie std. zmiennej\n")

# Istotnosc calych zmiennych kategorycznych (test Walda)
print("=== Testy Walda dla zmiennych kategorycznych ===")
print(nb.wald_test_terms(skip_single=True).summary_frame().round(4), "\n")

# ---------- 2) Model ML + permutation importance ----------
X = df[ZMIENNE_LICZBOWE + KATEG + [KOL_SKLEP]].copy()
for c in KATEG + [KOL_SKLEP]:
    X[c] = X[c].astype("category")
y = df[KOL_ZWROTY] / df[KOL_SPRZEDAZ]   # wskaznik zwrotow

# podzial czasowy: uczymy na przeszlosci, testujemy na ostatnich 20% dni
granica = df[KOL_DATA].quantile(0.8)
tr, te = df[KOL_DATA] <= granica, df[KOL_DATA] > granica

model = HistGradientBoostingRegressor(categorical_features="from_dtype",
                                      max_iter=300, random_state=0)
model.fit(X[tr], y[tr], sample_weight=df.loc[tr, KOL_SPRZEDAZ])
print(f"R2 na zbiorze testowym: {model.score(X[te], y[te]):.3f}")

pi = permutation_importance(model, X[te], y[te], n_repeats=20,
                            random_state=0,
                            sample_weight=df.loc[te, KOL_SPRZEDAZ])
waznosc = pd.DataFrame({"waznosc": pi.importances_mean,
                        "odch_std": pi.importances_std},
                       index=X.columns).sort_values("waznosc", ascending=False)
print("\n=== Permutation importance (spadek R2 po wymieszaniu zmiennej) ===")
print(waznosc.round(4))
