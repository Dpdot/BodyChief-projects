"""Globalny model popytu (wszystkie sklepy i produkty naraz) + optymalizacja ilości.

1. Popyt na partię ~ ujemny dwumianowy (NB): średnia mu z modelu GBM (strata Poissona),
   nadmierna dyspersja alpha estymowana osobno dla każdej kategorii.
2. Partie wyprzedane (zwrot = 0) to obserwacje ucięte: wiemy tylko, że popyt >= dostawa.
   Korekta EM: cel zastępowany przez E[D | D >= dostawa] i model uczony ponownie.
   Bez tego model uczy się historycznych braków i utrwala zbyt małe dostawy.
3. Ilość do dostawy = kwantyl krytyczny (problem gazeciarza):
       cr = (cena - koszt + kara_braku) / (cena + kara_braku)
   Zwrot kosztuje koszt wytworzenia, brak towaru — utraconą marżę.
   Koszty dostawy do regionu, obsługi sklepu i stałe nie zależą od ilości,
   więc nie zmieniają optymalnej ilości (są tylko w raporcie wyniku).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import optimize, stats
from sklearn.ensemble import HistGradientBoostingRegressor

from .cechy import CECHY, CECHY_KATEGORYCZNE

MAKS_K = 3000  # górna granica pętli po liczbie sztuk


def _nb(mu: np.ndarray, alpha: np.ndarray):
    n = 1.0 / np.maximum(alpha, 1e-6)
    p = n / (n + np.maximum(mu, 1e-9))
    return n, p


def oczekiwana_sprzedaz(mu, alpha, q) -> np.ndarray:
    """E[min(D, q)] = sum_{k=0}^{q-1} P(D > k)."""
    mu, alpha, q = map(np.asarray, (mu, alpha, q))
    n, p = _nb(mu, alpha)
    wynik = np.zeros(len(mu))
    for k in range(int(min(q.max(initial=0), MAKS_K))):
        m = q > k
        if not m.any():
            break
        wynik[m] += stats.nbinom.sf(k, n[m], p[m])
    return wynik


def oczekiwany_popyt_powyzej(mu, alpha, q) -> np.ndarray:
    """E[D | D >= q] — do imputacji popytu w partiach wyprzedanych."""
    mu, alpha, q = map(np.asarray, (mu, alpha, q))
    n, p = _nb(mu, alpha)
    czesc = np.zeros(len(mu))  # E[D * 1{D < q}]
    for k in range(1, int(min(q.max(initial=0), MAKS_K))):
        m = q > k
        if not m.any():
            break
        czesc[m] += k * stats.nbinom.pmf(k, n[m], p[m])
    ogon = stats.nbinom.sf(q - 1, n, p)
    wynik = (mu - czesc) / np.maximum(ogon, 1e-9)
    return np.maximum(wynik, q)  # popyt co najmniej tyle, ile dostarczono


def estymuj_alpha(y, mu, uciete) -> float:
    """MLE dyspersji NB z uwzględnieniem obserwacji uciętych."""
    y, mu, uciete = np.asarray(y, float), np.asarray(mu, float), np.asarray(uciete, bool)

    def nll(log_a):
        n, p = _nb(mu, np.full(len(mu), np.exp(log_a)))
        ll = np.where(uciete, stats.nbinom.logsf(y - 1, n, p), stats.nbinom.logpmf(y, n, p))
        return -np.sum(ll)

    r = optimize.minimize_scalar(nll, bounds=(np.log(1e-4), np.log(5.0)), method="bounded")
    return float(np.exp(r.x))


class ModelPopytu:
    def __init__(self, iteracje_cenzury: int = 4, losowosc: int = 42, **gbm_params):
        self.iteracje = iteracje_cenzury
        self.losowosc = losowosc
        self.gbm_params = dict(loss="poisson", learning_rate=0.05, max_iter=800,
                               max_leaf_nodes=63, min_samples_leaf=40, l2_regularization=1.0,
                               early_stopping=True, validation_fraction=0.1,
                               n_iter_no_change=30) | gbm_params
        self.alpha: dict[str, float] = {}
        self.gbm: HistGradientBoostingRegressor | None = None

    def _nowy_gbm(self):
        kat = [c in CECHY_KATEGORYCZNE for c in CECHY]
        return HistGradientBoostingRegressor(categorical_features=kat, random_state=self.losowosc,
                                             **self.gbm_params)

    def _alpha_wiersze(self, kategoria: pd.Series) -> np.ndarray:
        dom = np.median(list(self.alpha.values())) if self.alpha else 0.2
        return kategoria.map(self.alpha).fillna(dom).to_numpy(float)

    def fit(self, df: pd.DataFrame, alpha_start: dict[str, float] | None = None) -> "ModelPopytu":
        if alpha_start:
            self.alpha = dict(alpha_start)
        X = df[CECHY]
        y = df["sprzedaz"].to_numpy(float)
        uciete = df["wyprzedane"].to_numpy(bool)
        q = df["dostarczono"].to_numpy(float)
        cel = y.copy()
        for it in range(self.iteracje + 1):
            self.gbm = self._nowy_gbm().fit(X, cel)
            if it == self.iteracje or not uciete.any():
                break
            mu = self.gbm.predict(X)
            if not alpha_start:  # w pierwszym przebiegu szacunek in-sample
                self.alpha = {k: estymuj_alpha(y[m], mu[m], uciete[m])
                              for k, m in ((k, (df["kategoria"] == k).to_numpy())
                                           for k in df["kategoria"].unique())}
            a = self._alpha_wiersze(df["kategoria"])
            cel = y.copy()
            cel[uciete] = oczekiwany_popyt_powyzej(mu[uciete], a[uciete], q[uciete])
        return self

    def kalibruj_alpha(self, df: pd.DataFrame) -> dict[str, float]:
        """Dyspersja na danych spoza treningu (uczciwa niepewność prognozy)."""
        mu = self.predict(df)
        y = df["sprzedaz"].to_numpy(float)
        uc = df["wyprzedane"].to_numpy(bool)
        self.alpha = {k: estymuj_alpha(y[m], mu[m], uc[m])
                      for k in df["kategoria"].unique()
                      for m in [(df["kategoria"] == k).to_numpy()]}
        return self.alpha

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return np.maximum(self.gbm.predict(df[CECHY]), 1e-6)


def optymalne_ilosci(df: pd.DataFrame, mu: np.ndarray, alpha: np.ndarray,
                     kara_braku: float = 0.0, min_ilosc: int = 0,
                     max_mnoznik: float | None = None, karton: int = 1) -> pd.DataFrame:
    """Ilość = kwantyl krytyczny rozkładu popytu + oczekiwane skutki.

    karton: wielkość kartonu — ilość musi być jej wielokrotnością. Kolumna `karton`
    w df (z produkty.csv) ma pierwszeństwo; puste wartości -> parametr `karton`.
    """
    cena = df["cena"].to_numpy(float)
    koszt = df["koszt_wytworzenia"].to_numpy(float)
    cr = np.clip((cena - koszt + kara_braku) / (cena + kara_braku), 0.01, 0.995)
    n, p = _nb(mu, alpha)
    q = stats.nbinom.ppf(cr, n, p)
    q = np.where(np.isfinite(q), q, 0).astype(int)
    if max_mnoznik:
        q = np.minimum(q, np.ceil(mu * max_mnoznik).astype(int) + 1)
    k = np.full(len(df), max(int(karton), 1))
    if "karton" in df:
        k = df["karton"].fillna(k[0] if len(k) else 1).clip(lower=1).to_numpy(int)
    if (k > 1).any():
        # marża wklęsła w q -> najlepsza wielokrotność to jedna z dwóch sąsiednich
        dol = q // k * k
        gora = dol + k
        def zysk(x):
            return (cena + kara_braku) * oczekiwana_sprzedaz(mu, alpha, x) - koszt * x
        q = np.where(zysk(gora) > zysk(dol), gora, dol)
    q = np.maximum(q, -(-min_ilosc // k) * k)  # minimum zaokrąglone w górę do pełnego kartonu
    sprz = oczekiwana_sprzedaz(mu, alpha, q)
    wynik = pd.DataFrame({
        "popyt_sredni": mu.round(2),
        "poziom_krytyczny": cr.round(3),
        "ilosc": q,
        "kartony": q // k,
        "oczek_sprzedaz": sprz.round(2),
        "oczek_zwrot": (q - sprz).round(2),
        "p_wyprzedania": stats.nbinom.sf(q - 1, n, p).round(3),
        "oczek_marza": (cena * sprz - koszt * q).round(2),
    }, index=df.index)
    return wynik
