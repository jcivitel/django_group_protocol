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

**Seit dem Rollenmodell fragen `is_admin`, `may_write` und `may_read_only`
nicht mehr selbst die Stufe ab, sondern `rechte.darf()`.** Damit laufen alle
Rechtefragen der Anwendung durch eine Stelle, ohne dass zweiunddreissig
Aufrufer angefasst werden mussten. Wer `RECHTE_QUELLE` umstellt, stellt
damit die ganze Anwendung um - und nicht die Haelfte davon.

Die drei Namen bleiben, weil sie an den Aufrufstellen lesbar sind. Was
dahinter entscheidet, steht in `rechte.py`.
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
    """
    Sieht und verwaltet alles - unabhaengig von Gruppenzugehoerigkeit.

    Der Import steht in der Funktion und nicht oben: `rechte` liest aus
    diesem Modul, und ein Ringschluss beim Laden waere der Preis fuer eine
    Zeile Ordnung.
    """
    from .rechte import verwaltet

    return verwaltet(user)


def may_write(user, objekt=None) -> bool:
    """
    Darf fachlich dokumentieren - Protokolle, Bewohner, Fallakte.

    `objekt` ist neu und optional. Ohne es entscheidet allein die Rolle; mit
    ihm auch, WO sie gilt. Die Aufrufer reichen es nach und nach durch.
    """
    from .rechte import schreibt_dokumentation

    return schreibt_dokumentation(user, objekt)


def may_read_only(user) -> bool:
    """Aushilfe oder Azubi: sieht die eigenen Gruppen, aendert nichts."""
    return not may_write(user)


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
        return may_write(request.user)

    def has_object_permission(self, request, view, obj):
        """
        Dieselbe Frage, jetzt mit dem Gegenstand in der Hand.

        Unter `RECHTE_QUELLE=stufe` aendert das nichts - die Stufe kennt
        keinen Geltungsbereich. Unter `rollen` ist es der Unterschied
        zwischen "darf dokumentieren" und "darf hier dokumentieren".
        """
        if request.method in self.SAFE:
            return True
        return may_write(request.user, obj)

    @property
    def message(self):
        return (
            "Als Aushilfe oder Azubi kannst du Einträge lesen, "
            "aber nicht ändern."
        )
