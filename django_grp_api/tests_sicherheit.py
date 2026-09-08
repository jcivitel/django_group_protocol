"""
Regressionstests zu den Sicherheitsbefunden der Analyse.

Je ein Test pro Lücke, die geschlossen wurde - und zwar so geschrieben, dass
er die Lücke beschreibt und nicht die Umsetzung. Wer die Prüfung später
verschiebt, darf das; wer sie entfernt, soll hier scheitern.

S1  Protokoll einer fremden Gruppe anlegen
S2  Bewohner in eine fremde Gruppe anlegen oder verschieben
S3  Tagesordnungspunkt eines fremden Protokolls überschreiben
S4  Medien ohne Anmeldung und ohne Bezug zum Datensatz
S5  Bilddrehen über einen Dateipfad aus dem Rumpf
S10 Letztes Verwaltungskonto löschen
S11 E-Mail-Adresse doppelt vergeben
W8  Einheitliche Antwort auf den Schreibschutz
"""

import base64
from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from django_grp_backend.models import Group, Protocol, ProtocolItem, Resident


class ZweiGruppenMixin:
    """Zwei Gruppen, zwei Fachkräfte, die einander nichts angehen."""

    def setUp(self):
        self.eigene = Group.objects.create(
            name="Wohngruppe Nord", address="Weg 1", postalcode="42651", city="Solingen"
        )
        self.fremde = Group.objects.create(
            name="Wohngruppe Sued", address="Weg 2", postalcode="42651", city="Solingen"
        )
        self.person = User.objects.create_user(
            username="fachkraft", password="EinGutesPasswort1"
        )
        self.eigene.group_members.add(self.person)

        self.andere = User.objects.create_user(
            username="fremd", password="EinGutesPasswort1"
        )
        self.fremde.group_members.add(self.andere)

        self.client.force_authenticate(user=self.person)


class ProtokollFremdeGruppeTestCase(ZweiGruppenMixin, APITestCase):
    """S1: die Gruppennummer steht im Rumpf - geprüft wurde sie nie."""

    def test_protokoll_in_fremder_gruppe_wird_abgewiesen(self):
        antwort = self.client.post(
            "/api/v1/protocol/",
            {
                "protocol_date": "2026-09-09",
                "group": self.fremde.id,
                "topic": "Fremd",
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Protocol.objects.filter(group=self.fremde).exists())

    def test_protokoll_in_eigener_gruppe_geht(self):
        antwort = self.client.post(
            "/api/v1/protocol/",
            {"protocol_date": "2026-09-09", "group": self.eigene.id, "topic": "Eigen"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)


class BewohnerFremdeGruppeTestCase(ZweiGruppenMixin, APITestCase):
    """S2: Bewohner anlegen und verschieben, beides über den Rumpf."""

    def test_anlegen_in_fremder_gruppe_wird_abgewiesen(self):
        antwort = self.client.post(
            "/api/v1/resident/",
            {
                "first_name": "Max",
                "last_name": "Mustermann",
                "moved_in_since": "2026-01-01",
                "group": self.fremde.id,
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Resident.objects.filter(group=self.fremde).exists())

    def test_verschieben_in_fremde_gruppe_wird_abgewiesen(self):
        bewohner = Resident.objects.create(
            first_name="Lena",
            last_name="Klein",
            moved_in_since=date(2026, 1, 1),
            group=self.eigene,
        )
        antwort = self.client.patch(
            f"/api/v1/resident/{bewohner.id}/",
            {"group": self.fremde.id},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)
        bewohner.refresh_from_db()
        self.assertEqual(bewohner.group_id, self.eigene.id)


class FremdesProtokollBeschreibenTestCase(ZweiGruppenMixin, APITestCase):
    """
    S3: die gefährlichste der Lücken.

    Geprüft wurde der Zugriff auf das Protokoll aus dem Rumpf, geschrieben
    wurde danach über die Eintragsnummer allein - ohne jeden Bezug zu diesem
    Protokoll. Wer Zugriff auf irgendein Protokoll hatte, konnte Einträge
    jedes Protokolls überschreiben.
    """

    def setUp(self):
        super().setUp()
        self.eigenes = Protocol.objects.create(
            protocol_date=date(2026, 9, 9), group=self.eigene, status="draft"
        )
        self.fremdes = Protocol.objects.create(
            protocol_date=date(2026, 9, 9), group=self.fremde, status="draft"
        )
        self.fremder_eintrag = ProtocolItem.objects.create(
            protocol=self.fremdes, name="Vertraulich", position=0, value="Original"
        )

    def test_fremder_eintrag_laesst_sich_nicht_ueberschreiben(self):
        antwort = self.client.post(
            "/api/v1/item/",
            {
                # Zugriff wird für das eigene Protokoll geprüft ...
                "protocol": self.eigenes.id,
                # ... geschrieben werden soll aber im fremden.
                "id": self.fremder_eintrag.id,
                "name": "Gekapert",
                "position": 0,
                "value": "HACKED",
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_404_NOT_FOUND)
        self.fremder_eintrag.refresh_from_db()
        self.assertEqual(self.fremder_eintrag.value, "Original")

    def test_fremder_eintrag_laesst_sich_nicht_loeschen(self):
        antwort = self.client.delete(
            "/api/v1/item/", {"item_id": self.fremder_eintrag.id}, format="json"
        )
        self.assertIn(
            antwort.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )
        self.assertTrue(
            ProtocolItem.objects.filter(id=self.fremder_eintrag.id).exists()
        )

    def test_eigener_eintrag_laesst_sich_aendern(self):
        eintrag = ProtocolItem.objects.create(
            protocol=self.eigenes, name="Punkt", position=0, value="alt"
        )
        antwort = self.client.post(
            "/api/v1/item/",
            {
                "protocol": self.eigenes.id,
                "id": eintrag.id,
                "name": "Punkt",
                "position": 0,
                "value": "neu",
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        eintrag.refresh_from_db()
        self.assertEqual(eintrag.value, "neu")


class SchreibschutzTestCase(ZweiGruppenMixin, APITestCase):
    """W8: derselbe Fall, dieselbe Antwort - egal über welchen Endpunkt."""

    def setUp(self):
        super().setUp()
        self.protokoll = Protocol.objects.create(
            protocol_date=date(2026, 9, 9), group=self.eigene, status="exported"
        )

    def test_protokoll_aendern(self):
        antwort = self.client.patch(
            f"/api/v1/protocol/{self.protokoll.id}/",
            {"topic": "HACKED"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)

    def test_aufgabe_anlegen(self):
        antwort = self.client.post(
            f"/api/v1/protocol/{self.protokoll.id}/todo/",
            {"what": "Etwas", "who": "Jemand", "when": "2026-09-10T10:00:00Z"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)

    def test_eintrag_schreiben(self):
        antwort = self.client.post(
            "/api/v1/item/",
            {
                "protocol": self.protokoll.id,
                "name": "Punkt",
                "position": 0,
                "value": "HACKED",
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)

    def test_meldung_ist_ueberall_dieselbe(self):
        antworten = [
            self.client.patch(
                f"/api/v1/protocol/{self.protokoll.id}/",
                {"topic": "X"},
                format="json",
            ),
            self.client.post(
                "/api/v1/item/",
                {
                    "protocol": self.protokoll.id,
                    "name": "P",
                    "position": 0,
                    "value": "X",
                },
                format="json",
            ),
        ]
        texte = {str(antwort.data.get("detail", "")) for antwort in antworten}
        self.assertEqual(len(texte), 1, f"Uneinheitliche Meldungen: {texte}")
        self.assertIn("können", texte.pop())


class MedienTestCase(ZweiGruppenMixin, APITestCase):
    """S4: der Pfad allein berechtigt zu nichts."""

    def test_ohne_anmeldung_kein_zugriff(self):
        self.client.force_authenticate(user=None)
        antwort = self.client.get("/api/v1/media/images/beliebig.jpg")
        self.assertEqual(antwort.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unbekannte_datei_wird_nicht_ausgeliefert(self):
        antwort = self.client.get("/api/v1/media/images/gibtsnicht.jpg")
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)

    def test_pfadwechsel_nach_oben_scheitert(self):
        antwort = self.client.get("/api/v1/media/images/../../settings.py")
        self.assertIn(
            antwort.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )

    def test_absoluter_pfad_scheitert(self):
        """
        os.path.join(wurzel, "/etc/passwd") ergibt "/etc/passwd".

        Der erste Teil faellt weg - ein absoluter Pfad haette den Anker in
        MEDIA_ROOT damit einfach uebersprungen.
        """
        for pfad in ("/etc/passwd", "C:/Windows/win.ini"):
            with self.subTest(pfad=pfad):
                antwort = self.client.get(f"/api/v1/media/{pfad}")
                self.assertIn(
                    antwort.status_code,
                    (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
                )


class BilddrehenTestCase(ZweiGruppenMixin, APITestCase):
    """S5: kein Dateipfad aus dem Rumpf mehr."""

    def test_ohne_bewohnernummer_kein_vorgang(self):
        antwort = self.client.post(
            "/api/v1/rotate_image/",
            {"direction": "left", "image_url": "/media/../settings.py"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)

    def test_fremder_bewohner_wird_abgewiesen(self):
        bewohner = Resident.objects.create(
            first_name="Fremd",
            last_name="Kind",
            moved_in_since=date(2026, 1, 1),
            group=self.fremde,
        )
        antwort = self.client.post(
            f"/api/v1/resident/{bewohner.id}/rotate/",
            {"direction": "left"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_404_NOT_FOUND)


class VerwaltungskontoTestCase(APITestCase):
    """S10/S11: sich selbst aussperren und E-Mail-Adressen doppelt vergeben."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin",
            password="EinGutesPasswort1",
            email="admin@beispiel.de",
            is_staff=True,
            is_superuser=True,
        )
        self.zweiter = User.objects.create_user(
            username="zweiter", password="EinGutesPasswort1", email="zwei@beispiel.de"
        )
        self.client.force_authenticate(user=self.admin)

    def test_eigenes_konto_nicht_loeschbar(self):
        antwort = self.client.delete(f"/api/v1/admin/users/{self.admin.id}/")
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(User.objects.filter(id=self.admin.id).exists())

    def test_letztes_verwaltungskonto_nicht_stilllegbar(self):
        zweiter_admin = User.objects.create_user(
            username="admin2",
            password="EinGutesPasswort1",
            is_staff=True,
            is_superuser=True,
        )
        # Noch zwei Superuser: das geht.
        antwort = self.client.put(
            f"/api/v1/admin/users/{zweiter_admin.id}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)

        # Jetzt ist das eigene Konto das letzte aktive.
        antwort = self.client.put(
            f"/api/v1/admin/users/{self.admin.id}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)

    def test_email_nicht_doppelt_vergebbar(self):
        antwort = self.client.put(
            f"/api/v1/admin/users/{self.zweiter.id}/",
            {"email": "admin@beispiel.de"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)
        self.zweiter.refresh_from_db()
        self.assertEqual(self.zweiter.email, "zwei@beispiel.de")

    def test_eigenes_profil_email_nicht_doppelt(self):
        self.client.force_authenticate(user=self.zweiter)
        antwort = self.client.put(
            "/api/v1/user/profile/", {"email": "admin@beispiel.de"}, format="json"
        )
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)


class AnmeldebremseTestCase(APITestCase):
    """
    S8: Passwoerter durchprobieren muss teuer werden.

    Vorher nahm jeder Endpunkt zusaetzlich "Authorization: Basic" entgegen und
    der Login hatte keinerlei Bremse - eine Passwortliste liess sich in einem
    Rutsch durchspielen, ohne dass es irgendwo aufgefallen waere.
    """

    def setUp(self):
        cache.clear()
        User.objects.create_user(username="ziel", password="EinGutesPasswort1")

    def tearDown(self):
        cache.clear()

    def test_zu_viele_versuche_werden_abgewiesen(self):
        # Die Rate direkt setzen und nicht ueber override_settings:
        # ScopedRateThrottle liest THROTTLE_RATES als Klassenattribut, das
        # zur Importzeit gebunden wird - eine Einstellungsaenderung im Test
        # kaeme dort nie an.
        with patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"login": "3/min"}):
            for versuch in range(3):
                antwort = self.client.post(
                    "/api/v1/auth/login/",
                    {"username": "ziel", "password": "falsch"},
                    format="json",
                )
                self.assertEqual(
                    antwort.status_code,
                    status.HTTP_401_UNAUTHORIZED,
                    f"Versuch {versuch + 1} sollte durchgelassen werden",
                )

            antwort = self.client.post(
                "/api/v1/auth/login/",
                {"username": "ziel", "password": "falsch"},
                format="json",
            )
            self.assertEqual(antwort.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_bremse_ist_im_betrieb_gesetzt(self):
        """Ohne Rate ist die Klasse am Login wirkungslos - also festhalten."""
        self.assertIn("login", SimpleRateThrottle.THROTTLE_RATES)
        self.assertTrue(SimpleRateThrottle.THROTTLE_RATES["login"])

    def test_basic_auth_ist_aus(self):
        """
        Ohne BasicAuthentication nimmt die API keine Zugangsdaten im Kopf an.

        Der Test prueft die Wirkung, nicht die Einstellung: eine gueltige
        Kombination aus Benutzername und Passwort darf keinen Zugriff
        verschaffen.
        """
        zugang = base64.b64encode(b"ziel:EinGutesPasswort1").decode("ascii")
        antwort = self.client.get(
            "/api/v1/resident/", HTTP_AUTHORIZATION=f"Basic {zugang}"
        )
        self.assertEqual(antwort.status_code, status.HTTP_401_UNAUTHORIZED)
