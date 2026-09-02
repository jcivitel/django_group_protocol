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


# Dienstarten. Ohne mindestens eine erzeugt ein Dienstplan gar keine
# Dienste - das Raster bleibt leer und die Dienstplanung wirkt kaputt. Es
# gab bis hierher keine Oberflaeche, um welche anzulegen; die Vorgaben sind
# deshalb nicht nur Bequemlichkeit, sondern der Unterschied zwischen einem
# nutzbaren und einem toten Modul.
#
# Zeiten nach dem ueblichen Schichtbild einer Wohngruppe. Farben aus der
# Palette der Anwendung, damit das Raster von Anfang an lesbar ist.
DEFAULT_SHIFT_TYPES = [
    # Kuerzel, Name, Beginn, Ende, Pause, Farbe, Nacht, Bereitschaft, Fachkraft
    ("F", "Frühdienst", "06:30", "14:30", 30, "#abc270", False, False, True),
    ("Z", "Zwischendienst", "09:00", "17:00", 30, "#fec868", False, False, True),
    ("S", "Spätdienst", "13:30", "21:30", 30, "#fda769", False, False, True),
    ("N", "Nachtbereitschaft", "21:00", "07:00", 0, "#473c33", True, True, False),
]


def ensure_shift_types(ShiftType, provider) -> int:
    """
    Legt fehlende Dienstarten für einen Träger an.

    Bewusst keine Dienstart "Frei": eine Zelle ohne Dienst heisst bereits
    "nicht eingeteilt", und eine Dienstart von 00:00 bis 00:00 rechnet
    duration_hours als Nachtdienst ueber Mitternacht - also 24 Stunden
    Arbeitszeit fuer einen freien Tag.
    """
    created = 0
    for (
        short_code,
        name,
        start,
        end,
        pause,
        color,
        is_night,
        is_on_call,
        counts,
    ) in DEFAULT_SHIFT_TYPES:
        _, made = ShiftType.objects.get_or_create(
            provider=provider,
            short_code=short_code,
            defaults={
                "name": name,
                "start_time": start,
                "end_time": end,
                "break_minutes": pause,
                "color": color,
                "is_night": is_night,
                "is_on_call": is_on_call,
                "counts_specialist": counts,
            },
        )
        created += int(made)
    return created


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
