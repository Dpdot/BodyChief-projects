

from copy import deepcopy

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

PLIK_WEJSCIOWY = "szablon.docx"
PLIK_WYJSCIOWY = "wynik.docx"

# Stałe miejsca w dokumencie i pytanie, które pojawi się przy wpisywaniu
POLA = {
    "{IMIE}": "Imię: ",
    "{NAZWISKO}": "Nazwisko: ",
    "{DATA}": "Data: ",
}
# Miejsce, w które trafi numer strony, np. 1/2, 2/2
POLE_NUMERU = "{NUMER}"


def zamien(akapit, stary, nowy):
    # Word potrafi podzielić tekst na kilka fragmentów, więc szukamy w całym akapicie
    wezly = akapit.findall(".//" + qn("w:t"))
    tekst = "".join(w.text or "" for w in wezly)
    if stary not in tekst:
        return
    wezly[0].text = tekst.replace(stary, nowy)
    for w in wezly[1:]:
        w.text = ""


def podzial_strony():
    akapit = OxmlElement("w:p")
    run = OxmlElement("w:r")
    br = OxmlElement("w:br")
    br.set(qn("w:type"), "page")
    run.append(br)
    akapit.append(run)
    return akapit


doc = Document(PLIK_WEJSCIOWY)
wartosci = {pole: input(pytanie) for pole, pytanie in POLA.items()}
numerator = int(input("Numerator (liczba stron): "))

# Zapamiętaj treść szablonu i usuń ją z dokumentu (ustawienia strony zostają)
body = doc.element.body
ustawienia_strony = body.find(qn("w:sectPr"))
szablon = [el for el in body if el is not ustawienia_strony]
for el in szablon:
    body.remove(el)

for nr in range(1, numerator + 1):
    wartosci[POLE_NUMERU] = f"{nr}/{numerator}"
    for el in szablon:
        kopia = deepcopy(el)
        for akapit in kopia.iter(qn("w:p")):
            for pole, wartosc in wartosci.items():
                zamien(akapit, pole, wartosc)
        ustawienia_strony.addprevious(kopia)
    if nr < numerator:
        ustawienia_strony.addprevious(podzial_strony())

doc.save(PLIK_WYJSCIOWY)
print("Zapisano:", PLIK_WYJSCIOWY)