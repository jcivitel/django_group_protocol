"""
Trägertrennung in der Kern-App (Analyse 6.4 / P1 16).

`org`, `duty` und `care` trennen seit jeher nach Träger. Die Kern-App —
Gruppen, Bewohner, Protokolle — tat es nicht: ein Verwaltungskonto sah jede
Gruppe jedes Trägers. Für „ein Träger pro Installation" fällt das nicht auf;
als mandantenfähige Lösung war es ein offenes Tor.

Die Verbindung läuft über `Department.group`:
Gruppe → Bereich → Einrichtung → Standort → Träger.

Zwei Fälle bleiben bewusst offen und stehen deshalb auch hier als Test:
Gruppen ohne Bereichsverknüpfung und Konten ohne Personaldatensatz. Beides
schaltet STRICT_TENANCY scharf, sobald der Bestand so weit ist.
"""

from datetime import date

from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from django_grp_backend.models import Group, Protocol, Resident
from django_grp_org.models import Department, Employee, Facility, Provider, Site


def zeilen(antwort):
    daten = antwort.data
    if isinstance(daten, dict) and "results" in daten:
        return daten["results"]
    return daten


class TraegertrennungTestCase(APITestCase):
    def setUp(self):
        # Zwei Träger, je ein Standort, eine Einrichtung, ein Bereich.
        self.traeger_a = Provider.objects.create(name="Jugendhilfe A")
        self.traeger_b = Provider.objects.create(name="Jugendhilfe B")

        self.gruppe_a = Group.objects.create(
            name="Gruppe A", address="Weg 1", postalcode="42651", city="Solingen"
        )
        self.gruppe_b = Group.objects.create(
            name="Gruppe B", address="Weg 2", postalcode="42651", city="Solingen"
        )
        # Eine Gruppe ohne Bereich - der Altbestand.
        self.gruppe_ohne = Group.objects.create(
            name="Gruppe ohne Bereich",
            address="Weg 3",
            postalcode="42651",
            city="Solingen",
        )

        self._struktur(self.traeger_a, self.gruppe_a, "A")
        self._struktur(self.traeger_b, self.gruppe_b, "B")

        # Verwaltungskonto bei Träger A.
        self.verwaltung_a = User.objects.create_user(
            username="verwaltung.a", password="EinGutesPasswort1", is_staff=True
        )
        Employee.objects.create(
            provider=self.traeger_a,
            user=self.verwaltung_a,
            access_level="admin",
            first_name="Vera",
            last_name="Waltung",
            hired_on=date(2026, 1, 1),
        )

    @staticmethod
    def _struktur(provider, gruppe, kuerzel):
        standort = Site.objects.create(provider=provider, name=f"Standort {kuerzel}")
        einrichtung = Facility.objects.create(
            site=standort, name=f"Einrichtung {kuerzel}"
        )
        Department.objects.create(
            facility=einrichtung, name=f"Bereich {kuerzel}", group=gruppe
        )

    def test_verwaltung_sieht_nur_den_eigenen_traeger(self):
        self.client.force_authenticate(user=self.verwaltung_a)
        antwort = self.client.get("/api/v1/group/")

        namen = {eintrag["name"] for eintrag in zeilen(antwort)}
        self.assertIn("Gruppe A", namen)
        self.assertNotIn("Gruppe B", namen)

    def test_gruppe_ohne_bereich_bleibt_sichtbar(self):
        """
        Sonst stünde ein gewachsener Bestand nach dem Update leer da.

        Gruppen ohne Bereichsverknüpfung gehören zu keinem Träger; sie
        auszublenden hieße, sie unerreichbar zu machen.
        """
        self.client.force_authenticate(user=self.verwaltung_a)
        antwort = self.client.get("/api/v1/group/")

        namen = {eintrag["name"] for eintrag in zeilen(antwort)}
        self.assertIn("Gruppe ohne Bereich", namen)

    def test_bewohner_folgen_der_gruppengrenze(self):
        Resident.objects.create(
            first_name="Kind",
            last_name="Fremd",
            moved_in_since=date(2026, 1, 1),
            group=self.gruppe_b,
        )
        Resident.objects.create(
            first_name="Kind",
            last_name="Eigen",
            moved_in_since=date(2026, 1, 1),
            group=self.gruppe_a,
        )

        self.client.force_authenticate(user=self.verwaltung_a)
        antwort = self.client.get("/api/v1/resident/")

        namen = {eintrag["last_name"] for eintrag in zeilen(antwort)}
        self.assertIn("Eigen", namen)
        self.assertNotIn("Fremd", namen)

    def test_protokolle_folgen_der_gruppengrenze(self):
        Protocol.objects.create(
            protocol_date=date(2026, 9, 9), group=self.gruppe_b, topic="Fremd"
        )
        Protocol.objects.create(
            protocol_date=date(2026, 9, 9), group=self.gruppe_a, topic="Eigen"
        )

        self.client.force_authenticate(user=self.verwaltung_a)
        antwort = self.client.get("/api/v1/protocol/")

        themen = {eintrag["topic"] for eintrag in zeilen(antwort)}
        self.assertIn("Eigen", themen)
        self.assertNotIn("Fremd", themen)

    def test_konto_ohne_personaldatensatz_sieht_ohne_schalter_alles(self):
        """Der dokumentierte, bewusst offene Fall."""
        ohne = User.objects.create_user(
            username="ohne.personal", password="EinGutesPasswort1", is_staff=True
        )
        self.client.force_authenticate(user=ohne)
        antwort = self.client.get("/api/v1/group/")

        namen = {eintrag["name"] for eintrag in zeilen(antwort)}
        self.assertIn("Gruppe A", namen)
        self.assertIn("Gruppe B", namen)

    @override_settings(STRICT_TENANCY=True)
    def test_strict_tenancy_schliesst_konten_ohne_personaldatensatz_aus(self):
        ohne = User.objects.create_user(
            username="ohne.personal", password="EinGutesPasswort1", is_staff=True
        )
        self.client.force_authenticate(user=ohne)
        antwort = self.client.get("/api/v1/group/")

        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        self.assertEqual(len(zeilen(antwort)), 0)

    @override_settings(STRICT_TENANCY=True)
    def test_strict_tenancy_laesst_den_superuser_durch(self):
        """Sonst sperrt der Schalter die Person aus, die ihn zurücknehmen muss."""
        chef = User.objects.create_user(
            username="chef",
            password="EinGutesPasswort1",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_authenticate(user=chef)
        antwort = self.client.get("/api/v1/group/")

        self.assertGreater(len(zeilen(antwort)), 0)
