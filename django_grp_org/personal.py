"""
Personaldatensatz zu einem Konto.

Ein Konto ohne Personaldatensatz ist in dieser Anwendung ein halbes Konto:
es kann sich anmelden, aber es hat kein Foto, taucht in keinem Dienstplan
auf, kann keine Zeit buchen und keinen Urlaub beantragen. Auf der Uebersicht
steht dann "Zu diesem Konto gehoert kein Personaldatensatz" — richtig, aber
niemand weiss, wie es dazu kam.

Es kam dazu, weil beide Wege, auf denen das erste Konto entsteht, nur den
Zugang angelegt haben und nicht die Person: `manage.py createsuperuser` und
der Einrichtungsassistent. Hier steht der eine Weg, den beide gehen.
"""

from __future__ import annotations

from datetime import date

from django_grp_org.models import Employee, Provider


def personaldatensatz_anlegen(user, *, access_level: str = "admin") -> Employee | None:
    """
    Legt den Personaldatensatz zu einem Konto an, falls noetig und moeglich.

    Gibt den Datensatz zurueck — den vorhandenen, den neuen, oder `None`,
    wenn es (noch) keinen Traeger gibt. Ohne Traeger geht es nicht: der
    Personaldatensatz haengt daran, und daran haengt die Mandantentrennung.
    Das ist kein Fehler, sondern die Reihenfolge — beim `createsuperuser`
    auf einer leeren Datenbank gibt es noch keine Organisation.

    Der Zugriff ist standardmaessig "admin". Wer per `createsuperuser`
    angelegt wird oder den Einrichtungsassistenten ausfuellt, verwaltet
    dieses System; ihn als Fachkraft einzutragen waere eine Stufe unter dem,
    was das Konto ohnehin darf.
    """
    vorhanden = Employee.objects.filter(user=user).first()
    if vorhanden is not None:
        return vorhanden

    provider = Provider.objects.order_by("id").first()
    if provider is None:
        return None

    # Ohne Namen am Konto steht sonst ein leerer Datensatz in der Liste.
    # Der Benutzername ist kein schoener Vorname, aber ein eindeutiger.
    vorname = (user.first_name or "").strip() or user.get_username()
    nachname = (user.last_name or "").strip() or "—"

    return Employee.objects.create(
        provider=provider,
        user=user,
        access_level=access_level,
        first_name=vorname[:100],
        last_name=nachname[:100],
        email=(user.email or "")[:254],
        hired_on=date.today(),
    )
