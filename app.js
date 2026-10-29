/*
 * app.js
 * -------
 * Cała logika interfejsu przeglądarki cen w wersji webowej. Nie zawiera
 * ŻADNEJ logiki filtrowania/sortowania/przeliczania cen - to wszystko
 * liczy serwer (serwer_web.py + niezmienione moduły logika_widoku.py /
 * drob_scraper.py). Ten plik tylko: trzyma stan wybranych filtrów,
 * wysyła go do API i renderuje zwrócony JSON w tabelach, dokładnie
 * odwzorowując zakładki i panele dawnej aplikacji Tkinter.
 */

(() => {
"use strict";

const dzisiaj = () => new Date().toISOString().slice(0, 10);

// ------------------------------------------------------------------
// STAN (odpowiednik atrybutów self.* z dawnej klasy AplikacjaPrzegladarki)
// ------------------------------------------------------------------
const stan = {
    owoce: {
        gieldyWybrane: new Set(),
        produktyWybrane: new Set(),
        dniWybrane: [],
        trybCen: "znorm",
        pokazMin: true,
        pokazMaks: true,
        sortKolumna: "kategoria",
        sortOdwrocone: false,
        ostatnieGrupy: [],       // ostatnio pobrane grupy produktów (do zaznacz/odznacz wszystko)
    },
    drob: {
        kraje: [],
        produkty: [],
        krajeWybrane: new Set(),
        produktyWybrane: new Set(),
        waluta: "EUR",
        widok: "tabela",
        sortKolumna: null,       // null = domyślne sortowanie wielopoziomowe
        sortOdwrocone: false,
    },
};

async function api(sciezka, opcje) {
    const odpowiedz = await fetch(sciezka, opcje);
    if (!odpowiedz.ok) {
        const tekst = await odpowiedz.text().catch(() => "");
        throw new Error(`${sciezka}: ${odpowiedz.status} ${tekst}`);
    }
    return odpowiedz.json();
}

async function pobierzPlik(sciezka, opcje, domyslnaNazwa) {
    const odpowiedz = await fetch(sciezka, opcje);
    if (!odpowiedz.ok) {
        const dane = await odpowiedz.json().catch(() => ({}));
        alert(dane.blad || "Nie udało się wyeksportować danych.");
        return;
    }
    const blob = await odpowiedz.blob();
    let nazwa = domyslnaNazwa;
    const naglowek = odpowiedz.headers.get("Content-Disposition") || "";
    const dopasowanie = naglowek.match(/filename="?([^"]+)"?/);
    if (dopasowanie) nazwa = dopasowanie[1];
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = nazwa;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
}

// ------------------------------------------------------------------
// ZAKŁADKI (Notebook - z definicji wzajemnie się wykluczające)
// ------------------------------------------------------------------
function ustawZakladki(kontener, atrybut) {
    kontener.querySelectorAll(`[data-${atrybut}]`).forEach((przycisk) => {
        przycisk.addEventListener("click", () => {
            const cel = przycisk.getAttribute(`data-${atrybut}`);
            kontener.querySelectorAll(`[data-${atrybut}]`).forEach((p) => p.classList.remove("aktywna"));
            przycisk.classList.add("aktywna");
            kontener.parentElement.querySelectorAll(`.${atrybut === "zakladka" ? "karta-zakladki" : "podkarta"}`)
                .forEach((karta) => karta.classList.remove("aktywna"));
            const idKarty = atrybut === "zakladka" ? `karta-${cel}` : `podkarta-${cel}`;
            document.getElementById(idKarty).classList.add("aktywna");
        });
    });
}

// ------------------------------------------------------------------
// OWOCE I WARZYWA
// ------------------------------------------------------------------
function renderGieldy(gieldy) {
    const kontener = document.getElementById("lista-gield");
    kontener.innerHTML = "";
    gieldy.forEach((gielda) => {
        const etykieta = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = stan.owoce.gieldyWybrane.has(gielda);
        checkbox.addEventListener("change", () => {
            if (checkbox.checked) stan.owoce.gieldyWybrane.add(gielda);
            else stan.owoce.gieldyWybrane.delete(gielda);
            odswiezPanelProduktow();
            odswiezTabeleOwocow();
        });
        etykieta.appendChild(checkbox);
        etykieta.appendChild(document.createTextNode(" " + gielda));
        kontener.appendChild(etykieta);
    });
}

function renderDni() {
    const lista = document.getElementById("lista-dni");
    lista.innerHTML = "";
    [...stan.owoce.dniWybrane].sort().forEach((dzien) => {
        const opcja = document.createElement("option");
        opcja.value = dzien;
        opcja.textContent = dzien;
        lista.appendChild(opcja);
    });
}

function dodajDzien() {
    const pole = document.getElementById("pole-daty");
    const wartosc = pole.value;
    if (!wartosc) {
        alert("Wybierz poprawną datę z kalendarza.");
        return;
    }
    if (!stan.owoce.dniWybrane.includes(wartosc)) {
        stan.owoce.dniWybrane.push(wartosc);
        renderDni();
        odswiezTabeleOwocow();
    }
}

function usunDzien() {
    const lista = document.getElementById("lista-dni");
    const zaznaczona = lista.selectedOptions[0];
    if (!zaznaczona) return;
    stan.owoce.dniWybrane = stan.owoce.dniWybrane.filter((d) => d !== zaznaczona.value);
    renderDni();
    odswiezTabeleOwocow();
}

async function odswiezPanelProduktow() {
    const fraza = document.getElementById("pole-szukaj").value.trim();
    const dane = await api("/api/owoce/produkty", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ gieldy: [...stan.owoce.gieldyWybrane], szukaj: fraza }),
    });
    stan.owoce.ostatnieGrupy = dane.grupy;
    renderPanelProduktow(dane.grupy);
}

function tekstEtykietyKategorii(kategoria, produkty) {
    const zaznaczone = produkty.filter((p) => stan.owoce.produktyWybrane.has(p)).length;
    return `${kategoria}  (${zaznaczone}/${produkty.length})`;
}

function renderPanelProduktow(grupy) {
    const kontener = document.getElementById("panel-produktow");
    kontener.innerHTML = "";
    grupy.forEach(({ kategoria, produkty, rozwinieta }) => {
        const sekcja = document.createElement("div");
        sekcja.className = "sekcja-kategorii";

        const naglowek = document.createElement("div");
        naglowek.className = "sekcja-naglowek";
        const strzalka = document.createElement("span");
        strzalka.className = "sekcja-strzalka";
        strzalka.textContent = rozwinieta ? "▼" : "▶";
        const etykieta = document.createElement("span");
        etykieta.textContent = tekstEtykietyKategorii(kategoria, produkty);
        naglowek.appendChild(strzalka);
        naglowek.appendChild(etykieta);

        const zawartosc = document.createElement("div");
        zawartosc.className = "sekcja-zawartosc" + (rozwinieta ? " rozwinieta" : "");

        const etykietaWszystkie = document.createElement("label");
        const checkboxWszystkie = document.createElement("input");
        checkboxWszystkie.type = "checkbox";
        checkboxWszystkie.checked = produkty.every((p) => stan.owoce.produktyWybrane.has(p));
        checkboxWszystkie.addEventListener("change", () => {
            produkty.forEach((p) => {
                if (checkboxWszystkie.checked) stan.owoce.produktyWybrane.add(p);
                else stan.owoce.produktyWybrane.delete(p);
            });
            renderPanelProduktow(stan.owoce.ostatnieGrupy);
            odswiezTabeleOwocow();
        });
        etykietaWszystkie.appendChild(checkboxWszystkie);
        etykietaWszystkie.appendChild(document.createTextNode(" zaznacz całą kategorię"));
        zawartosc.appendChild(etykietaWszystkie);

        produkty.forEach((produkt) => {
            const etykietaP = document.createElement("label");
            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.className = "produkt-checkbox";
            checkbox.checked = stan.owoce.produktyWybrane.has(produkt);
            checkbox.addEventListener("change", () => {
                if (checkbox.checked) stan.owoce.produktyWybrane.add(produkt);
                else stan.owoce.produktyWybrane.delete(produkt);
                etykieta.textContent = tekstEtykietyKategorii(kategoria, produkty);
                checkboxWszystkie.checked = produkty.every((p) => stan.owoce.produktyWybrane.has(p));
                odswiezTabeleOwocow();
            });
            etykietaP.appendChild(checkbox);
            etykietaP.appendChild(document.createTextNode(" " + produkt));
            zawartosc.appendChild(etykietaP);
        });

        naglowek.addEventListener("click", (e) => {
            if (e.target === checkboxWszystkie) return;
            zawartosc.classList.toggle("rozwinieta");
            strzalka.textContent = zawartosc.classList.contains("rozwinieta") ? "▼" : "▶";
        });

        sekcja.appendChild(naglowek);
        sekcja.appendChild(zawartosc);
        kontener.appendChild(sekcja);
    });
}

const ETYKIETY_KOLUMN_OWOCE = { kategoria: "Kategoria", produkt: "Produkt", gielda: "Giełda" };

function formatujWartoscOwoce(wartosc) {
    if (wartosc === null || wartosc === undefined) return "—";
    if (typeof wartosc === "number") return `${wartosc.toFixed(2)} zł`;
    return wartosc;
}

async function odswiezTabeleOwocow() {
    const znormalizowane = stan.owoce.trybCen === "znorm";
    const zadanie = {
        gieldy: [...stan.owoce.gieldyWybrane],
        produkty: [...stan.owoce.produktyWybrane],
        dni: stan.owoce.dniWybrane,
        znormalizowane,
        pokazMin: stan.owoce.pokazMin,
        pokazMaks: stan.owoce.pokazMaks,
        sortKolumna: stan.owoce.sortKolumna,
        sortOdwrocone: stan.owoce.sortOdwrocone,
    };
    const dane = await api("/api/owoce/widok", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(zadanie),
    });

    const ramkaTabeli = document.getElementById("ramka-tabeli-owoce");
    const etykietaBrak = document.getElementById("etykieta-brak");
    const etykietaLiczby = document.getElementById("etykieta-liczby-wierszy");

    if (dane.brakWyboru) {
        ramkaTabeli.style.display = "none";
        etykietaBrak.style.display = "block";
        etykietaLiczby.textContent = "";
        return;
    }
    ramkaTabeli.style.display = "block";
    etykietaBrak.style.display = "none";
    etykietaLiczby.textContent = `${dane.liczbaWierszy} wierszy`;

    const etykietaJedn = znormalizowane ? "Jedn. (znorm.)" : "Jedn.";
    const kolejnosc = ["kategoria", "produkt", "gielda", "jednostka", ...dane.kolumnyCenowe];

    const thead = document.querySelector("#tabela-owoce thead");
    const tbody = document.querySelector("#tabela-owoce tbody");
    thead.innerHTML = "";
    const wierszNaglowka = document.createElement("tr");
    kolejnosc.forEach((klucz) => {
        const th = document.createElement("th");
        const etykietaBazowa = klucz === "jednostka" ? etykietaJedn : (ETYKIETY_KOLUMN_OWOCE[klucz] || klucz);
        let strzalka = "";
        if (klucz === stan.owoce.sortKolumna) strzalka = stan.owoce.sortOdwrocone ? " ▼" : " ▲";
        th.textContent = etykietaBazowa + strzalka;
        th.addEventListener("click", () => {
            if (stan.owoce.sortKolumna === klucz) stan.owoce.sortOdwrocone = !stan.owoce.sortOdwrocone;
            else { stan.owoce.sortKolumna = klucz; stan.owoce.sortOdwrocone = false; }
            odswiezTabeleOwocow();
        });
        wierszNaglowka.appendChild(th);
    });
    thead.appendChild(wierszNaglowka);

    tbody.innerHTML = "";
    dane.wiersze.forEach((wiersz) => {
        const tr = document.createElement("tr");
        kolejnosc.forEach((klucz) => {
            const td = document.createElement("td");
            const wartosc = wiersz[klucz];
            td.textContent = formatujWartoscOwoce(wartosc);
            if (typeof wartosc === "number") td.classList.add("kolumna-liczbowa");
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    // Serwer zapisuje "ostatni widok" automatycznie przy każdym /api/owoce/widok
    // (odpowiednik na_zmiane_filtrow() -> _zapisz_ostatni_widok() z Tkinter).
}

function stanOwocowDoZapisu() {
    return {
        gieldy: [...stan.owoce.gieldyWybrane],
        produkty: [...stan.owoce.produktyWybrane],
        dni: stan.owoce.dniWybrane,
        znormalizowane: stan.owoce.trybCen === "znorm",
        pokazMin: stan.owoce.pokazMin,
        pokazMaks: stan.owoce.pokazMaks,
    };
}

function zastosujStan(stanWidoku, wszystkieGieldy) {
    const gieldy = (stanWidoku.gieldy || []).filter((g) => wszystkieGieldy.includes(g));
    stan.owoce.gieldyWybrane = new Set(gieldy.length ? gieldy : wszystkieGieldy);
    stan.owoce.produktyWybrane = new Set(stanWidoku.produkty || []);
    stan.owoce.dniWybrane = [...(stanWidoku.dni || [])];
    stan.owoce.trybCen = stanWidoku.znormalizowane === false ? "oryg" : "znorm";
    stan.owoce.pokazMin = stanWidoku.pokazMin !== false;
    stan.owoce.pokazMaks = stanWidoku.pokazMaks !== false;

    document.querySelector(`input[name="tryb-cen"][value="${stan.owoce.trybCen}"]`).checked = true;
    document.getElementById("pokaz-min").checked = stan.owoce.pokazMin;
    document.getElementById("pokaz-maks").checked = stan.owoce.pokazMaks;
}

async function odswiezListeWidokow() {
    const dane = await api("/api/owoce/widoki");
    const combo = document.getElementById("combo-widoki");
    const biezaca = combo.value;
    combo.innerHTML = '<option value=""></option>';
    dane.nazwy.forEach((nazwa) => {
        const opcja = document.createElement("option");
        opcja.value = nazwa;
        opcja.textContent = nazwa;
        combo.appendChild(opcja);
    });
    combo.value = dane.nazwy.includes(biezaca) ? biezaca : "";
}

// ------------------------------------------------------------------
// DRÓB PL/DE
// ------------------------------------------------------------------
function renderListeCheckboxow(kontenerId, wartosci, zbior, naZmiane) {
    const kontener = document.getElementById(kontenerId);
    kontener.innerHTML = "";
    wartosci.forEach((wartosc) => {
        const etykieta = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = zbior.has(wartosc);
        checkbox.addEventListener("change", () => {
            if (checkbox.checked) zbior.add(wartosc);
            else zbior.delete(wartosc);
            naZmiane();
        });
        etykieta.appendChild(checkbox);
        etykieta.appendChild(document.createTextNode(" " + wartosc));
        kontener.appendChild(etykieta);
    });
}

const ETYKIETY_KOLUMN_DROBIU = {
    kraj: "Kraj", produkt: "Produkt", data_od: "Data od", data_do: "Data do",
    cena_100kg: "Cena za 100 kg", cena_1kg: "Cena za 1 kg",
};
const KOLUMNY_DROBIU = ["kraj", "produkt", "data_od", "data_do", "cena_100kg", "cena_1kg"];

async function odswiezTabeleDrobiu() {
    const zadanie = {
        kraje: [...stan.drob.krajeWybrane],
        produkty: [...stan.drob.produktyWybrane],
        waluta: stan.drob.waluta,
        sortKolumna: stan.drob.sortKolumna,
        sortOdwrocone: stan.drob.sortOdwrocone,
    };
    const dane = await api("/api/drob/widok", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(zadanie),
    });

    const etykietaKursu = document.getElementById("etykieta-status-kursu");
    if (dane.kursBlad) {
        etykietaKursu.textContent = dane.kursBlad;
        document.querySelector('input[name="waluta-drobiu"][value="EUR"]').checked = true;
        stan.drob.waluta = "EUR";
    } else if (dane.kursInfo) {
        etykietaKursu.textContent = `Kurs NBP z ${dane.kursInfo.data}: 1 EUR = ${dane.kursInfo.kurs.toFixed(4)} PLN`;
    } else {
        etykietaKursu.textContent = "";
    }

    document.getElementById("etykieta-liczby-wierszy-drobiu").textContent = `${dane.liczbaWierszy} wierszy`;

    renderTabeleDrobiu(dane.tabela.wiersze, dane.jednostka);
    renderSiatkeDrobiu(dane.siatka.kombinacje, dane.siatka.wiersze, dane.jednostka);
}

function renderTabeleDrobiu(wiersze, jednostka) {
    const thead = document.querySelector("#tabela-drob-tabela thead");
    const tbody = document.querySelector("#tabela-drob-tabela tbody");
    thead.innerHTML = "";
    const wierszNaglowka = document.createElement("tr");
    KOLUMNY_DROBIU.forEach((klucz) => {
        const th = document.createElement("th");
        let strzalka = "";
        if (klucz === stan.drob.sortKolumna) strzalka = stan.drob.sortOdwrocone ? " ▼" : " ▲";
        th.textContent = ETYKIETY_KOLUMN_DROBIU[klucz] + strzalka;
        th.addEventListener("click", () => {
            if (stan.drob.sortKolumna === klucz) stan.drob.sortOdwrocone = !stan.drob.sortOdwrocone;
            else { stan.drob.sortKolumna = klucz; stan.drob.sortOdwrocone = false; }
            odswiezTabeleDrobiu();
        });
        wierszNaglowka.appendChild(th);
    });
    thead.appendChild(wierszNaglowka);

    tbody.innerHTML = "";
    wiersze.forEach((wiersz) => {
        const tr = document.createElement("tr");
        const wartosci = [
            wiersz.kraj, wiersz.produkt, wiersz.data_od, wiersz.data_do,
            `${wiersz.cena_100kg.toFixed(2)} ${jednostka}`, `${wiersz.cena_1kg.toFixed(4)} ${jednostka}`,
        ];
        wartosci.forEach((wartosc, i) => {
            const td = document.createElement("td");
            td.textContent = wartosc;
            if (i >= 4) td.classList.add("kolumna-liczbowa");
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

function renderSiatkeDrobiu(kombinacje, wierszeSiatki, jednostka) {
    const thead = document.querySelector("#tabela-drob-siatka thead");
    const tbody = document.querySelector("#tabela-drob-siatka tbody");
    thead.innerHTML = "";
    const wierszNaglowka = document.createElement("tr");
    const thData = document.createElement("th");
    thData.textContent = "Data od — do";
    wierszNaglowka.appendChild(thData);
    kombinacje.forEach(([kraj, produkt]) => {
        const th = document.createElement("th");
        th.textContent = `${kraj} ${produkt} (za 1 kg)`;
        wierszNaglowka.appendChild(th);
    });
    thead.appendChild(wierszNaglowka);

    tbody.innerHTML = "";
    wierszeSiatki.forEach((wiersz) => {
        const tr = document.createElement("tr");
        const tdData = document.createElement("td");
        tdData.textContent = `${wiersz.data_od} — ${wiersz.data_do}`;
        tr.appendChild(tdData);
        wiersz.ceny.forEach((cena) => {
            const td = document.createElement("td");
            td.textContent = cena === null ? "—" : `${cena.toFixed(4)} ${jednostka}`;
            td.classList.add("kolumna-liczbowa");
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

function przelaczWidokDrobiu() {
    const tabela = document.getElementById("ramka-tabeli-drobiu");
    const siatka = document.getElementById("ramka-siatki-drobiu");
    if (stan.drob.widok === "siatka") {
        tabela.style.display = "none";
        siatka.style.display = "block";
    } else {
        siatka.style.display = "none";
        tabela.style.display = "block";
    }
}

let odpytywanieStatusu = null;
async function odswiezStatusDrobiu() {
    const dane = await api("/api/drob/status");
    document.getElementById("etykieta-status-drobiu").textContent = dane.tekst;
    if (dane.stan === "odswiezanie") {
        odpytywanieStatusu = setTimeout(odswiezStatusDrobiu, 1500);
    } else {
        odswiezTabeleDrobiu();
    }
}

// ------------------------------------------------------------------
// RESTART SERWERA (przycisk "Odśwież dane", krok 2)
// ------------------------------------------------------------------
async function poczekajNaSerwerIPrzeladuj(przycisk) {
    for (let i = 0; i < 30; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        try {
            const odp = await fetch("/api/owoce/stan_startowy");
            if (odp.ok) {
                location.reload();
                return;
            }
        } catch (e) {
            // Serwer jeszcze nie wstał po restarcie - próbuj dalej.
        }
    }
    przycisk.disabled = false;
    przycisk.textContent = "Odśwież dane";
    alert(
        "Serwer nie odpowiedział po 30 sekundach od restartu.\n\n" +
        "Sprawdź, czy usługa wstała poprawnie (np. journalctl -u scraper-web -n 50), " +
        "a potem odśwież tę stronę ręcznie (F5)."
    );
}

// ------------------------------------------------------------------
// INICJALIZACJA
// ------------------------------------------------------------------
async function init() {
    ustawZakladki(document.querySelector(".paski-zakladek:not(.podzakladki)"), "zakladka");
    document.querySelectorAll(".paski-zakladek.podzakladki").forEach((pasek) => ustawZakladki(pasek, "podzakladka"));

    // --- Owoce i warzywa ---
    const startOwoce = await api("/api/owoce/stan_startowy");
    document.getElementById("etykieta-zakres-dat").textContent =
        `Dane: ${startOwoce.zakresDat}    (produktów: ${startOwoce.liczbaWierszyHistorii} wierszy historii)`;
    document.getElementById("etykieta-ostatnia-aktualizacja").textContent = startOwoce.ostatniaAktualizacja;

    stan.owoce.gieldyWybrane = new Set(startOwoce.gieldy);
    if (startOwoce.ostatniWidok) {
        zastosujStan(startOwoce.ostatniWidok, startOwoce.gieldy);
    } else {
        stan.owoce.produktyWybrane = new Set(startOwoce.produktyDomyslne || []);
    }
    if (!stan.owoce.dniWybrane.includes(dzisiaj())) stan.owoce.dniWybrane.push(dzisiaj());

    document.getElementById("pole-daty").value = dzisiaj();
    renderGieldy(startOwoce.gieldy);
    renderDni();
    await odswiezPanelProduktow();
    await odswiezTabeleOwocow();
    await odswiezListeWidokow();

    document.getElementById("btn-dodaj-dzien").addEventListener("click", dodajDzien);
    document.getElementById("btn-usun-dzien").addEventListener("click", usunDzien);
    document.querySelectorAll('input[name="tryb-cen"]').forEach((radio) => {
        radio.addEventListener("change", () => {
            stan.owoce.trybCen = document.querySelector('input[name="tryb-cen"]:checked').value;
            odswiezTabeleOwocow();
        });
    });
    document.getElementById("pokaz-min").addEventListener("change", (e) => {
        stan.owoce.pokazMin = e.target.checked;
        odswiezTabeleOwocow();
    });
    document.getElementById("pokaz-maks").addEventListener("change", (e) => {
        stan.owoce.pokazMaks = e.target.checked;
        odswiezTabeleOwocow();
    });
    document.getElementById("pole-szukaj").addEventListener("input", odswiezPanelProduktow);
    document.getElementById("btn-zaznacz-wszystko").addEventListener("click", async () => {
        stan.owoce.ostatnieGrupy.forEach(({ produkty }) => produkty.forEach((p) => stan.owoce.produktyWybrane.add(p)));
        renderPanelProduktow(stan.owoce.ostatnieGrupy);
        odswiezTabeleOwocow();
    });
    document.getElementById("btn-odznacz-wszystko").addEventListener("click", () => {
        stan.owoce.produktyWybrane.clear();
        renderPanelProduktow(stan.owoce.ostatnieGrupy);
        odswiezTabeleOwocow();
    });
    document.getElementById("btn-zapisz-domyslne").addEventListener("click", async () => {
        const lista = [...stan.owoce.produktyWybrane].sort();
        await api("/api/owoce/produkty_domyslne", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ produkty: lista }),
        });
        alert(`Zapisano ${lista.length} produktów jako domyślne.\n\nBędą zaznaczane automatycznie przy pierwszym uruchomieniu (bez zapamiętanego widoku) oraz po kliknięciu „Przywróć widok domyślny” w zakładce „Zapisane widoki”.`);
    });
    document.getElementById("btn-odswiez-csv").addEventListener("click", async () => {
        const przycisk = document.getElementById("btn-odswiez-csv");

        // Krok 1: jak dotychczas - ponowne wczytanie CSV do pamięci, bez
        // restartu procesu (dokładnie stare zachowanie tego przycisku).
        const dane = await api("/api/owoce/odswiez_csv", { method: "POST" });
        document.getElementById("etykieta-zakres-dat").textContent =
            `Dane: ${dane.zakresDat}    (produktów: ${dane.liczbaWierszyHistorii} wierszy historii)`;
        document.getElementById("etykieta-ostatnia-aktualizacja").textContent = dane.ostatniaAktualizacja;
        await odswiezPanelProduktow();
        await odswiezTabeleOwocow();

        // Krok 2 (nowość): do tego dochodzi faktyczny restart całego procesu
        // serwera. Strona na chwilę straci połączenie - to oczekiwane.
        if (!confirm(
            `Wczytano ${dane.liczbaWierszyHistorii} wierszy historii cen.\n\n` +
            "Zrestartować teraz serwer, żeby zastosować wszystkie zmiany od zera? " +
            "Strona na chwilę straci połączenie i przeładuje się sama."
        )) {
            return;
        }

        przycisk.disabled = true;
        przycisk.textContent = "Restartowanie...";

        try {
            await fetch("/api/restart", { method: "POST" });
        } catch (e) {
            // Połączenie może się zerwać w trakcie odpowiedzi - to normalne,
            // proces po drugiej stronie właśnie się kończy.
        }

        await poczekajNaSerwerIPrzeladuj(przycisk);
    });
    document.getElementById("btn-eksport-owoce").addEventListener("click", () => {
        pobierzPlik("/api/owoce/eksport", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...stanOwocowDoZapisu(), sortKolumna: stan.owoce.sortKolumna, sortOdwrocone: stan.owoce.sortOdwrocone }),
        }, "eksport.xlsx");
    });

    document.getElementById("btn-wczytaj-widok").addEventListener("click", async () => {
        const nazwa = document.getElementById("combo-widoki").value;
        if (!nazwa) return;
        const dane = await api(`/api/owoce/widoki/${encodeURIComponent(nazwa)}`);
        zastosujStan(dane.stan, startOwoce.gieldy);
        renderGieldy(startOwoce.gieldy);
        renderDni();
        await odswiezPanelProduktow();
        await odswiezTabeleOwocow();
    });
    document.getElementById("btn-usun-widok").addEventListener("click", async () => {
        const nazwa = document.getElementById("combo-widoki").value;
        if (!nazwa) return;
        if (!confirm(`Usunąć zapisany widok "${nazwa}"?`)) return;
        await api(`/api/owoce/widoki/${encodeURIComponent(nazwa)}`, { method: "DELETE" });
        await odswiezListeWidokow();
    });
    document.getElementById("btn-zapisz-widok").addEventListener("click", async () => {
        const nazwa = prompt("Nazwa widoku:");
        if (!nazwa) return;
        await api("/api/owoce/widoki", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ nazwa, stan: stanOwocowDoZapisu() }),
        });
        await odswiezListeWidokow();
        document.getElementById("combo-widoki").value = nazwa;
    });
    document.getElementById("btn-widok-domyslny").addEventListener("click", async () => {
        // Wczytaj aktualne produkty domyślne z serwera (bez nadpisywania ich) -
        // odpowiednik _przywroc_widok_domyslny() w dawnej aplikacji Tkinter.
        const startOwoceObecne = await api("/api/owoce/stan_startowy");
        stan.owoce.gieldyWybrane = new Set(startOwoceObecne.gieldy);
        stan.owoce.produktyWybrane = new Set(startOwoceObecne.produktyDomyslne || []);
        stan.owoce.dniWybrane = [dzisiaj()];
        renderGieldy(startOwoceObecne.gieldy);
        renderDni();
        await odswiezPanelProduktow();
        await odswiezTabeleOwocow();
        if (!startOwoceObecne.produktyDomyslne || !startOwoceObecne.produktyDomyslne.length) {
            alert('Nie zapisano jeszcze żadnych domyślnych produktów.\nZaznacz produkty w zakładce „Produkty” i kliknij „Zapisz jako domyślne”, żeby ten przycisk je przywracał.');
        }
    });

    // --- Drób PL/DE ---
    const startDrob = await api("/api/drob/stan_startowy");
    stan.drob.kraje = startDrob.kraje;
    stan.drob.produkty = startDrob.produkty;
    stan.drob.krajeWybrane = new Set(startDrob.kraje);
    stan.drob.produktyWybrane = new Set(startDrob.produkty);
    renderListeCheckboxow("lista-krajow-drobiu", startDrob.kraje, stan.drob.krajeWybrane, odswiezTabeleDrobiu);
    renderListeCheckboxow("lista-produktow-drobiu", startDrob.produkty, stan.drob.produktyWybrane, odswiezTabeleDrobiu);
    document.getElementById("etykieta-status-drobiu").textContent = startDrob.status.tekst;
    await odswiezTabeleDrobiu();
    if (startDrob.status.stan === "odswiezanie") odswiezStatusDrobiu();

    document.querySelectorAll('input[name="waluta-drobiu"]').forEach((radio) => {
        radio.addEventListener("change", () => {
            stan.drob.waluta = document.querySelector('input[name="waluta-drobiu"]:checked').value;
            odswiezTabeleDrobiu();
        });
    });
    document.querySelectorAll('input[name="widok-drobiu"]').forEach((radio) => {
        radio.addEventListener("change", () => {
            stan.drob.widok = document.querySelector('input[name="widok-drobiu"]:checked').value;
            przelaczWidokDrobiu();
        });
    });
    document.getElementById("btn-eksport-drob").addEventListener("click", () => {
        pobierzPlik("/api/drob/eksport", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                kraje: [...stan.drob.krajeWybrane], produkty: [...stan.drob.produktyWybrane],
                waluta: stan.drob.waluta, sortKolumna: stan.drob.sortKolumna,
                sortOdwrocone: stan.drob.sortOdwrocone, widok: stan.drob.widok,
            }),
        }, "eksport_drob.xlsx");
    });
}

document.addEventListener("DOMContentLoaded", init);
})();
