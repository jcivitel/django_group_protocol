"""
Tests der Regelprüfung für Dienstpläne.

Schwerpunkt: nach spätestens sechs Tagen muss ein freier Tag kommen. Die
Grenze stand auf sieben und die Prüfung schlug erst darüber an — eine
durchgearbeitete Woche, Montag bis Sonntag, ging damit glatt durch. Der
Automat kannte die Regel überhaupt nicht.

Rechtlicher Hintergrund: § 9 ArbZG schreibt die Sonntagsruhe vor.
Einrichtungen zur Betreuung von Personen dürfen sonntags arbeiten lassen
(§ 10 Abs. 1 Nr. 3), müssen dafür aber einen Ersatzruhetag geben
(§ 11 Abs. 3). Die Woche hat damit sechs Arbeitstage.
"""

from datetime import date, time, timedelta

from django.test import TestCase

from django_grp_backend.models import Group
from django_grp_duty.autofill import autofill_plan
from django_grp_duty.models import DutyPlan, Shift, ShiftType
from django_grp_duty.rules import (
    MAX_CONSECUTIVE_DAYS,
    check_plan,
    serie_um,
)
from django_grp_org.models import (
    Department,
    Employee,
    Facility,
    Provider,
    Site,
)


class SerieUmTestCase(TestCase):
    """Die Hilfsfunktion, auf der beide Seiten aufsetzen."""

    def test_einzelner_tag(self):
        self.assertEqual(serie_um(set(), date(2026, 9, 9)), 1)

    def test_zaehlt_nach_hinten(self):
        tage = {date(2026, 9, 7), date(2026, 9, 8)}
        self.assertEqual(serie_um(tage, date(2026, 9, 9)), 3)

    def test_zaehlt_nach_vorn(self):
        tage = {date(2026, 9, 10), date(2026, 9, 11)}
        self.assertEqual(serie_um(tage, date(2026, 9, 9)), 3)

    def test_verbindet_zwei_serien(self):
        """
        Der Fall, der sonst durchfällt.

        Für sich betrachtet ist der 9. ein einzelner Tag. Er schließt aber
        eine Lücke zwischen zwei Serien und macht aus ihnen eine lange.
        """
        tage = {
            date(2026, 9, 6),
            date(2026, 9, 7),
            date(2026, 9, 8),
            date(2026, 9, 10),
            date(2026, 9, 11),
            date(2026, 9, 12),
        }
        self.assertEqual(serie_um(tage, date(2026, 9, 9)), 7)

    def test_luecke_bleibt_luecke(self):
        tage = {date(2026, 9, 6), date(2026, 9, 11)}
        self.assertEqual(serie_um(tage, date(2026, 9, 8)), 1)


class DienstplanMixin:
    """Ein Bereich, eine Dienstart, eine Person."""

    def aufbauen(self):
        self.traeger = Provider.objects.create(name="Jugendhilfe Musterstadt")
        standort = Site.objects.create(provider=self.traeger, name="Haus Lindenweg")
        einrichtung = Facility.objects.create(site=standort, name="Haus Lindenweg")
        self.gruppe = Group.objects.create(
            name="Gruppe Lindenweg",
            address="Weg 1",
            postalcode="42651",
            city="Solingen",
        )
        self.bereich = Department.objects.create(
            facility=einrichtung,
            name="Wohngruppe",
            group=self.gruppe,
            minimum_staff=1,
            specialist_ratio=0,
        )
        self.dienstart = ShiftType.objects.create(
            provider=self.traeger,
            name="Frühdienst",
            short_code="F",
            start_time=time(6, 0),
            end_time=time(14, 0),
        )
        self.person = Employee.objects.create(
            provider=self.traeger,
            first_name="Miriam",
            last_name="Kern",
            hired_on=date(2026, 1, 1),
        )

    def plan(self, jahr, monat):
        return DutyPlan.objects.create(
            department=self.bereich, year=jahr, month=monat
        )

    def dienste(self, plan, start, tage, person=None):
        """Legt `tage` aufeinanderfolgende Dienste ab `start` an."""
        for versatz in range(tage):
            Shift.objects.create(
                plan=plan,
                date=start + timedelta(days=versatz),
                shift_type=self.dienstart,
                employee=person if person is not None else self.person,
            )


class SerienpruefungTestCase(DienstplanMixin, TestCase):
    def setUp(self):
        self.aufbauen()

    def verstoesse(self, plan):
        return [
            verstoss
            for verstoss in check_plan(plan)
            if verstoss.rule == "consecutive_days"
        ]

    def test_sechs_tage_sind_erlaubt(self):
        plan = self.plan(2026, 9)
        self.dienste(plan, date(2026, 9, 7), 6)
        self.assertEqual(self.verstoesse(plan), [])

    def test_sieben_tage_am_stueck_werden_gemeldet(self):
        """
        Der eigentliche Befund.

        Montag bis Sonntag durchgearbeitet - das ging vorher durch, weil die
        Grenze auf sieben stand und die Prüfung erst darüber anschlug.
        """
        plan = self.plan(2026, 9)
        self.dienste(plan, date(2026, 9, 7), 7)

        verstoesse = self.verstoesse(plan)
        self.assertEqual(len(verstoesse), 1)
        self.assertEqual(verstoesse[0].severity, "error")
        self.assertIn("Kern", verstoesse[0].message)
        self.assertIn("freier Tag", verstoesse[0].message)

    def test_ein_freier_tag_setzt_die_serie_zurueck(self):
        plan = self.plan(2026, 9)
        self.dienste(plan, date(2026, 9, 1), 5)
        # Der 6. bleibt frei.
        self.dienste(plan, date(2026, 9, 7), 5)
        self.assertEqual(self.verstoesse(plan), [])

    def test_serie_ueber_den_monatswechsel(self):
        """
        Zwei Pläne, eine Serie.

        Wer vom 27. bis 31. Januar durcharbeitet und am 1. Februar
        weitermacht, steht in zwei Plänen mit je einer kurzen, unauffälligen
        Serie — und in Wahrheit seit acht Tagen im Dienst. Ohne den Blick
        über den Rand endet jede Prüfung am Monatsersten.
        """
        januar = self.plan(2026, 1)
        februar = self.plan(2026, 2)
        self.dienste(januar, date(2026, 1, 27), 5)  # 27. bis 31.
        self.dienste(februar, date(2026, 2, 1), 3)  # 1. bis 3.

        self.assertEqual(len(self.verstoesse(februar)), 1)

    def test_andere_person_bleibt_unberuehrt(self):
        zweite = Employee.objects.create(
            provider=self.traeger,
            first_name="Jonas",
            last_name="Brand",
            hired_on=date(2026, 1, 1),
        )
        plan = self.plan(2026, 9)
        self.dienste(plan, date(2026, 9, 7), 4)
        self.dienste(plan, date(2026, 9, 11), 4, person=zweite)
        self.assertEqual(self.verstoesse(plan), [])


class AutofillSerieTestCase(DienstplanMixin, TestCase):
    """
    Der Automat darf die Regel nicht erst hinterher verletzen.

    Er kannte sie überhaupt nicht: geprüft wurden Ruhezeit und
    Doppelbelegung, und eine Person ließ sich ohne Weiteres sieben Tage am
    Stück eintragen. Die Regelprüfung meldete das danach — hinterher ist der
    falsche Zeitpunkt, wenn ein Automat den Plan gebaut hat.
    """

    def setUp(self):
        self.aufbauen()
        self.gruppe.group_members.add(
            # Der Automat sucht sein Personal über Stelle oder Gruppe.
            self._konto()
        )

    def _konto(self):
        from django.contrib.auth.models import User

        konto = User.objects.create_user(
            username="m.kern", password="EinGutesPasswort1"
        )
        self.person.user = konto
        self.person.save(update_fields=["user"])
        return konto

    def test_automat_teilt_keine_sieben_tage_am_stueck_ein(self):
        plan = self.plan(2026, 9)
        for versatz in range(8):
            Shift.objects.create(
                plan=plan,
                date=date(2026, 9, 7) + timedelta(days=versatz),
                shift_type=self.dienstart,
            )

        autofill_plan(plan)

        tage = sorted(
            plan.shifts.filter(employee=self.person).values_list("date", flat=True)
        )
        # Sonst liefe der Test leer durch: ohne eine einzige Zuteilung ist
        # jede Serie kurz genug, und der Test bewiese nichts.
        #
        # Erwartet werden sieben Zuteilungen aus acht Diensten: sechs Tage am
        # Stück, dann bleibt der siebte frei, und danach geht es weiter. Der
        # Automat hört also nicht auf, er legt einen Ruhetag ein - genau das
        # soll er tun.
        self.assertEqual(len(tage), 7)

        laengste = 1
        aktuell = 1
        for vorher, jetzt in zip(tage, tage[1:]):
            aktuell = aktuell + 1 if (jetzt - vorher).days == 1 else 1
            laengste = max(laengste, aktuell)

        self.assertLessEqual(laengste, MAX_CONSECUTIVE_DAYS)

    def test_automat_hinterlaesst_keinen_verstoss(self):
        plan = self.plan(2026, 9)
        for versatz in range(10):
            Shift.objects.create(
                plan=plan,
                date=date(2026, 9, 7) + timedelta(days=versatz),
                shift_type=self.dienstart,
            )

        autofill_plan(plan)

        self.assertTrue(
            plan.shifts.filter(employee=self.person).exists(),
            "Ohne Zuteilung beweist der Test nichts",
        )

        serien = [
            verstoss
            for verstoss in check_plan(plan)
            if verstoss.rule == "consecutive_days"
        ]
        self.assertEqual(serien, [])
