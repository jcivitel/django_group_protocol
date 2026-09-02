"""
Wer darf was.

Vorher stand das als `user.is_staff` an gut zwanzig Stellen verstreut, und
die Rechtematrix unter /admin/benutzer schrieb Zeilen, die nie jemand
gelesen hat - wer dort jemanden auf „nur lesen" stellte, glaubte es habe
gewirkt. Es hatte nicht.

Jetzt gibt es drei Stufen, und sie stehen genau hier:

    Mitarbeiter (admin)       verwaltet alles: Stammdaten, Personal, Dienst
    Fachkraft (specialist)    schreibt in den eigenen Gruppen
    Aushilfe / Azubi          liest in den eigenen Gruppen

Die Stufe steht an Employee.access_level. Dieses Modul kommt ohne Import
von django_grp_org aus - es folgt der Rueckbeziehung `user.employee` und
vermeidet damit einen Ringschluss zwischen den beiden Apps.
"""

ADMIN = "admin"
SPECIALIST = "specialist"
ASSISTANT = "assistant"

LEVEL_LABEL = {
    ADMIN: "Mitarbeiter",
    SPECIALIST: "Fachkraft",
    ASSISTANT: "Aushilfe / Azubi",
}


def employee_of(user):
    """Personaldatensatz zum Konto, falls vorhanden."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    try:
        return user.employee
    except Exception:  # noqa: BLE001 - kein Datensatz, kaputte Verknuepfung
        return None


def access_level(user) -> str | None:
    """
    Zugriffsstufe des Kontos.

    Ohne Personaldatensatz entscheidet weiterhin is_staff. Das haelt
    bestehende Konten handlungsfaehig, solange die Zusammenlegung noch
    nicht ueberall durchgelaufen ist, und macht den Superuser nie
    versehentlich aus.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None

    employee = employee_of(user)
    if employee is not None:
        return employee.access_level

    return ADMIN if user.is_staff else SPECIALIST


def is_admin(user) -> bool:
    """Sieht und verwaltet alles - unabhaengig von Gruppenzugehoerigkeit."""
    if user is not None and getattr(user, "is_superuser", False):
        return True
    return access_level(user) == ADMIN


def may_write(user) -> bool:
    """Darf in den Gruppen schreiben, in denen die Person Mitglied ist."""
    return access_level(user) in (ADMIN, SPECIALIST)


def may_read_only(user) -> bool:
    """Aushilfe oder Azubi: sieht die eigenen Gruppen, aendert nichts."""
    return access_level(user) == ASSISTANT


class WriteNeedsRole:
    """
    Schreibzugriff nur fuer Mitarbeiter und Fachkraefte.

    Als DRF-Rechteklasse und nicht als Pruefung in jedem einzelnen View:
    verteilt man so etwas von Hand, fehlt es irgendwann an einer Stelle -
    und genau die ist dann die Luecke. Hier gilt es fuer jeden Endpunkt,
    der die Klasse fuehrt, und fuer jede veraendernde Methode.

    Eine Oberflaeche, die den Knopf versteckt, ist keine Rechtevergabe.
    """

    SAFE = ("GET", "HEAD", "OPTIONS")

    def has_permission(self, request, view):
        if request.method in self.SAFE:
            return True
        return not may_read_only(request.user)

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)

    @property
    def message(self):
        return (
            "Als Aushilfe oder Azubi kannst du Einträge lesen, "
            "aber nicht ändern."
        )
