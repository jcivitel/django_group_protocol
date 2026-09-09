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
