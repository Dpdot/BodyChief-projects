"""Powiadomienie e-mail o zmianach cen (ogólna informacja - szczegóły są w osobnym raporcie).

Ustawienia skrzynki: sekcja [smtp] w db_config.ini (wzór w db_config.example.ini).
Bez tej sekcji wysyłka jest wyłączona.
"""

import configparser
import smtplib
import ssl
from email.message import EmailMessage

import historia


def ustawienia_smtp():
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(historia.PLIK_KONFIGURACJI, encoding="utf-8")
    if not cfg.has_section("smtp") or not cfg["smtp"].get("host"):
        return None
    return cfg["smtp"]


def tresc_komunikatu(zmiany):
    """zmiany: {źródło: liczba indeksów ze zmianą ceny}"""
    linie = [f'Zmiana ceny w "{zrodlo}" dla {ile} {"indeksu" if ile == 1 else "indeksów"}.' for zrodlo, ile in zmiany.items()]
    return "\n".join(linie + ["", "Szczegóły w raporcie."])


def wyslij_powiadomienie(zmiany, dzis):
    """Wysyła mail, jeśli są zmiany cen i skonfigurowano SMTP. Zwraca opis wyniku do logu."""
    if not zmiany:
        return "brak zmian cen - mail nie został wysłany"
    smtp = ustawienia_smtp()
    if smtp is None:
        return "wykryto zmiany cen, ale wysyłka maili jest wyłączona (brak sekcji [smtp] w db_config.ini)"

    odbiorcy = [a.strip() for a in smtp["to"].split(",") if a.strip()]
    mail = EmailMessage()
    mail["Subject"] = f"Zmiany cen w cennikach - {dzis.isoformat()}"
    mail["From"] = smtp.get("from") or smtp["user"]
    mail["To"] = ", ".join(odbiorcy)
    mail.set_content(tresc_komunikatu(zmiany))

    host, port = smtp["host"], smtp.getint("port", 465)
    szyfrowanie = smtp.get("security", "ssl").lower()  # ssl (port 465) / starttls (port 587)
    kontekst = ssl.create_default_context()
    if szyfrowanie == "ssl":
        serwer = smtplib.SMTP_SSL(host, port, context=kontekst, timeout=30)
    else:
        serwer = smtplib.SMTP(host, port, timeout=30)
    with serwer:
        if szyfrowanie == "starttls":
            serwer.starttls(context=kontekst)
        if smtp.get("user"):
            serwer.login(smtp["user"], smtp.get("password", ""))
        serwer.send_message(mail)
    return f"mail wysłany do {', '.join(odbiorcy)}"
