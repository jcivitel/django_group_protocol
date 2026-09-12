"""
Die Rechtematrix je Person.

Der Teil, auf den es ankommt, steht in `MatrixGreiftTestCase`: eine Matrix,
die nur `darf()` beantwortet und an den Endpunkten nicht ankommt, ist eine
Anzeige und keine Sperre. Deshalb wird hier gegen die echten Adressen
geprueft und nicht gegen die Funktion.
"""

from datetime import date

from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from django.utils import timezone

from django_grp_backend import rechte, zweitfaktor
from django_grp_backend.models import (
    Group,
    Protocol,
    Rechtezuweisung,
    Resident,
    ZweiterFaktor,
)
from django_grp_org.models import Employee, Provider


def setze(user, **merkmale):
    """Setzt eine vollstaendige Matrix; alles Ungenannte ist kein Zugriff."""
    for aktion in rechte.ALLE_AKTIONEN:
        Rechtezuweisung.objects.update_or_create(
            user=user,
            aktion=aktion,
            defaults={"stufe": merkmale.get(aktion, rechte.KEIN)},
        )


class MatrixBasis(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.traeger = Provider.objects.create(name="Wegzeichen")

        self.fachkraft = User.objects.create_user(
            username="fach",
            password="testpass123",
            first_name="Mara",
            last_name="Ott",
        )
        # Ein Personaldatensatz mit Stufe "specialist" - der Normalfall, und
        # genau der, bei dem is_staff und access_level auseinandergehen.
        Employee.objects.create(
            user=self.fachkraft,
            provider=self.traeger,
            first_name="Mara",
            last_name="Ott",
            hired_on=date(2024, 1, 1),
            access_level="specialist",
        )

        self.gruppe = Group.objects.create(
            name="Haus Ahorn", address="A", postalcode="11111", city="Hier"
        )
        self.gruppe.group_members.add(self.fachkraft)

        self.kind = Resident.objects.create(
            first_name="Nele",
            last_name="Beispiel",
            moved_in_since=date(2024, 1, 1),
            group=self.gruppe,
        )
        self.protokoll = Protocol.objects.create(
            group=self.gruppe, protocol_date=date.today()
        )


class MatrixEntscheidetTestCase(MatrixBasis):
    """Was `darf()` antwortet, sobald eine Matrix da ist."""

    def test_ohne_matrix_entscheidet_die_stufe(self):
        """
        Ein Konto, an dem noch niemand war, verliert nichts. Sonst waere die
        Einfuehrung ein Rechteentzug fuer alle auf einmal.
        """
        self.assertFalse(rechte.hat_eigene_matrix(self.fachkraft))
        self.assertTrue(
            rechte.darf(self.fachkraft, rechte.PROTOKOLLE, schreiben=True)
        )

    def test_die_matrix_schlaegt_die_stufe(self):
        setze(self.fachkraft, **{rechte.PROTOKOLLE: rechte.LESEN})

        self.assertTrue(rechte.darf(self.fachkraft, rechte.PROTOKOLLE))
        self.assertFalse(
            rechte.darf(self.fachkraft, rechte.PROTOKOLLE, schreiben=True)
        )

    def test_die_matrix_kann_auch_mehr_geben(self):
        """
        Nicht nur beschraenken: eine Fachkraft darf laut Stufe keine
        Zeitkonten abschliessen, per Matrix aber schon.
        """
        self.assertFalse(
            rechte.darf(
                self.fachkraft, rechte.ZEITKONTO_ABSCHLIESSEN, schreiben=True
            )
        )
        setze(
            self.fachkraft,
            **{rechte.ZEITKONTO_ABSCHLIESSEN: rechte.SCHREIBEN},
        )
        self.assertTrue(
            rechte.darf(
                self.fachkraft, rechte.ZEITKONTO_ABSCHLIESSEN, schreiben=True
            )
        )

    def test_eine_gesetzte_matrix_ist_vollstaendig(self):
        """
        Fehlt darin eine Zeile, heisst das kein Zugriff. Sonst liesse sich
        ein Entzug nicht von einer Luecke unterscheiden.
        """
        Rechtezuweisung.objects.create(
            user=self.fachkraft,
            aktion=rechte.PROTOKOLLE,
            stufe=rechte.SCHREIBEN,
        )
        self.assertTrue(
            rechte.darf(self.fachkraft, rechte.PROTOKOLLE, schreiben=True)
        )
        self.assertFalse(rechte.darf(self.fachkraft, rechte.BEWOHNER))

    def test_der_generalschluessel_steht_davor(self):
        """
        Der Notausgang fuer den Tag, an dem sich jemand aussperrt. Und den
        Tag gibt es.
        """
        chef = User.objects.create_user(
            username="chef", password="testpass123", is_staff=True
        )
        setze(chef)  # alles auf kein Zugriff

        self.assertTrue(rechte.darf(chef, rechte.PROTOKOLLE, schreiben=True))
        self.assertTrue(rechte.darf(chef, rechte.ORG_STRUKTUR, schreiben=True))

    def test_alles_auf_kein_zugriff_sperrt_wirklich(self):
        setze(self.fachkraft)
        for aktion in rechte.ALLE_AKTIONEN:
            with self.subTest(aktion=aktion):
                self.assertFalse(rechte.darf(self.fachkraft, aktion))


class MatrixGreiftTestCase(MatrixBasis):
    """
    Die Probe aufs Exempel: greift die Matrix an den echten Adressen?

    Eine Matrix, die nur `darf()` beantwortet, ist eine Anzeige. Sie muss
    den Schreibzugriff abweisen, und zwar dort, wo er ankommt.
    """

    def test_lesen_erlaubt_das_lesen(self):
        setze(self.fachkraft, **{rechte.PROTOKOLLE: rechte.LESEN})
        self.client.force_authenticate(user=self.fachkraft)

        antwort = self.client.get(f"/api/v1/protocol/{self.protokoll.id}/")
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)

    def test_lesen_verbietet_das_schreiben(self):
        setze(self.fachkraft, **{rechte.PROTOKOLLE: rechte.LESEN})
        self.client.force_authenticate(user=self.fachkraft)

        antwort = self.client.patch(
            f"/api/v1/protocol/{self.protokoll.id}/",
            {"topic": "Von einer Lesekraft geändert"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)
        self.protokoll.refresh_from_db()
        self.assertNotEqual(
            self.protokoll.topic, "Von einer Lesekraft geändert"
        )

    def test_schreiben_erlaubt_das_schreiben(self):
        setze(self.fachkraft, **{rechte.PROTOKOLLE: rechte.SCHREIBEN})
        self.client.force_authenticate(user=self.fachkraft)

        antwort = self.client.patch(
            f"/api/v1/protocol/{self.protokoll.id}/",
            {"topic": "Gruppenabend"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)

    def test_das_profil_nennt_die_wirksamen_rechte(self):
        """Damit die Oberflaeche aufhoert zu raten."""
        setze(
            self.fachkraft,
            **{
                rechte.PROTOKOLLE: rechte.SCHREIBEN,
                rechte.BEWOHNER: rechte.LESEN,
            },
        )
        self.client.force_authenticate(user=self.fachkraft)

        antwort = self.client.get("/api/v1/user/me/")
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)

        gemeldet = antwort.data["rechte"]
        self.assertEqual(gemeldet[rechte.PROTOKOLLE], "schreiben")
        self.assertEqual(gemeldet[rechte.BEWOHNER], "lesen")
        self.assertEqual(gemeldet[rechte.ORG_STRUKTUR], "kein")

    def test_die_auskunft_stimmt_mit_der_sperre_ueberein(self):
        """
        Die Probe auf die eigentliche Zusage: was das Profil meldet, muss
        genau das sein, was die Endpunkte zulassen. Gaebe es zwei
        Rechnungen, waere die Anzeige irgendwann die falsche - und das war
        der Fehler, den diese Auskunft ersetzt.
        """
        setze(
            self.fachkraft,
            **{
                rechte.PROTOKOLLE: rechte.SCHREIBEN,
                rechte.BEWOHNER: rechte.LESEN,
                rechte.FALLAKTE: rechte.KEIN,
            },
        )
        self.client.force_authenticate(user=self.fachkraft)
        gemeldet = self.client.get("/api/v1/user/me/").data["rechte"]

        for aktion, wort in gemeldet.items():
            with self.subTest(aktion=aktion):
                self.assertEqual(
                    rechte.darf(self.fachkraft, aktion, schreiben=True),
                    wort == "schreiben",
                )
                self.assertEqual(
                    rechte.darf(self.fachkraft, aktion),
                    wort in ("lesen", "schreiben"),
                )


class MatrixVergebenTestCase(MatrixBasis):
    """Wer die Matrix anderer setzen darf - und wer nicht."""

    def setUp(self):
        super().setUp()
        self.leitung = User.objects.create_user(
            username="leitung", password="testpass123", is_staff=True
        )
        # Rechte vergeben darf nur, wer selbst einen zweiten Faktor hat.
        # Ohne ihn antwortet der Endpunkt mit 403, und zwar zu Recht.
        faktor = ZweiterFaktor(user=self.leitung, bestaetigt_am=timezone.now())
        faktor.geheimnis = zweitfaktor.geheimnis_erzeugen()
        faktor.save()

    def test_vorlagen_kommen_aus_derselben_quelle(self):
        self.client.force_authenticate(user=self.fachkraft)
        antwort = self.client.get("/api/v1/rechte/vorlagen/")

        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        kennungen = {v["kennung"] for v in antwort.data["vorlagen"]}
        self.assertIn("facility_lead", kennungen)
        self.assertEqual(len(antwort.data["vorlagen"]), 9)

        # Jede Vorlage nennt jedes Merkmal. Eine Vorlage mit Luecken waere
        # eine Matrix mit unbeantworteten Zeilen.
        for vorlage in antwort.data["vorlagen"]:
            self.assertEqual(
                sorted(vorlage["rechte"]), sorted(rechte.ALLE_AKTIONEN)
            )

    def test_die_gliederung_nennt_jedes_merkmal_genau_einmal(self):
        self.client.force_authenticate(user=self.fachkraft)
        antwort = self.client.get("/api/v1/rechte/vorlagen/")

        aus_gruppen = [
            m["kennung"] for g in antwort.data["gruppen"] for m in g["merkmale"]
        ]
        self.assertEqual(sorted(aus_gruppen), sorted(rechte.ALLE_AKTIONEN))
        self.assertEqual(len(aus_gruppen), len(set(aus_gruppen)))

    def test_ohne_recht_kein_lesen_fremder_matrix(self):
        self.client.force_authenticate(user=self.fachkraft)
        antwort = self.client.get(f"/api/v1/rechte/{self.leitung.id}/")
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)

    def test_ohne_recht_kein_setzen(self):
        self.client.force_authenticate(user=self.fachkraft)
        antwort = self.client.put(
            f"/api/v1/rechte/{self.leitung.id}/",
            {"rechte": {a: rechte.SCHREIBEN for a in rechte.ALLE_AKTIONEN}},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Rechtezuweisung.objects.exists())

    def test_die_leitung_setzt_eine_matrix(self):
        self.client.force_authenticate(user=self.leitung)
        antwort = self.client.put(
            f"/api/v1/rechte/{self.fachkraft.id}/",
            {
                "rechte": {
                    **{a: rechte.KEIN for a in rechte.ALLE_AKTIONEN},
                    rechte.PROTOKOLLE: rechte.SCHREIBEN,
                }
            },
            format="json",
        )

        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        self.assertTrue(rechte.hat_eigene_matrix(self.fachkraft))
        self.assertTrue(
            rechte.darf(self.fachkraft, rechte.PROTOKOLLE, schreiben=True)
        )
        self.assertFalse(rechte.darf(self.fachkraft, rechte.BEWOHNER))

    def test_niemand_aendert_die_eigene_matrix(self):
        """
        Sonst waere jede Beschraenkung eine, die sich in derselben Sitzung
        wieder aufheben laesst.
        """
        self.client.force_authenticate(user=self.leitung)
        antwort = self.client.put(
            f"/api/v1/rechte/{self.leitung.id}/",
            {"rechte": {a: rechte.SCHREIBEN for a in rechte.ALLE_AKTIONEN}},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)

    def test_ein_unbekanntes_merkmal_wird_abgewiesen(self):
        """
        Ein Tippfehler in der Kennung waere sonst ein Recht, das niemand
        vergibt und das trotzdem in der Tabelle steht.
        """
        self.client.force_authenticate(user=self.leitung)
        antwort = self.client.put(
            f"/api/v1/rechte/{self.fachkraft.id}/",
            {"rechte": {"doku.protokoll": rechte.SCHREIBEN}},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("doku.protokoll", str(antwort.data))
        self.assertFalse(Rechtezuweisung.objects.exists())

    def test_eine_ungueltige_stufe_wird_abgewiesen(self):
        self.client.force_authenticate(user=self.leitung)
        for wert in (7, -1, "schreiben", None):
            with self.subTest(wert=wert):
                antwort = self.client.put(
                    f"/api/v1/rechte/{self.fachkraft.id}/",
                    {"rechte": {rechte.PROTOKOLLE: wert}},
                    format="json",
                )
                self.assertEqual(
                    antwort.status_code, status.HTTP_400_BAD_REQUEST
                )

    def test_zuruecknehmen_gibt_das_konto_an_die_stufe_zurueck(self):
        """
        Nicht dasselbe wie alles auf kein Zugriff: das eine gibt zurueck,
        das andere sperrt aus.
        """
        setze(self.fachkraft)
        self.assertFalse(rechte.darf(self.fachkraft, rechte.PROTOKOLLE))

        self.client.force_authenticate(user=self.leitung)
        antwort = self.client.delete(f"/api/v1/rechte/{self.fachkraft.id}/")

        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        self.assertFalse(rechte.hat_eigene_matrix(self.fachkraft))
        self.assertTrue(
            rechte.darf(self.fachkraft, rechte.PROTOKOLLE, schreiben=True)
        )

    def test_ein_generalschluessel_laesst_sich_nicht_beschneiden(self):
        """
        Seine Matrix haette keine Wirkung. Eine Oberflaeche, die sie
        trotzdem anbietet, verspricht etwas Falsches.
        """
        zweite_leitung = User.objects.create_user(
            username="chef2", password="testpass123", is_staff=True
        )
        self.client.force_authenticate(user=self.leitung)

        antwort = self.client.put(
            f"/api/v1/rechte/{zweite_leitung.id}/",
            {"rechte": {a: rechte.KEIN for a in rechte.ALLE_AKTIONEN}},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)

    def test_die_aenderung_steht_im_aenderungsprotokoll(self):
        from django_grp_org.audit import AuditEvent

        vorher = AuditEvent.objects.count()
        self.client.force_authenticate(user=self.leitung)
        self.client.put(
            f"/api/v1/rechte/{self.fachkraft.id}/",
            {"rechte": {a: rechte.LESEN for a in rechte.ALLE_AKTIONEN}},
            format="json",
        )

        self.assertGreater(AuditEvent.objects.count(), vorher)

    def test_wer_gesetzt_hat_steht_dabei(self):
        self.client.force_authenticate(user=self.leitung)
        self.client.put(
            f"/api/v1/rechte/{self.fachkraft.id}/",
            {"rechte": {a: rechte.LESEN for a in rechte.ALLE_AKTIONEN}},
            format="json",
        )

        zeile = Rechtezuweisung.objects.filter(user=self.fachkraft).first()
        self.assertEqual(zeile.geaendert_von, "leitung")
