"""
Stammdaten, die es beim ersten Start schon geben soll.

Eine leere Liste ist eine Huerde: wer eine Qualifikation an einer Person
eintragen will, muss sie erst anlegen, und wer nicht weiss, welche
Bezeichnungen ueblich sind, laesst es. Deshalb ein Satz Vorgaben, der den
Alltag in der Jugendhilfe abdeckt - aendern und loeschen laesst sich alles
in der Oberflaeche.

Zwei Aufrufer teilen sich diese Datei: die Migration fuer bestehende
Installationen und der Einrichtungsassistent fuer neue. Beide legen nur an,
was noch fehlt - eine umbenannte Vorgabe kommt nicht als Dublette zurueck.
"""

# is_specialist entscheidet, ob eine Person auf die Fachkraftquote einzahlt.
# Das ist die einzige Angabe hier, die die Dienstplanung tatsaechlich rechnet.
DEFAULT_QUALIFICATIONS = [
    ("Erzieherin / Erzieher", True, "Staatlich anerkannt"),
    ("Sozialpädagogin / Sozialpädagoge", True, "Bachelor oder Diplom"),
    ("Sozialarbeiterin / Sozialarbeiter", True, "Bachelor oder Diplom"),
    ("Heilerziehungspflegerin / Heilerziehungspfleger", True, ""),
    ("Kindheitspädagogin / Kindheitspädagoge", True, ""),
    ("Psychologin / Psychologe", True, ""),
    ("Heilpädagogin / Heilpädagoge", True, ""),
    ("Kinderpflegerin / Kinderpfleger", False, "Assistenz, keine Fachkraft"),
    ("Anerkennungspraktikum", False, "Im Anerkennungsjahr"),
    ("Hilfskraft", False, "Ohne pädagogische Ausbildung"),
    ("Ersthelferin / Ersthelfer", False, "Läuft ab, alle zwei Jahre auffrischen"),
    ("Deeskalationstraining", False, ""),
    ("Medikamentengabe", False, "Einweisung nach Landesrecht"),
]

# Wochenstunden nach TVöD SuE. Wer ein anderes Tarifwerk fährt, ändert die
# Zahlen in der Oberfläche - deshalb stehen sie hier und nicht im Code.
DEFAULT_WORKTIME_MODELS = [
    ("Vollzeit", "39.00", "5.0", 30, ""),
    ("Teilzeit 75 %", "29.25", "5.0", 30, ""),
    ("Teilzeit 50 %", "19.50", "3.0", 30, "Urlaub anteilig prüfen"),
    ("Teilzeit 30 %", "11.70", "2.0", 30, "Urlaub anteilig prüfen"),
    ("Geringfügige Beschäftigung", "10.00", "2.0", 30, "Urlaub anteilig prüfen"),
]


def ensure_qualifications(Qualification) -> int:
    """
    Legt fehlende Qualifikationen an. Gibt zurueck, wie viele dazukamen.

    Das Modell kommt als Argument, damit die Migration ihre historische
    Fassung uebergeben kann - die kennt nur die Felder, die es zum Zeitpunkt
    der Migration gab.
    """
    created = 0
    for name, is_specialist, description in DEFAULT_QUALIFICATIONS:
        _, made = Qualification.objects.get_or_create(
            name=name,
            defaults={"is_specialist": is_specialist, "description": description},
        )
        created += int(made)
    return created


def ensure_worktime_models(WorkTimeModel, provider) -> int:
    """Legt fehlende Arbeitszeitmodelle für einen Träger an."""
    created = 0
    for name, weekly, days, vacation, notes in DEFAULT_WORKTIME_MODELS:
        _, made = WorkTimeModel.objects.get_or_create(
            provider=provider,
            name=name,
            defaults={
                "weekly_hours": weekly,
                "days_per_week": days,
                "vacation_days": vacation,
                "notes": notes,
            },
        )
        created += int(made)
    return created
