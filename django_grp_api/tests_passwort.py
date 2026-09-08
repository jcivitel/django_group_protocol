"""
Tests zum Zurücksetzen des Passworts (Analyse P0 8).

Der Ablauf muss drei Dinge aushalten, und genau die stehen hier:
keine Auskunft über vorhandene Adressen, ein Link der abläuft und nur einmal
gilt, und eine Sitzung die dabei endet.
"""

from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from django_grp_mail.models import MailMessage


class PasswortVergessenTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        self.person = User.objects.create_user(
            username="fachkraft",
            email="Fach.Kraft@Beispiel.de",
            password="EinGutesPasswort1",
        )

    def tearDown(self):
        cache.clear()

    def anfordern(self, adresse):
        return self.client.post(
            "/api/v1/auth/passwort-vergessen/", {"email": adresse}, format="json"
        )

    def test_bekannte_adresse_bekommt_eine_mail(self):
        antwort = self.anfordern("fach.kraft@beispiel.de")
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)

        mail = MailMessage.objects.filter(kind="password_reset").first()
        self.assertIsNotNone(mail)
        # Django kleinschreibt beim Anlegen die Domain (normalize_email),
        # der lokale Teil bleibt wie eingegeben.
        self.assertEqual(mail.to_address, self.person.email)
        self.assertIn("/passwort-neu?uid=", mail.body)

    def test_unbekannte_adresse_sieht_genauso_aus(self):
        """
        Sonst wird aus "Passwort vergessen" ein Verzeichnis der Beschäftigten.
        """
        bekannt = self.anfordern("fach.kraft@beispiel.de")
        unbekannt = self.anfordern("gibtsnicht@beispiel.de")

        self.assertEqual(bekannt.status_code, unbekannt.status_code)
        self.assertEqual(bekannt.data, unbekannt.data)
        self.assertEqual(MailMessage.objects.filter(kind="password_reset").count(), 1)

    def test_ohne_adresse_ein_fehler(self):
        antwort = self.anfordern("")
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)


class PasswortNeuTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        self.person = User.objects.create_user(
            username="fachkraft",
            email="fach.kraft@beispiel.de",
            password="EinGutesPasswort1",
        )
        self.uid = urlsafe_base64_encode(force_bytes(self.person.pk))
        self.token = default_token_generator.make_token(self.person)

    def tearDown(self):
        cache.clear()

    def setzen(self, passwort, *, uid=None, token=None):
        return self.client.post(
            "/api/v1/auth/passwort-neu/",
            {
                "uid": uid if uid is not None else self.uid,
                "token": token if token is not None else self.token,
                "password": passwort,
            },
            format="json",
        )

    def test_gueltiger_link_setzt_das_passwort(self):
        antwort = self.setzen("EinAnderesPasswort9")
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)

        self.person.refresh_from_db()
        self.assertTrue(self.person.check_password("EinAnderesPasswort9"))

    def test_link_gilt_nur_einmal(self):
        self.assertEqual(self.setzen("EinAnderesPasswort9").status_code, 200)
        # Derselbe Token ein zweites Mal: der Hash hat sich geändert, damit
        # ist er wertlos.
        zweite = self.setzen("NochEinPasswort7")
        self.assertEqual(zweite.status_code, status.HTTP_400_BAD_REQUEST)
        self.person.refresh_from_db()
        self.assertTrue(self.person.check_password("EinAnderesPasswort9"))

    def test_erfundener_token_wird_abgewiesen(self):
        antwort = self.setzen("EinAnderesPasswort9", token="abc-erfunden")
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)
        self.person.refresh_from_db()
        self.assertTrue(self.person.check_password("EinGutesPasswort1"))

    def test_schwaches_passwort_wird_abgewiesen(self):
        """Djangos Regeln gelten hier genauso wie überall sonst."""
        antwort = self.setzen("12345678")
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)
        self.person.refresh_from_db()
        self.assertTrue(self.person.check_password("EinGutesPasswort1"))

    def test_bestehende_sitzung_endet(self):
        Token.objects.create(user=self.person)
        self.setzen("EinAnderesPasswort9")
        self.assertFalse(Token.objects.filter(user=self.person).exists())
