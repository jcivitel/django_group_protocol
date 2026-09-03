"""
Hintergrundaufgaben rund um E-Mail.

Zwei Stueck: eine Mail verschicken, und einmal am Tag an faellige Aufgaben
erinnern.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger("django_grp.mail")

# Wie weit voraus die Erinnerung schaut.
FRIST_VORLAUF_TAGE = 2


@shared_task(
    name="django_grp_mail.versenden",
    bind=True,
    max_retries=4,
    # Eine Minute, dann zwei, dann vier, dann acht. Ein Mailserver, der
    # gerade nicht antwortet, ist meist in ein paar Minuten wieder da; sofort
    # nachzufassen bringt nichts ausser Last.
    retry_backoff=60,
    retry_backoff_max=600,
    retry_jitter=True,
)
def versenden_task(self, nachricht_id: int):
    from .service import versenden

    nachricht = versenden(nachricht_id)
    if nachricht is None:
        return "weg"

    # Nur bei echtem Fehlschlag wiederholen. "skipped" heisst, der Versand
    # ist aus - das wird durch Wiederholen nicht besser.
    if nachricht.status == "failed" and self.request.retries < self.max_retries:
        raise self.retry(exc=RuntimeError(nachricht.error))

    return nachricht.status


@shared_task(name="django_grp_mail.erinnere_an_faellige_aufgaben")
def erinnere_an_faellige_aufgaben():
    """
    Erinnert an Protokollaufgaben, deren Frist naeher rueckt.

    Eine Mail je zustaendiger Person mit allen ihren Aufgaben, nicht eine je
    Aufgabe: wer sechs offene Punkte hat, bekommt sonst sechs Mails und liest
    keine davon.

    Zugeordnet wird ueber das Feld "who" - es traegt freien Text und wird mit
    dem Namen der Mitarbeitenden verglichen. Das ist ungenau, aber es ist die
    einzige Verbindung, die es gibt: eine Aufgabe zeigt auf keinen
    Benutzerdatensatz.
    """
    from django_grp_backend.models import ProtocolTodo
    from django_grp_org.models import Employee

    from .service import einstellen

    jetzt = timezone.now()
    grenze = jetzt + timedelta(days=FRIST_VORLAUF_TAGE)

    faellig = list(
        ProtocolTodo.objects.filter(when__lte=grenze).select_related(
            "protocol__group"
        )
    )
    if not faellig:
        return "nichts faellig"

    # Name (klein) -> Person mit E-Mail
    personen = {
        mitarbeiter.get_full_name().strip().lower(): mitarbeiter
        for mitarbeiter in Employee.objects.exclude(email="").filter(
            left_on__isnull=True
        )
    }

    nach_person: dict[int, list] = {}
    for aufgabe in faellig:
        person = personen.get((aufgabe.who or "").strip().lower())
        if person is None:
            continue
        nach_person.setdefault(person.id, []).append((person, aufgabe))

    verschickt = 0
    for eintraege in nach_person.values():
        person = eintraege[0][0]
        zeilen = []
        for _, aufgabe in sorted(eintraege, key=lambda paar: paar[1].when):
            ueberfaellig = "überfällig" if aufgabe.when < jetzt else "fällig"
            zeilen.append(
                f"- {aufgabe.what.strip()}\n"
                f"  {ueberfaellig} am {timezone.localtime(aufgabe.when):%d.%m.%Y um %H:%M} "
                f"({aufgabe.protocol.group.name})"
            )

        einstellen(
            to=person.email,
            subject=f"{len(zeilen)} offene Aufgaben aus den Protokollen",
            body=(
                f"Guten Morgen {person.first_name},\n\n"
                "diese Aufgaben stehen bei dir und laufen bald ab:\n\n"
                + "\n\n".join(zeilen)
                + "\n\nAbgehakt wird im jeweiligen Protokoll.\n"
            ),
            kind="todo_due",
        )
        verschickt += 1

    return f"{verschickt} Erinnerungen eingestellt"
