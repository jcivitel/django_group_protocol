"""
Woran eine Benachrichtigung haengt.

Drei Ereignisse loesen eine Mail aus. Die vierte Benachrichtigung - die
Erinnerung an faellige Aufgaben - laeuft nicht ueber ein Signal, sondern
einmal taeglich ueber Celery beat (siehe tasks.py).

Alles hier ist bewusst still: schlaegt eine Benachrichtigung fehl, darf der
Fachvorgang trotzdem durchgehen. Wer einen Urlaubsantrag genehmigt, soll
keine Fehlerseite bekommen, bloss weil der Mailserver gerade nicht antwortet.
Der Postausgang haelt den Fehlschlag fest, dort ist er nachzulesen.
"""

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

logger = logging.getLogger("django_grp.mail")


def _sicher(funktion):
    """Laesst eine Benachrichtigung scheitern, ohne den Vorgang mitzureissen."""

    def huelle(*args, **kwargs):
        try:
            funktion(*args, **kwargs)
        except Exception:  # noqa: BLE001
            logger.exception("Benachrichtigung fehlgeschlagen")

    return huelle


def _adresse(mitarbeiter) -> str:
    return (getattr(mitarbeiter, "email", "") or "").strip()


def _status_merken(sender, instance):
    """
    Den gespeicherten Stand festhalten, bevor er ueberschrieben wird.

    Ohne das kaeme bei jedem Speichern eine Mail - auch wenn nur eine Notiz
    geaendert wurde.
    """
    if instance.pk is None:
        instance._vorheriger_status = None
        return
    vorher = sender.objects.filter(pk=instance.pk).values_list("status", flat=True)
    instance._vorheriger_status = vorher[0] if vorher else None


def _unveraendert(instance) -> bool:
    return instance.status == getattr(instance, "_vorheriger_status", None)


# ------------------------------------------------- Abwesenheit entschieden


@receiver(pre_save, sender="django_grp_duty.Absence")
@_sicher
def _abwesenheit_vorher(sender, instance, **kwargs):
    _status_merken(sender, instance)


@receiver(post_save, sender="django_grp_duty.Absence")
@_sicher
def _abwesenheit_entschieden(sender, instance, created, **kwargs):
    from .service import benachrichtigen

    if created or _unveraendert(instance):
        return
    if instance.status not in ("approved", "rejected"):
        return

    empfaenger = _adresse(instance.employee)
    if not empfaenger:
        return

    entschieden = "genehmigt" if instance.status == "approved" else "abgelehnt"
    zeilen = [
        f"Hallo {instance.employee.first_name},",
        "",
        f"dein Antrag wurde {entschieden}.",
        "",
        f"Art:      {instance.absence_type}",
        f"Zeitraum: {instance.start_date:%d.%m.%Y} bis {instance.end_date:%d.%m.%Y}",
    ]
    if instance.decision_note:
        zeilen.append(f"Hinweis:  {instance.decision_note}")
    zeilen += ["", "Der Dienstplan ist entsprechend angepasst.", ""]

    benachrichtigen(
        instance.employee,
        subject=f"Antrag {entschieden}: {instance.absence_type}",
        body="\n".join(zeilen),
        kind="absence_decided",
        # Auf einem Sperrbildschirm steht der Anlass, nicht der Inhalt.
        push_text=f"Dein Antrag wurde {entschieden}.",
        push_url="/meine-dienste",
    )


# ------------------------------------------------- Dienstplan veroeffentlicht


@receiver(pre_save, sender="django_grp_duty.DutyPlan")
@_sicher
def _plan_vorher(sender, instance, **kwargs):
    _status_merken(sender, instance)


@receiver(post_save, sender="django_grp_duty.DutyPlan")
@_sicher
def _plan_veroeffentlicht(sender, instance, created, **kwargs):
    """
    Beim Wechsel auf "veroeffentlicht" bekommt jede eingeteilte Person ihre
    eigenen Dienste - nicht den ganzen Plan.
    """
    from .service import benachrichtigen

    if created or instance.status != "published" or _unveraendert(instance):
        return

    nach_person: dict[int, list] = {}
    for dienst in instance.shifts.select_related("employee", "shift_type").filter(
        employee__isnull=False
    ):
        nach_person.setdefault(dienst.employee_id, []).append(dienst)

    for dienste in nach_person.values():
        person = dienste[0].employee
        empfaenger = _adresse(person)
        if not empfaenger:
            continue

        zeilen = [
            f"Hallo {person.first_name},",
            "",
            f"der Dienstplan für {instance.month:02d}/{instance.year} "
            f"({instance.department}) steht.",
            "",
            "Deine Dienste:",
            "",
        ]
        for dienst in sorted(dienste, key=lambda d: d.date):
            art = dienst.shift_type
            zeilen.append(
                f"- {dienst.date:%d.%m.}  {art.short_code}  "
                f"{art.start_time:%H:%M}–{art.end_time:%H:%M}"
            )
        zeilen.append("")

        benachrichtigen(
            person,
            subject=(
                f"Dienstplan {instance.month:02d}/{instance.year} "
                f"veröffentlicht — {len(dienste)} Dienste"
            ),
            body="\n".join(zeilen),
            kind="plan_published",
            push_text=f"{len(dienste)} Dienste für dich eingeteilt.",
            push_url="/meine-dienste",
        )


# ------------------------------------------------------------ Diensttausch


@receiver(pre_save, sender="django_grp_duty.ShiftSwap")
@_sicher
def _tausch_vorher(sender, instance, **kwargs):
    _status_merken(sender, instance)


@receiver(post_save, sender="django_grp_duty.ShiftSwap")
@_sicher
def _tausch_bewegt(sender, instance, created, **kwargs):
    """
    Ein Tausch laeuft ueber drei Stufen: angeboten, angenommen, bestaetigt.

    Benachrichtigt wird jeweils die Seite, die gerade nichts getan hat - wer
    selbst geklickt hat, weiss es schon.
    """
    from .service import benachrichtigen

    if not created and _unveraendert(instance):
        return

    anbieter = instance.offered_by
    uebernehmer = instance.accepted_by
    dienst = instance.shift

    if created:
        # Ein offenes Angebot hat noch keine Gegenseite - dann gibt es
        # niemanden zu benachrichtigen, und das ist in Ordnung.
        if uebernehmer is None or not _adresse(uebernehmer):
            return
        zeilen = [
            f"Hallo {uebernehmer.first_name},",
            "",
            f"{anbieter.get_full_name()} bietet dir einen Dienst an:",
            "",
            str(dienst),
        ]
        if instance.reason:
            zeilen.append(f"Grund: {instance.reason}")
        zeilen += ["", "Unter „Diensttausch“ kannst du zusagen oder ablehnen.", ""]
        benachrichtigen(
            uebernehmer,
            push_text="Dir wird ein Dienst angeboten.",
            push_url="/meine-dienste",
            subject=f"Diensttausch angefragt: {dienst}",
            body="\n".join(zeilen),
            kind="swap",
        )
        return

    if instance.status == "accepted" and _adresse(anbieter):
        wer = uebernehmer.get_full_name() if uebernehmer else "Jemand"
        benachrichtigen(
            anbieter,
            push_text="Dein Tauschangebot wurde angenommen.",
            push_url="/meine-dienste",
            subject=f"Diensttausch angenommen: {dienst}",
            body="\n".join(
                [
                    f"Hallo {anbieter.first_name},",
                    "",
                    f"{wer} übernimmt deinen Dienst:",
                    "",
                    str(dienst),
                    "",
                    "Es fehlt noch die Bestätigung durch die Leitung.",
                    "Bis dahin bleibt der Dienst bei dir.",
                    "",
                ]
            ),
            kind="swap",
        )
        return

    if instance.status == "confirmed":
        # Jetzt hat der Dienst wirklich die Person gewechselt - das muessen
        # beide wissen.
        for person, satz in (
            (anbieter, "Dein Dienst ist abgegeben:"),
            (uebernehmer, "Du übernimmst diesen Dienst:"),
        ):
            if person is None or not _adresse(person):
                continue
            benachrichtigen(
                person,
                push_text="Ein Diensttausch wurde bestätigt.",
                push_url="/meine-dienste",
                subject=f"Diensttausch bestätigt: {dienst}",
                body="\n".join(
                    [
                        f"Hallo {person.first_name},",
                        "",
                        f"der Tausch wurde bestätigt. {satz}",
                        "",
                        str(dienst),
                        "",
                    ]
                ),
                kind="swap",
            )
        return

    if instance.status in ("declined", "withdrawn"):
        # Zurueckgezogen hat der Anbieter selbst - dann geht die Nachricht an
        # die Gegenseite, sonst an den Anbieter.
        empfaenger = uebernehmer if instance.status == "withdrawn" else anbieter
        if empfaenger is None or not _adresse(empfaenger):
            return
        wort = "abgelehnt" if instance.status == "declined" else "zurückgezogen"
        benachrichtigen(
            empfaenger,
            push_text=f"Ein Diensttausch wurde {wort}.",
            push_url="/meine-dienste",
            subject=f"Diensttausch {wort}: {dienst}",
            body="\n".join(
                [
                    f"Hallo {empfaenger.first_name},",
                    "",
                    f"der Tausch für {dienst} wurde {wort}.",
                    "Der Dienstplan bleibt unverändert.",
                    "",
                ]
            ),
            kind="swap",
        )
