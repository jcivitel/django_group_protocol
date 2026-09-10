from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase

from django_grp_org.models import Employee, Provider
from django_grp_org.personal import personaldatensatz_anlegen


class PersonaldatensatzTest(TestCase):
    """
    Ein Konto ohne Personaldatensatz ist ein halbes Konto: kein Foto, kein
    Dienstplan, keine Zeitbuchung. Beide Wege, auf denen das erste Konto
    entsteht, legen ihn jetzt mit an.
    """

    def setUp(self):
        self.user = User.objects.create_superuser(
            username="chefin", email="chefin@beispiel.de", password="x" * 12,
            first_name="Andrea", last_name="Kern",
        )

    def test_ohne_traeger_passiert_nichts(self):
        """
        Auf einer leeren Datenbank gibt es noch keine Organisation. Das ist
        kein Fehler, sondern die Reihenfolge — und darf nicht scheitern.
        """
        Provider.objects.all().delete()

        self.assertIsNone(personaldatensatz_anlegen(self.user))

    def test_mit_traeger_entsteht_der_datensatz(self):
        provider = Provider.objects.create(name="Träger")

        employee = personaldatensatz_anlegen(self.user)

        self.assertIsNotNone(employee)
        self.assertEqual(employee.user, self.user)
        self.assertEqual(employee.provider, provider)
        self.assertEqual(employee.first_name, "Andrea")
        self.assertEqual(employee.last_name, "Kern")
        # Wer ein System einrichtet, verwaltet es auch.
        self.assertEqual(employee.access_level, "admin")

    def test_zweimal_aufrufen_legt_nichts_doppelt_an(self):
        Provider.objects.create(name="Träger")

        erst = personaldatensatz_anlegen(self.user)
        zweit = personaldatensatz_anlegen(self.user)

        self.assertEqual(erst.pk, zweit.pk)
        self.assertEqual(Employee.objects.filter(user=self.user).count(), 1)

    def test_ohne_namen_am_konto_bleibt_der_datensatz_auffindbar(self):
        """Sonst stuende dort eine leere Zeile in der Personalliste."""
        Provider.objects.create(name="Träger")
        ohne_namen = User.objects.create_superuser(
            username="admin2", email="a2@beispiel.de", password="x" * 12
        )

        employee = personaldatensatz_anlegen(ohne_namen)

        self.assertEqual(employee.first_name, "admin2")
        self.assertTrue(employee.last_name)


class EntgeltTestCase(TestCase):
    """
    Entgeltgruppen, Stufen und Zuschlagssaetze.

    Der Kern ist die Frage, wann die Abrechnung einen Betrag ausweist und
    wann nur Stunden. Sie soll lieber schweigen als raten - deshalb prueft
    jeder Test hier eine Stelle, an der ein Stueck fehlt.
    """

    def setUp(self):
        from decimal import Decimal

        from django_grp_org.entgelt import ensure_pay_grades, ensure_surcharges
        from django_grp_org.models import (
            Contract,
            Employee,
            PayGrade,
            PayGradeStep,
            Provider,
            WorkTimeModel,
        )

        self.Decimal = Decimal
        self.PayGradeStep = PayGradeStep

        self.traeger = Provider.objects.create(name="Testträger")
        ensure_pay_grades(self.traeger)
        ensure_surcharges(self.traeger)

        self.modell = WorkTimeModel.objects.create(
            provider=self.traeger,
            name="Vollzeit",
            weekly_hours=Decimal("39.00"),
            days_per_week=Decimal("5.0"),
            vacation_days=30,
        )
        self.person = Employee.objects.create(
            provider=self.traeger,
            first_name="Test",
            last_name="Person",
            hired_on=date(2024, 1, 1),
            work_time_model=self.modell,
        )
        self.gruppe = PayGrade.objects.get(provider=self.traeger, name="S 8b")
        self.vertrag = Contract.objects.create(
            employee=self.person,
            kind="permanent",
            weekly_hours=Decimal("39.00"),
            valid_from=date(2024, 1, 1),
            pay_grade_ref=self.gruppe,
            pay_step=3,
        )

    def test_vorgaben_sind_da(self):
        from django_grp_org.models import PayGrade, SurchargeRate

        self.assertEqual(PayGrade.objects.filter(provider=self.traeger).count(), 9)
        self.assertEqual(
            SurchargeRate.objects.filter(provider=self.traeger).count(), 4
        )

    def test_ohne_betrag_kein_stundenentgelt(self):
        """
        Die Gruppe ist zugeordnet, die Stufe steht - nur der Betrag fehlt.
        Dann gibt es keinen Stundensatz, und die Abrechnung bleibt bei den
        Stunden.
        """
        from django_grp_duty.payroll import _stundenentgelt

        self.assertIsNone(_stundenentgelt(self.person, date(2026, 1, 1)))

    def test_mit_betrag_rechnet_es(self):
        from django_grp_duty.payroll import _stundenentgelt

        self.PayGradeStep.objects.create(
            pay_grade=self.gruppe,
            step=3,
            monthly_amount=self.Decimal("3600.00"),
            valid_from=date(2025, 1, 1),
        )
        satz = _stundenentgelt(self.person, date(2026, 1, 1))
        # 3600 / (39 * 4,348) = 21,2299...
        self.assertIsNotNone(satz)
        self.assertAlmostEqual(float(satz), 21.23, places=1)

    def test_juengste_fassung_gewinnt(self):
        """
        Nach einer Tarifrunde stehen zwei Zeilen. Gerechnet wird mit der,
        die am Stichtag galt - nicht mit der neuesten und nicht mit der
        ersten.
        """
        for jahr, betrag in ((2025, "3600.00"), (2026, "3800.00")):
            self.PayGradeStep.objects.create(
                pay_grade=self.gruppe,
                step=3,
                monthly_amount=self.Decimal(betrag),
                valid_from=date(jahr, 4, 1),
            )
        self.assertEqual(
            self.gruppe.betrag_am(3, date(2026, 3, 31)), self.Decimal("3600.00")
        )
        self.assertEqual(
            self.gruppe.betrag_am(3, date(2026, 4, 1)), self.Decimal("3800.00")
        )

    def test_ohne_stufe_kein_betrag(self):
        """Eine Gruppe ohne Stufe sagt nichts ueber das Entgelt."""
        from django_grp_duty.payroll import _stundenentgelt

        self.PayGradeStep.objects.create(
            pay_grade=self.gruppe,
            step=3,
            monthly_amount=self.Decimal("3600.00"),
            valid_from=date(2025, 1, 1),
        )
        self.vertrag.pay_step = None
        self.vertrag.save(update_fields=["pay_step"])
        self.assertIsNone(_stundenentgelt(self.person, date(2026, 1, 1)))
