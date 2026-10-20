from copy import deepcopy
from datetime import datetime

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from openpyxl import load_workbook

PLIK_WORD = "szablon.docx"
PLIK_EXCEL = "dane.xlsx"
PLIK_WYJSCIOWY = "wynik.docx"

# --- Ustawienia Excela (litery kolumn wybierasz sam) --------------------------
PIERWSZY_WIERSZ_DANYCH = 4
# Znacznik w dokumencie -> kolumna Excela z wartością dla każdego wiersza
KOLUMNY = {
    "{IMIE}": "A",
    "{NAZWISKO}": "B",
}
KOLUMNA_ILOSCI = "D"  # ile razy skopiować stronę dla danego wiersza
# Data jest jedna dla całego pliku: komórka w nagłówku wybranej kolumny
POLE_DATY = "{DATA}"
KOMORKA_DATY = "C3"
# ------------------------------------------------------------------------------
# Miejsce, w które trafi numer strony, np. 1/2, 2/2
POLE_NUMERU = "{NUMER}"


def tekst(wartosc):
    if isinstance(wartosc, datetime):
        return wartosc.strftime("%d.%m.%Y")
    return "" if wartosc is None else str(wartosc)


def zamien(akapit, stary, nowy):
    """Zamienia tekst, nie ruszając formatowania. Word potrafi podzielić znacznik
    na kilka fragmentów (runów) – wtedy nowy tekst trafia do fragmentu, w którym
    znacznik się zaczyna, a pozostałe fragmenty tracą tylko resztę znacznika."""
    wezly = akapit.findall(".//" + qn("w:t"))
    start = 0
    while True:
        teksty = [w.text or "" for w in wezly]
        idx = "".join(teksty).find(stary, start)
        if idx < 0:
            return
        koniec = idx + len(stary)
        pos = 0
        pierwszy = True
        for wezel, txt in zip(wezly, teksty):
            od, do = pos, pos + len(txt)
            pos = do
            if do <= idx or od >= koniec:
                continue
            a, b = max(idx, od) - od, min(koniec, do) - od
            wezel.text = txt[:a] + (nowy if pierwszy else "") + txt[b:]
            wezel.set(qn("xml:space"), "preserve")
            pierwszy = False
        start = idx + len(nowy)


def nowa_strona(elementy):
    """Kopia zaczyna się od nowej strony. Gdy pierwszy element to akapit, dostaje
    ustawienie 'podział strony przed' – bez dokładania pustych linii."""
    pierwszy = elementy[0]
    if pierwszy.tag == qn("w:p"):
        pierwszy.get_or_add_pPr().get_or_add_pageBreakBefore()
        return elementy
    akapit = OxmlElement("w:p")
    run = OxmlElement("w:r")
    br = OxmlElement("w:br")
    br.set(qn("w:type"), "page")
    run.append(br)
    akapit.append(run)
    return [akapit] + elementy


# Wczytaj dane z Excela: wspólną datę i dla każdego wiersza wartości + liczbę kopii
arkusz = load_workbook(PLIK_EXCEL, data_only=True).active
data = tekst(arkusz[KOMORKA_DATY].value)
wiersze = []
for nr_wiersza in range(PIERWSZY_WIERSZ_DANYCH, arkusz.max_row + 1):
    ilosc = arkusz[f"{KOLUMNA_ILOSCI}{nr_wiersza}"].value
    if ilosc is None:
        continue  # pusty wiersz
    wartosci = {pole: tekst(arkusz[f"{kol}{nr_wiersza}"].value) for pole, kol in KOLUMNY.items()}
    wartosci[POLE_DATY] = data
    wiersze.append((wartosci, int(ilosc)))

doc = Document(PLIK_WORD)

# Zapamiętaj treść szablonu i usuń ją z dokumentu (ustawienia strony zostają)
body = doc.element.body
ustawienia_strony = body.find(qn("w:sectPr"))
szablon = [el for el in body if el is not ustawienia_strony]
for el in szablon:
    body.remove(el)

pierwsza_strona = True
for wartosci, numerator in wiersze:
    for nr in range(1, numerator + 1):
        wartosci[POLE_NUMERU] = f"{nr}/{numerator}"
        kopia = [deepcopy(el) for el in szablon]
        for el in kopia:
            for akapit in el.iter(qn("w:p")):
                for pole, wartosc in wartosci.items():
                    zamien(akapit, pole, wartosc)
        if not pierwsza_strona:
            kopia = nowa_strona(kopia)
        pierwsza_strona = False
        for el in kopia:
            ustawienia_strony.addprevious(el)

# Nagłówki i stopki są wspólne dla wszystkich stron – wstawiamy w nie tylko datę
for part in doc.part.package.iter_parts():
    if part.content_type.endswith(("header+xml", "footer+xml")):
        for akapit in part.element.iter(qn("w:p")):
            zamien(akapit, POLE_DATY, data)

doc.save(PLIK_WYJSCIOWY)
print(f"Zapisano: {PLIK_WYJSCIOWY} ({len(wiersze)} wierszy z Excela)")
