"""
Entgeltgruppen, Stufen und Zuschlagssätze (Roadmap Phase 4).

Bisher stand die Entgeltgruppe als freier Text am Vertrag. Damit ließ sich
nichts prüfen und nichts rechnen: „S 8b", „S8b" und „S 8 b" waren drei
verschiedene Gruppen, und die Lohnübergabe konnte nur Stunden liefern.

Was hier steht und was nicht, ist eine Entscheidung und keine Nachlässigkeit:

- **Die Gruppennamen kommen ab Werk.** Die S-Gruppen des TVöD SuE ändern
  sich praktisch nie, und eine leere Liste wäre eine Hürde am ersten Tag.
- **Die Beträge nicht.** Eine Entgelttabelle gilt ein Jahr und wird neu
  verhandelt. Eine Zahl im Quelltext wäre nach der nächsten Tarifrunde
  falsch, und zwar unbemerkt. Sie werden hier gepflegt, vom Träger.
- **Die Zuschlagssätze kommen als Vorschlag.** Sie sind stabiler als die
  Beträge, aber je Tarifwerk verschieden. Wer AVR oder einen Haustarif
  fährt, ändert sie — der Hinweis dazu steht am Feld.

Solange an einer Gruppe kein Betrag steht, verhält sich die Lohnübergabe wie
zuvor und liefert nur Stunden. Eine halbe Rechnung wäre schlimmer als keine.
"""

from decimal import Decimal

from django.db import models

from .models import Provider, fk

# Die Entgeltgruppen des TVöD SuE, wie sie in der Jugendhilfe vorkommen.
# Ohne Betrag - siehe Modulkommentar.
DEFAULT_PAY_GRADES = [
    ("S 2", "Beschäftigte in der Tätigkeit von Kinderpfleger:innen"),
    ("S 3", "Kinderpfleger:innen mit staatlicher Anerkennung"),
    ("S 4", "Kinderpfleger:innen mit besonders schwierigen Tätigkeiten"),
    ("S 8a", "Erzieher:innen"),
    ("S 8b", "Erzieher:innen mit besonders schwierigen Tätigkeiten"),
    ("S 11b", "Sozialarbeiter:innen und Sozialpädagog:innen"),
    ("S 12", "Sozialarbeiter:innen mit besonders schwierigen Tätigkeiten"),
    ("S 15", "Leitung einer Einrichtung"),
    ("S 17", "Leitung mehrerer Einrichtungen"),
]

# Vorschlagswerte nach TVöD § 8. Sie sind zu prüfen, nicht zu glauben:
# Feiertagsarbeit steht dort mit 35 % nur bei Freizeitausgleich, ohne
# Ausgleich deutlich höher. Genau deshalb sind sie pflegbar.
DEFAULT_SURCHARGES = [
    ("night", Decimal("20.00"), "TVöD § 8: Nachtarbeit zwischen 21 und 6 Uhr"),
    ("saturday", Decimal("20.00"), "TVöD § 8: Samstag zwischen 13 und 21 Uhr"),
    ("sunday", Decimal("25.00"), "TVöD § 8: Sonntagsarbeit"),
    ("holiday", Decimal("35.00"), "TVöD § 8: mit Freizeitausgleich; ohne Ausgleich prüfen"),
]


class PayGrade(models.Model):
    """
    Eine Entgeltgruppe des Trägers.

    Sie trägt keinen Betrag. Der hängt an der Stufe, und die hängt am Jahr.
    """

    provider = fk(Provider, related_name="pay_grades", verbose_name="Träger")
    name = models.CharField(max_length=30, verbose_name="Bezeichnung")
    description = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="Beschreibung",
        help_text="Wofür die Gruppe gilt",
    )
    position = models.PositiveIntegerField(
        default=0,
        verbose_name="Reihenfolge",
        help_text="Kleinere Zahl steht weiter oben",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Aktiv",
        help_text="Abgeschaltet verschwindet sie aus der Auswahl, bestehende Verträge behalten sie",
    )

    class Meta:
        ordering = ["position", "name"]
        unique_together = [("provider", "name")]
        verbose_name = "Entgeltgruppe"
        verbose_name_plural = "Entgeltgruppen"

    def __str__(self) -> str:
        return self.name

    def betrag_am(self, stufe: int, stichtag) -> Decimal | None:
        """
        Monatsentgelt einer Stufe zum Stichtag.

        Die jüngste Fassung, die am Stichtag schon galt. Gibt es keine,
        kommt None zurück — und die Lohnübergabe liefert dann Stunden ohne
        Betrag, statt mit einem veralteten zu rechnen.
        """
        eintrag = (
            self.steps.filter(step=stufe, valid_from__lte=stichtag)
            .order_by("-valid_from")
            .first()
        )
        return eintrag.monthly_amount if eintrag else None


class PayGradeStep(models.Model):
    """
    Eine Stufe einer Entgeltgruppe, gültig ab einem Datum.

    Mehrere Zeilen je Stufe sind der Normalfall: nach jeder Tarifrunde kommt
    eine dazu. Die alte bleibt stehen, damit eine Abrechnung aus dem Vorjahr
    nachvollziehbar bleibt — das ist derselbe Gedanke wie beim Hilfeplan.
    """

    pay_grade = fk(PayGrade, related_name="steps", verbose_name="Entgeltgruppe")
    step = models.PositiveSmallIntegerField(verbose_name="Stufe")
    monthly_amount = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        verbose_name="Monatsentgelt",
        help_text="Bei Vollzeit, in Euro",
    )
    valid_from = models.DateField(verbose_name="Gültig ab")

    class Meta:
        ordering = ["pay_grade", "step", "-valid_from"]
        unique_together = [("pay_grade", "step", "valid_from")]
        verbose_name = "Entgeltstufe"
        verbose_name_plural = "Entgeltstufen"

    def __str__(self) -> str:
        return f"{self.pay_grade.name} Stufe {self.step} ab {self.valid_from}"


class SurchargeRate(models.Model):
    """
    Ein Zuschlagssatz des Trägers.

    Die Anwendung zählt die Stunden ohnehin schon — Nacht, Sonntag und
    Feiertag stehen als eigene Lohnarten in der Übergabe. Mit einem Satz
    daneben kann sie daraus auch einen Betrag machen.

    Ohne Satz bleibt es bei den Stunden. Das ist der Zustand von vorher und
    weiterhin ein gültiger: viele Häuser rechnen die Zuschläge im
    Lohnprogramm und wollen sie hier gar nicht.
    """

    KIND_CHOICES = [
        ("night", "Nachtarbeit"),
        ("saturday", "Samstagsarbeit"),
        ("sunday", "Sonntagsarbeit"),
        ("holiday", "Feiertagsarbeit"),
    ]

    provider = fk(Provider, related_name="surcharge_rates", verbose_name="Träger")
    kind = models.CharField(
        max_length=20, choices=KIND_CHOICES, verbose_name="Art"
    )
    percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        verbose_name="Zuschlag in Prozent",
        help_text="0 lassen, wenn die Lohnabrechnung den Satz selbst kennt",
    )
    note = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="Anmerkung",
        help_text="Welches Tarifwerk, welche Fundstelle",
    )

    class Meta:
        ordering = ["kind"]
        unique_together = [("provider", "kind")]
        verbose_name = "Zuschlagssatz"
        verbose_name_plural = "Zuschlagssätze"

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.percent} %"


def ensure_pay_grades(provider) -> int:
    """Legt die fehlenden Entgeltgruppen eines Trägers an."""
    created = 0
    for platz, (name, beschreibung) in enumerate(DEFAULT_PAY_GRADES):
        _, made = PayGrade.objects.get_or_create(
            provider=provider,
            name=name,
            defaults={"description": beschreibung, "position": platz},
        )
        created += int(made)
    return created


def ensure_surcharges(provider) -> int:
    """Legt die fehlenden Zuschlagssätze eines Trägers an."""
    created = 0
    for kind, percent, note in DEFAULT_SURCHARGES:
        _, made = SurchargeRate.objects.get_or_create(
            provider=provider,
            kind=kind,
            defaults={"percent": percent, "note": note},
        )
        created += int(made)
    return created
