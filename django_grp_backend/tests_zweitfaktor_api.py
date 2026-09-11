"""
Der zweite Faktor an der Schnittstelle.

Die Rechnung selbst steht in `tests_zweitfaktor.py` gegen die Vektoren aus
dem Standard. Hier geht es um die Regeln drumherum, und die sind es, an
denen so etwas im Betrieb scheitert: wann die Anmeldung durchgeht, wer
abschalten darf, und ob der Notfallweg wirklich nur der Verwaltung offen
steht.
"""

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from django_grp_backend import zweitfaktor
from django_grp_backend.models import ZweiterFaktor


def _code(geheimnis: str) -> str:
    return zweitfaktor.code(geheimnis, zweitfaktor.schritt_jetzt())


class ZweitfaktorBasis(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.fachkraft = User.objects.create_user(
            username="fach", password="testpass123"
        )
        # is_staff traegt den Generalschluessel: dieses Konto darf verwalten
        # und hat damit Pflicht.
        self.leitung = User.objects.create_user(
            username="leitung", password="testpass123", is_staff=True
        )

    def _einrichten(self, user) -> str:
        """Richtet einen aktiven Faktor ein und gibt das Geheimnis zurueck."""
        geheimnis = zweitfaktor.geheimnis_erzeugen()
        eintrag = ZweiterFaktor(user=user, bestaetigt_am=timezone.now())
        eintrag.geheimnis = geheimnis
        eintrag.save()
        return geheimnis


class EinrichtenTestCase(ZweitfaktorBasis):
    def test_stand_ist_zunaechst_aus(self):
        self.client.force_authenticate(user=self.fachkraft)
        antwort = self.client.get("/api/v1/zweitfaktor/")

        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        self.assertFalse(antwort.data["aktiv"])
        self.assertFalse(antwort.data["eingerichtet"])
        self.assertFalse(antwort.data["pflicht"])

    def test_verwaltung_hat_pflicht(self):
        self.client.force_authenticate(user=self.leitung)
        antwort = self.client.get("/api/v1/zweitfaktor/")

        self.assertTrue(antwort.data["pflicht"])
        self.assertFalse(antwort.data["aktiv"])

    def test_einrichten_gibt_geheimnis_und_adresse(self):
        self.client.force_authenticate(user=self.fachkraft)
        antwort = self.client.post("/api/v1/zweitfaktor/einrichten/")

        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        geheimnis = antwort.data["data"]["geheimnis"]
        self.assertEqual(len(geheimnis), 32)
        self.assertIn(f"secret={geheimnis}", antwort.data["data"]["otpauth"])

    def test_eingerichtet_ist_noch_nicht_aktiv(self):
        """
        Zwischen Einrichten und Bestaetigen liegt ein Code. Ohne diese
        Trennung sperrt sich aus, wer die Einrichtung abbricht.
        """
        self.client.force_authenticate(user=self.fachkraft)
        self.client.post("/api/v1/zweitfaktor/einrichten/")

        stand = self.client.get("/api/v1/zweitfaktor/").data
        self.assertTrue(stand["eingerichtet"])
        self.assertFalse(stand["aktiv"])

    def test_bestaetigen_mit_richtigem_code(self):
        self.client.force_authenticate(user=self.fachkraft)
        geheimnis = self.client.post("/api/v1/zweitfaktor/einrichten/").data["data"][
            "geheimnis"
        ]

        antwort = self.client.post(
            "/api/v1/zweitfaktor/bestaetigen/", {"code": _code(geheimnis)}
        )

        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        self.assertTrue(antwort.data["data"]["aktiv"])

    def test_bestaetigen_mit_falschem_code_schaltet_nicht(self):
        self.client.force_authenticate(user=self.fachkraft)
        self.client.post("/api/v1/zweitfaktor/einrichten/")

        antwort = self.client.post(
            "/api/v1/zweitfaktor/bestaetigen/", {"code": "000000"}
        )

        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(self.client.get("/api/v1/zweitfaktor/").data["aktiv"])

    def test_ein_aktiver_faktor_wird_nicht_ueberschrieben(self):
        """
        Sonst genuegte ein gestohlener Token, um den Faktor gegen einen
        eigenen zu tauschen.
        """
        self._einrichten(self.fachkraft)
        self.client.force_authenticate(user=self.fachkraft)

        antwort = self.client.post("/api/v1/zweitfaktor/einrichten/")
        self.assertEqual(antwort.status_code, status.HTTP_409_CONFLICT)

    def test_geheimnis_liegt_nicht_im_klartext_in_der_tabelle(self):
        geheimnis = self._einrichten(self.fachkraft)
        eintrag = ZweiterFaktor.objects.get(user=self.fachkraft)

        self.assertNotEqual(eintrag.geheim_verschluesselt, geheimnis)
        self.assertNotIn(geheimnis, eintrag.geheim_verschluesselt)
        # Lesbar bleibt es trotzdem - sonst waere es nur kaputt.
        self.assertEqual(eintrag.geheimnis, geheimnis)


class AbschaltenTestCase(ZweitfaktorBasis):
    def test_abschalten_braucht_einen_code(self):
        self._einrichten(self.fachkraft)
        self.client.force_authenticate(user=self.fachkraft)

        antwort = self.client.post("/api/v1/zweitfaktor/aus/", {"code": "000000"})

        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(ZweiterFaktor.objects.filter(user=self.fachkraft).exists())

    def test_abschalten_mit_code(self):
        geheimnis = self._einrichten(self.fachkraft)
        self.client.force_authenticate(user=self.fachkraft)

        antwort = self.client.post(
            "/api/v1/zweitfaktor/aus/", {"code": _code(geheimnis)}
        )

        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        self.assertFalse(ZweiterFaktor.objects.filter(user=self.fachkraft).exists())

    def test_wer_pflicht_hat_kann_nicht_abschalten(self):
        geheimnis = self._einrichten(self.leitung)
        self.client.force_authenticate(user=self.leitung)

        antwort = self.client.post(
            "/api/v1/zweitfaktor/aus/", {"code": _code(geheimnis)}
        )

        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(ZweiterFaktor.objects.filter(user=self.leitung).exists())


class ZuruecksetzenTestCase(ZweitfaktorBasis):
    """
    Der Notfallweg. Es gibt keine Wiederherstellungscodes, also ist das der
    einzige Weg zurueck - und damit der empfindlichste Endpunkt.
    """

    def test_nur_die_verwaltung_darf(self):
        self._einrichten(self.leitung)
        self.client.force_authenticate(user=self.fachkraft)

        antwort = self.client.post(
            "/api/v1/zweitfaktor/zuruecksetzen/", {"user": self.leitung.id}
        )

        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(ZweiterFaktor.objects.filter(user=self.leitung).exists())

    def test_die_verwaltung_setzt_zurueck(self):
        self._einrichten(self.fachkraft)
        self.client.force_authenticate(user=self.leitung)

        antwort = self.client.post(
            "/api/v1/zweitfaktor/zuruecksetzen/", {"user": self.fachkraft.id}
        )

        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        self.assertFalse(ZweiterFaktor.objects.filter(user=self.fachkraft).exists())

    def test_das_eigene_konto_geht_hier_nicht(self):
        """
        Sonst waere das ein Abschalten ohne Code, an der Pruefung in
        ZweitfaktorAusView vorbei - und fuer die Leitung die Umgehung ihrer
        eigenen Pflicht.
        """
        self._einrichten(self.leitung)
        self.client.force_authenticate(user=self.leitung)

        antwort = self.client.post(
            "/api/v1/zweitfaktor/zuruecksetzen/", {"user": self.leitung.id}
        )

        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(ZweiterFaktor.objects.filter(user=self.leitung).exists())

    def test_zuruecksetzen_steht_im_aenderungsprotokoll(self):
        from django_grp_org.audit import AuditEvent

        self._einrichten(self.fachkraft)
        vorher = AuditEvent.objects.count()

        self.client.force_authenticate(user=self.leitung)
        self.client.post(
            "/api/v1/zweitfaktor/zuruecksetzen/", {"user": self.fachkraft.id}
        )

        self.assertGreater(AuditEvent.objects.count(), vorher)

    def test_das_geheimnis_steht_nicht_im_protokoll(self):
        """
        Verschluesselt ist es, aber es gehoert trotzdem nicht in eine zweite
        Tabelle. Ein Geheimnis an einer Stelle laesst sich drehen, eines an
        zweien vergisst man zur Haelfte.
        """
        from django_grp_org.audit import AuditEvent

        geheimnis = self._einrichten(self.fachkraft)
        eintrag = ZweiterFaktor.objects.get(user=self.fachkraft)

        self.client.force_authenticate(user=self.leitung)
        self.client.post(
            "/api/v1/zweitfaktor/zuruecksetzen/", {"user": self.fachkraft.id}
        )

        alles = " ".join(str(e.changes) for e in AuditEvent.objects.all())
        self.assertNotIn(geheimnis, alles)
        self.assertNotIn(eintrag.geheim_verschluesselt, alles)


class PflichtGreiftTestCase(ZweitfaktorBasis):
    """
    Die Pflicht ist erst dann eine, wenn der Server sie durchsetzt.

    Sie haelt die Anmeldung nicht auf - sonst haette die Einfuehrung am
    ersten Tag die ganze Verwaltung ausgesperrt. Zu bleibt genau das, wofuer
    der Faktor gedacht ist.
    """

    def test_ohne_faktor_keine_stammdatenaenderung(self):
        self.client.force_authenticate(user=self.leitung)

        antwort = self.client.post(
            "/api/v1/qualification/",
            {"name": "Probe Zweitfaktor", "is_specialist": False},
            format="json",
        )

        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("zweite Faktor", str(antwort.data))

    def test_mit_faktor_geht_es(self):
        self._einrichten(self.leitung)
        self.client.force_authenticate(user=self.leitung)

        antwort = self.client.post(
            "/api/v1/qualification/",
            {"name": "Probe Zweitfaktor", "is_specialist": False},
            format="json",
        )

        self.assertIn(
            antwort.status_code,
            (status.HTTP_200_OK, status.HTTP_201_CREATED),
        )

    def test_lesen_bleibt_offen(self):
        """
        Wer noch keinen Faktor hat, soll weiterarbeiten koennen. Nur das
        Aendern ist zu.
        """
        self.client.force_authenticate(user=self.leitung)

        antwort = self.client.get("/api/v1/qualification/")
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)

    def test_ohne_pflicht_aendert_sich_nichts(self):
        """
        Eine Fachkraft ohne Verwaltungsrechte wird von dieser Regel nicht
        beruehrt - sie darf Stammdaten ohnehin nicht aendern, und zwar mit
        der alten Begruendung.
        """
        self.client.force_authenticate(user=self.fachkraft)

        antwort = self.client.post(
            "/api/v1/qualification/", {"name": "Probe ohne Pflicht"}, format="json"
        )

        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotIn("zweite Faktor", str(antwort.data))


class AnmeldungTestCase(ZweitfaktorBasis):
    """Die Anmeldung selbst - der Weg, den jede Fachkraft taeglich geht."""

    def test_ohne_faktor_wie_bisher(self):
        antwort = self.client.post(
            "/api/v1/auth/login/",
            {"username": "fach", "password": "testpass123"},
            format="json",
        )

        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        self.assertIn("token", antwort.data["data"])

    def test_mit_faktor_und_ohne_code_kein_token(self):
        self._einrichten(self.fachkraft)

        antwort = self.client.post(
            "/api/v1/auth/login/",
            {"username": "fach", "password": "testpass123"},
            format="json",
        )

        self.assertEqual(antwort.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertTrue(antwort.data["zweitfaktor"])
        self.assertNotIn("data", antwort.data)

    def test_mit_faktor_und_code(self):
        geheimnis = self._einrichten(self.fachkraft)

        antwort = self.client.post(
            "/api/v1/auth/login/",
            {
                "username": "fach",
                "password": "testpass123",
                "code": _code(geheimnis),
            },
            format="json",
        )

        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        self.assertIn("token", antwort.data["data"])

    def test_falsches_passwort_verraet_den_faktor_nicht(self):
        """
        Der Faktor wird erst nach dem Passwort geprueft. Andersherum
        verriete die Antwort, welche Konten einen haben - und damit, welche
        interessant sind.
        """
        self._einrichten(self.fachkraft)

        antwort = self.client.post(
            "/api/v1/auth/login/",
            {"username": "fach", "password": "falsch"},
            format="json",
        )

        self.assertEqual(antwort.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotIn("zweitfaktor", antwort.data)

    def test_derselbe_code_geht_kein_zweites_mal(self):
        geheimnis = self._einrichten(self.fachkraft)
        code = _code(geheimnis)
        zugang = {
            "username": "fach",
            "password": "testpass123",
            "code": code,
        }

        erste = self.client.post("/api/v1/auth/login/", zugang, format="json")
        self.assertEqual(erste.status_code, status.HTTP_200_OK)

        zweite = self.client.post("/api/v1/auth/login/", zugang, format="json")
        self.assertEqual(zweite.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_ein_nicht_bestaetigter_faktor_haelt_niemanden_auf(self):
        """
        Wer die Einrichtung abbricht, muss sich weiter anmelden koennen.
        """
        eintrag = ZweiterFaktor(user=self.fachkraft)
        eintrag.geheimnis = zweitfaktor.geheimnis_erzeugen()
        eintrag.save()

        antwort = self.client.post(
            "/api/v1/auth/login/",
            {"username": "fach", "password": "testpass123"},
            format="json",
        )

        self.assertEqual(antwort.status_code, status.HTTP_200_OK)

    def test_die_anmeldung_sagt_ob_pflicht_besteht(self):
        """
        Pflicht ohne aktiven Faktor laesst die Anmeldung durch - sonst
        sperrte die Einfuehrung die ganze Verwaltung aus. Die Oberflaeche
        fuehrt daraufhin zur Einrichtung.
        """
        antwort = self.client.post(
            "/api/v1/auth/login/",
            {"username": "leitung", "password": "testpass123"},
            format="json",
        )

        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        self.assertTrue(antwort.data["data"]["zweitfaktor"]["pflicht"])
        self.assertFalse(antwort.data["data"]["zweitfaktor"]["aktiv"])
