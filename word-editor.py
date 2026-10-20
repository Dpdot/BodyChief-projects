from docx import Document
from docx.oxml.ns import qn

PLIK_WEJSCIOWY = "szablon.docx"
PLIK_WYJSCIOWY = "wynik.docx"

# Stałe miejsca w dokumencie i pytanie, które pojawi się przy wpisywaniu
POLA = {
    "{IMIE}": "Imię: ",
    "{NAZWISKO}": "Nazwisko: ",
    "{DATA}": "Data: ",
}


def zamien(akapit, stary, nowy):
    # Word potrafi podzielić tekst na kilka fragmentów, więc szukamy w całym akapicie
    wezly = akapit.findall(".//" + qn("w:t"))
    tekst = "".join(w.text or "" for w in wezly)
    if stary not in tekst:
        return
    wezly[0].text = tekst.replace(stary, nowy)
    for w in wezly[1:]:
        w.text = ""


doc = Document(PLIK_WEJSCIOWY)
wartosci = {pole: input(pytanie) for pole, pytanie in POLA.items()}

for akapit in doc.element.body.iter(qn("w:p")):
    for pole, wartosc in wartosci.items():
        zamien(akapit, pole, wartosc)

doc.save(PLIK_WYJSCIOWY)
print("Zapisano:", PLIK_WYJSCIOWY)
