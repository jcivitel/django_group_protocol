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
    Der Endpunkt sagt, welches Merkmal er braucht - hier wird gefragt.

    Als DRF-Rechteklasse und nicht als Pruefung in jedem einzelnen View:
    verteilt man so etwas von Hand, fehlt es irgendwann an einer Stelle -
    und genau die ist dann die Luecke. Hier gilt es fuer jeden Endpunkt,
    der die Klasse fuehrt, und fuer jede veraendernde Methode.

    **Bis zur Rechtematrix fragte diese Klasse an jedem Endpunkt dasselbe:
    `PROTOKOLLE` schreiben.** Das war richtig, solange eine Stufe fuer die
    ganze Anwendung galt, und wurde mit der Matrix zur Luecke: achtzehn
    Zeilen in der Oberflaeche, eine davon durchgesetzt. Wer `Dienstplan` auf
    „kein Zugriff" stellte, nahm damit einen Knopf weg und kein Recht - der
    Endpunkt liess weiter durch, weil die Person Protokolle schreiben darf.

    Jetzt nennt jeder Endpunkt sein Merkmal:

        class DutyPlanViewSet(viewsets.ModelViewSet):
            recht = rechte.DIENSTPLAN_BEARBEITEN

    `recht` gilt fuer veraendernde Methoden, `recht_lesen` fuer GET. Bleibt
    `recht_lesen` leer, darf jede angemeldete Person lesen, was ihr
    `get_queryset` uebrig laesst - das ist fuer die meisten Endpunkte die
    richtige Antwort, weil der Geltungsbereich dort und nicht hier
    entschieden wird.

    Ohne `recht` bleibt es bei `PROTOKOLLE`. Ein neuer Endpunkt ist damit
    nicht versehentlich offen, sondern versehentlich zu streng - die
    Richtung, in der ein Fehler auffaellt, ohne Schaden anzurichten.

    Eine Oberflaeche, die den Knopf versteckt, ist keine Rechtevergabe.
    """

    SAFE = ("GET", "HEAD", "OPTIONS")

    #: Unterscheidet „kein Merkmal genannt" von „ausdruecklich keines noetig".
    #: Ein Endpunkt, der eigene Daten verwaltet - die eigene Zeitbuchung, der
    #: eigene Wunsch, der eigene Antrag - setzt `recht = None`. Er prueft dann
    #: selbst, dass es die eigenen sind. Ohne diese Unterscheidung bliebe nur
    #: die Wahl zwischen einem falschen Merkmal und gar keiner Pruefung.
    _UNGESETZT = object()

    def _merkmal(self, view, lesen: bool):
        from .rechte import PROTOKOLLE

        if lesen:
            return getattr(view, "recht_lesen", None)
        wert = getattr(view, "recht", self._UNGESETZT)
        return PROTOKOLLE if wert is self._UNGESETZT else wert

    def _pruefen(self, request, view, objekt=None) -> bool:
        from .rechte import AKTION_LABEL, darf

        lesen = request.method in self.SAFE
        merkmal = self._merkmal(view, lesen)
        if merkmal is None:
            return True

        if darf(request.user, merkmal, objekt, schreiben=not lesen):
            return True

        # Die Meldung nennt das fehlende Merkmal. Sonst steht die Person vor
        # einem 403 und weiss nicht, welche Zeile der Matrix fehlt - und die
        # Verwaltung raet beim Nachbessern.
        name = AKTION_LABEL.get(merkmal, merkmal)
        was = "zum Lesen" if lesen else "zum Ändern"
        self.message = f"Dafür fehlt das Recht „{name}“ {was}."
        return False

    def has_permission(self, request, view):
        return self._pruefen(request, view)

    def has_object_permission(self, request, view, obj):
        """
        Dieselbe Frage, jetzt mit dem Gegenstand in der Hand.

        Unter `RECHTE_QUELLE=stufe` aendert das nichts - die Stufe kennt
        keinen Geltungsbereich. Unter `rollen` ist es der Unterschied
        zwischen "darf dokumentieren" und "darf hier dokumentieren".
        """
        return self._pruefen(request, view, obj)

    message = "Dafür fehlt die Berechtigung."
