"""
Erwaehnungen und der Generalschluessel.

Beides Aenderungen an bestehenden Wegen, und beide koennten still
danebengehen: eine Suche, die zu viel findet, faellt niemandem auf, und ein
Konto, das nach einer Rechteumstellung aussperrt, faellt erst nachts auf.
"""

from datetime import date

from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from django_grp_backend import rechte
from django_grp_backend.models import (
    Group,
    Protocol,
    ProtocolItem,
    Resident,
)


class ErwaehnungenTestCase(APITestCase):
    """Was die Datenbank findet, und was sie nicht finden darf."""

    def setUp(self):
        self.client = APIClient()
        self.fachkraft = User.objects.create_user(
            username="fach", password="testpass123"
        )
        self.fremde = User.objects.create_user(
            username="fremd", password="testpass123"
        )

        self.gruppe = Group.objects.create(
            name="Ahorn", address="A", postalcode="11111", city="Hier"
        )
        self.andere = Group.objects.create(
            name="Birke", address="B", postalcode="22222", city="Dort"
        )
        self.gruppe.group_members.add(self.fachkraft)
        self.andere.group_members.add(self.fremde)

        self.kind = Resident.objects.create(
            first_name="Nele",
            last_name="Beispiel",
            group=self.gruppe,
            moved_in_since=date(2024, 1, 1),
        )
        self.client.force_authenticate(user=self.fachkraft)

    def protokoll(self, tag, text, gruppe=None):
        eintrag = Protocol.objects.create(
            group=gruppe or self.gruppe, protocol_date=tag
        )
        ProtocolItem.objects.create(
            protocol=eintrag, name="Verlauf", value=text, position=0
        )
        return eintrag

    def hole(self, bewohner=None):
        return self.client.get(
            f"/api/v1/resident/{(bewohner or self.kind).id}/mentions/"
        )

    def test_findet_die_erwaehnung(self):
        self.protokoll(
            date(2026, 3, 4),
            "Am Nachmittag hat @Nele_Beispiel die Aufgabe uebernommen.",
        )
        antwort = self.hole()
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        self.assertEqual(len(antwort.data), 1)
        self.assertEqual(antwort.data[0]["itemName"], "Verlauf")
        self.assertIn("Aufgabe uebernommen", antwort.data[0]["excerpt"])

    def test_gross_und_kleinschreibung_egal(self):
        self.protokoll(date(2026, 3, 4), "Hinweis von @nele_beispiel.")
        self.assertEqual(len(self.hole().data), 1)

    def test_ohne_klammeraffe_kein_treffer(self):
        """
        Der Name allein ist keine Erwaehnung. Sonst faende die Suche jeden
        Satz, in dem das Kind vorkommt - und das ist jedes Protokoll.
        """
        self.protokoll(date(2026, 3, 4), "Nele Beispiel war beim Zahnarzt.")
        self.assertEqual(len(self.hole().data), 0)

    def test_nur_die_eigene_gruppe(self):
        """
        Ein gleichnamiges Kind in der Nachbargruppe darf die Akte nicht
        fuellen - und ein Protokoll der Nachbargruppe erst recht nicht.
        """
        self.protokoll(
            date(2026, 3, 4),
            "@Nele_Beispiel war hier.",
            gruppe=self.andere,
        )
        self.assertEqual(len(self.hole().data), 0)

    def test_juengste_zuerst(self):
        self.protokoll(date(2026, 1, 5), "@Nele_Beispiel im Januar.")
        self.protokoll(date(2026, 5, 5), "@Nele_Beispiel im Mai.")
        daten = self.hole().data
        self.assertEqual(len(daten), 2)
        self.assertGreater(daten[0]["protocolDate"], daten[1]["protocolDate"])

    def test_ausschnitt_statt_ganzem_text(self):
        lang = "x" * 400 + " @Nele_Beispiel " + "y" * 400
        self.protokoll(date(2026, 3, 4), lang)
        ausschnitt = self.hole().data[0]["excerpt"]
        self.assertLess(len(ausschnitt), len(lang))
        self.assertIn("@Nele_Beispiel", ausschnitt)
        self.assertTrue(ausschnitt.startswith("…"))
        self.assertTrue(ausschnitt.endswith("…"))

    def test_fremde_gruppe_bekommt_nichts(self):
        """Wie ueberall: 404, nicht 403 - sonst bestaetigt die Antwort die Id."""
        self.protokoll(date(2026, 3, 4), "@Nele_Beispiel war hier.")
        self.client.force_authenticate(user=self.fremde)
        self.assertEqual(self.hole().status_code, status.HTTP_404_NOT_FOUND)

    def test_ohne_anmeldung_abgewiesen(self):
        self.client.force_authenticate(user=None)
        self.assertIn(
            self.hole().status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )


class GeneralschluesselTestCase(APITestCase):
    """
    Superuser und `is_staff` duerfen immer alles.

    Das ist der Notausgang der Rechteumstellung: wer den Schalter auf
    `rollen` stellt und dabei eine Zuweisung vergisst, kommt ueber ein
    solches Konto wieder hinein - ohne Datenbankzugriff.
    """

    def setUp(self):
        self.mitarbeit = User.objects.create_user(
            username="staff", password="testpass123", is_staff=True
        )
        self.root = User.objects.create_superuser(
            username="root", password="testpass123", email=""
        )
        self.niemand = User.objects.create_user(
            username="niemand", password="testpass123"
        )

    def test_staff_darf_alles_unter_stufe(self):
        for aktion in rechte.MATRIX["executive"]:
            self.assertTrue(
                rechte.darf(self.mitarbeit, aktion, schreiben=True),
                f"Staff darf {aktion} nicht",
            )

    @override_settings(RECHTE_QUELLE="rollen")
    def test_staff_darf_alles_auch_unter_rollen(self):
        """Ohne eine einzige Rollenzuweisung."""
        for aktion in rechte.MATRIX["executive"]:
            self.assertTrue(
                rechte.darf(self.mitarbeit, aktion, schreiben=True),
                f"Staff darf {aktion} nicht",
            )

    @override_settings(RECHTE_QUELLE="rollen")
    def test_superuser_ebenso(self):
        self.assertTrue(
            rechte.darf(self.root, rechte.FALLAKTE_GESCHUETZT, schreiben=True)
        )

    @override_settings(RECHTE_QUELLE="rollen")
    def test_ohne_beides_und_ohne_rolle_nichts(self):
        self.assertFalse(rechte.darf(self.niemand, rechte.PROTOKOLLE))

    def test_generalschluessel_ohne_anmeldung(self):
        self.assertFalse(rechte.generalschluessel(None))

    def test_alte_helfer_antworten_weiter(self):
        """
        `is_admin` und `may_write` heissen noch so und fragen jetzt die
        Auskunftsstelle. Fuer die Aufrufer darf sich nichts geaendert haben.
        """
        from django_grp_backend.access import is_admin, may_read_only, may_write

        self.assertTrue(is_admin(self.mitarbeit))
        self.assertTrue(may_write(self.mitarbeit))
        self.assertFalse(may_read_only(self.mitarbeit))

        self.assertFalse(is_admin(self.niemand))
