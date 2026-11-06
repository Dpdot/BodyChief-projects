# Prognoza dostaw dań do sklepów

Globalny model (wszystkie sklepy × produkty w jednym modelu) prognozujący popyt na każdą
partię i wyznaczający **ilość do dostawy maksymalizującą marżę** — czyli optymalny
kompromis między sprzedażą a zwrotami.

## Instalacja (Windows, Python 3.12+)

```
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Uruchomienie

```
python -m prognoza --dane dane --wyniki wyniki
```

| opcja | domyślnie | znaczenie |
|---|---|---|
| `--od` / `--do` | dzień po końcu historii / +3 mies. | okres prognozy (RRRR-MM-DD) |
| `--miesiace` | 3 | długość okresu, jeśli nie podano `--do` |
| `--backtest-dni` | 90 | test na ostatnich N dniach historii (0 = pomiń) |
| `--kara-braku` | 0 | dodatkowy koszt braku (zł/szt.), np. utrata klienta — podnosi dostawy |
| `--min-ilosc` | 0 | minimalna ilość każdego dania w sklepie (kompletność oferty) |
| `--karton` | 1 | wielkość kartonu — ilości są jej wielokrotnością (kolumna `karton` w `produkty.csv` ma pierwszeństwo) |
| `--luka` | 45 | jak „stare" są cechy sklepu/produktu w treningu (≈ połowa horyzontu) |
| `--koszty-stale-mies` | 0 | globalne koszty stałe / mies. — tylko do raportu wyniku sklepów |

Test na danych syntetycznych: `python generuj_dane_testowe.py` → `python -m prognoza --dane dane_testowe`.

## Dane wejściowe (katalog `--dane`, CSV z `,` lub `;`)

| plik | kolumny | uwagi |
|---|---|---|
| `dostawy.csv` | `data, sklep_id, produkt_id, dostarczono, zwrot` | **wymagany**; `zwrot` = zwrot z partii dostarczonej w `data` |
| `produkty.csv` | `produkt_id, kategoria, cena, koszt_wytworzenia[, karton]` | **wymagany**; kategoria: `obiad` / `male` / `deser`; `karton` = sztuk w kartonie |
| `sklepy.csv` | `sklep_id, region[, koszt_obslugi_dostawa]` | **wymagany**; koszt obsługi sklepu za jedną dostawę |
| `regiony.csv` | `region, koszt_dostawy` | opcjonalny; koszt jednego dnia dostaw do regionu |
| `menu.csv` | `data, produkt_id[, sklep_id]` | opcjonalny; plan dań na okres prognozy |
| `dni_specjalne.csv` | `data, typ` | opcjonalny; `zamkniete` lub `niedziela_handlowa` (wyjątki) |

Bez `menu.csv` plan dań jest odtwarzany z cyklu ~3 tygodni (ten sam dzień tygodnia 3, 4, 5… tygodni wcześniej).
Jeśli macie plan menu — podajcie go, to wyraźnie poprawia trafność.

Dane z SQL Server: wystarczy zapisać wyniki zapytań do tych CSV albo podmienić `_csv()` w `prognoza/dane.py`
na `pd.read_sql(...)` (SQLAlchemy + `mssql+pyodbc`).

## Wyniki (katalog `--wyniki`)

- `prognoza_dostaw.csv` — dla każdej daty × sklep × danie: okno sprzedaży, średni popyt, **ilosc**,
  oczekiwana sprzedaż, zwrot, prawdopodobieństwo wyprzedania, oczekiwana marża.
- `podsumowanie_dni.csv` — sumy na dzień dostawy.
- `podsumowanie_sklepy.csv` — marża pokrycia na sklep minus koszty dostawy, obsługi i udział kosztów stałych
  (sklepy z ujemnym wynikiem na górze).
- `raport.txt` — backtest + podsumowanie prognozy.

## Jak to działa

1. **Jednostka = partia** (sklep × danie × dzień dostawy) z oknem sprzedaży 1 lub 2 dni.
   Okna wg reguł procesu (`prognoza/kalendarz.py`, `Kalendarz.okno_nominalne`): pn–śr 2 dni, czw 1 dzień (2 przed niedzielą handlową),
   pt 2 dni (1 przed niedzielą handlową), sob (tylko przed niedzielą handlową) 2 dni.
   Dni zamknięte (święta, niedziele niehandlowe) wypadają z okna.
2. **Kalendarz PL liczony algorytmicznie** (nie trzeba go aktualizować): święta ustawowe z Wielkanocą,
   Bożym Ciałem itd., Wigilia wolna od 2025 r., niedziele handlowe (ostatnia niedziela stycznia, kwietnia,
   czerwca, sierpnia, Niedziela Palmowa, 3 niedziele przed Wigilią). Dodatkowo w historii każda sobotnia
   dostawa oznacza handlową niedzielę.
3. **Cechy**: okno (długość, sobota, niedziela handlowa), odległość do/od święta, mostki, dzień przed
   świętem, okres świąteczny, sezonowość, konkurencja partii na półce; poziom sprzedaży sklepu w kategorii
   (182 i 56 dni), trend, udział wyprzedanych partii, profil dni tygodnia sklepu, sezon sklepu rok do roku; popularność dania (względem innych dań tego dnia),
   dopasowanie dania do sklepu; cena, koszt, marża, region.
4. **Model**: gradient boosting ze stratą Poissona (scikit-learn) + rozkład ujemny dwumianowy
   (dyspersja kalibrowana na danych spoza treningu).
5. **Korekta wyprzedanych partii**: zwrot = 0 oznacza, że popyt był ≥ dostawie. Zamiast uczyć się
   sprzedaży (co utrwala braki), model iteracyjnie zastępuje te obserwacje oczekiwanym popytem
   E[D | D ≥ dostawa]. Na danych testowych zmniejsza to błąd prognozy popytu z 29% do 14%.
6. **Ilość** = kwantyl rozkładu popytu na poziomie `(cena − koszt) / cena` (problem gazeciarza):
   zwrot kosztuje koszt wytworzenia, brak — utraconą marżę. Koszty dostawy, obsługi i stałe nie
   zależą od ilości, więc nie zmieniają optymalnej dostawy (są w raporcie wyniku sklepów).

## Założenia do potwierdzenia

- Gdy święto wypada w dzień dostawy, dostawy nie ma, a okno poprzedniej partii się nie wydłuża
  — zamiast tego w każdy otwarty dzień bez towaru (np. sobota po wolnym piątku) dodawana jest dostawa uzupełniająca.
- Dnia przed dniem wolnym nie ma dostawy, jeśli dzień wcześniej była dostawa (jej towar leży 2 dni)
  — przełącznik `POMIJAJ_DOSTAWE_PRZED_WOLNYM` w `prognoza/kalendarz.py`. W historii okna liczone są
  wg faktycznych dni dostaw z `dostawy.csv`.
- Wszystkie aktywne sklepy (dostawy w ostatnich 28 dniach) dostają to samo menu, chyba że `menu.csv` ma `sklep_id`.
- Prognoza nie uwzględnia sprzedaży na sklepach otwartych w niedziele niehandlowe (np. stacje) — dopisać
  takie dni w `dni_specjalne.csv` nie wystarczy, trzeba by kalendarza per sklep.
- Ceny są aktualne (bez historii), więc model nie mierzy elastyczności cenowej.
