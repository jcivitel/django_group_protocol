"""
Volltextsuche.

Zwei Dinge werden geprueft, und das zweite ist das wichtigere: dass sie
findet, und dass sie **nicht** findet, was das Konto nicht sehen darf. Eine
Suche, die Treffer aus fremden Gruppen anzeigt, ist eine Umgehung der Rechte
mit Komfortbegruendung - und sie faellt niemandem auf, weil ein Treffer ja
wie ein Erfolg aussieht.
"""

from datetime import date

from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase

from django_grp_backend.models import (
    Group,
    Protocol,
    ProtocolItem,
    ProtocolObservation,
    Resident,
)
from django_grp_backend.suche import begriffe, boolean_ausdruck, suchen


class BegriffeTestCase(APITestCase):
    """Was aus einer Eingabe wird, bevor die Datenbank sie sieht."""

    def test_kurze_woerter_fallen_raus(self):
        # innodb_ft_min_token_size ist ab Werk drei.
        self.assertEqual(begriffe("im Bad"), ["Bad"])

    def test_satzzeichen_fliegen_raus(self):
        """
        Im Boolean-Modus sind +, -, * und Klammern Steuerzeichen. Ein
        Suchwort mit Klammer waere sonst ein Syntaxfehler in der Datenbank
        und keine leere Ergebnisliste.
        """
        self.assertEqual(begriffe("Ausflug (Samstag)!"), ["Ausflug", "Samstag"])

    def test_umlaute_bleiben(self):
        self.assertEqual(begriffe("Gespräch über Schule"), ["Gespräch", "über", "Schule"])

    def test_leere_eingabe(self):
        self.assertEqual(begriffe(""), [])
        self.assertEqual(begriffe("  "), [])

    def test_jedes_wort_ist_pflicht_und_darf_vorne_stehen(self):
        """
        Der Stern faengt die deutsche Beugung und die zusammengesetzten
        Woerter ab: ohne ihn faende "Medikament" kein "Medikamentenplan".
        """
        self.assertEqual(
            boolean_ausdruck(["Medikament", "Plan"]), "+Medikament* +Plan*"
        )


class SucheTestCase(APITransactionTestCase):
    """
    Die Suche selbst, ueber den Endpunkt.

    **APITransactionTestCase und nicht APITestCase**, und das ist kein
    Geschmack: InnoDB traegt neue Zeilen erst beim Commit in den
    Volltextindex ein. Ein gewoehnlicher TestCase laeuft in einer
    Transaktion, die am Ende zurueckgerollt wird - `MATCH ... AGAINST`
    findet darin nichts, und zwar auch dann nicht, wenn alles richtig ist.

    Dieselbe Eigenschaft gilt im Betrieb: wer in einer Transaktion schreibt
    und darin sucht, findet das eben Geschriebene nicht. Fuer diese
    Anwendung ist das folgenlos - gesucht wird in einer eigenen Anfrage -
    aber es gehoert gewusst.
    """

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
            last_name="Brandhorst",
            group=self.gruppe,
            moved_in_since=date(2024, 1, 1),
        )

        self.protokoll = Protocol.objects.create(
            group=self.gruppe,
            protocol_date=date(2026, 3, 4),
            topic="Gruppenabend zum Kletterwald",
        )
        ProtocolItem.objects.create(
            protocol=self.protokoll,
            name="Rückblick",
            value="Der Ausflug zum Kletterwald wurde von allen mitgetragen.",
            position=0,
        )
        ProtocolObservation.objects.create(
            protocol=self.protokoll,
            resident=self.kind,
            category="behaviour",
            text="Nele hat beim Klettern zum ersten Mal die Führung übernommen.",
        )

        self.client.force_authenticate(user=self.fachkraft)

    def hole(self, frage):
        return self.client.get(f"/api/v1/suche/?q={frage}")

    def test_findet_im_protokollpunkt(self):
        antwort = self.hole("Kletterwald")
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        arten = {gruppe["art"] for gruppe in antwort.data["gruppen"]}
        self.assertIn("protokoll", arten)

    def test_findet_im_verlauf(self):
        gruppen = {g["art"]: g for g in self.hole("Führung").data["gruppen"]}
        self.assertIn("verlauf", gruppen)
        self.assertIn("Nele", gruppen["verlauf"]["treffer"][0]["titel"])

    def test_findet_bewohner_am_namensanfang(self):
        gruppen = {g["art"]: g for g in self.hole("Brand").data["gruppen"]}
        self.assertIn("bewohner", gruppen)
        self.assertEqual(
            gruppen["bewohner"]["treffer"][0]["titel"], "Nele Brandhorst"
        )

    def test_mitten_im_namen_zaehlt_nicht(self):
        """
        Namen werden am Anfang verglichen. Sonst faende "and" jeden zweiten
        Nachnamen, und die Liste waere unbrauchbar.
        """
        gruppen = {g["art"]: g for g in self.hole("andhorst").data["gruppen"]}
        self.assertNotIn("bewohner", gruppen)

    def test_zwei_woerter_muessen_beide_vorkommen(self):
        beide = self.hole("Ausflug Kletterwald").data["gruppen"]
        self.assertTrue(any(g["art"] == "protokoll" for g in beide))

        # "Zahnarzt" steht nirgends - damit faellt der ganze Treffer weg.
        keins = self.hole("Ausflug Zahnarzt").data["gruppen"]
        self.assertFalse(any(g["art"] == "protokoll" for g in keins))

    def test_der_ausschnitt_zeigt_die_stelle(self):
        treffer = [
            g for g in self.hole("Kletterwald").data["gruppen"]
            if g["art"] == "protokoll"
        ][0]["treffer"][0]
        self.assertIn("Kletterwald", treffer["ausschnitt"])
        self.assertTrue(treffer["pfad"].startswith("/protokolle/"))

    def test_fremde_gruppe_findet_nichts(self):
        """Der Fall, der beim Bauen einer Suche am leichtesten durchrutscht."""
        self.client.force_authenticate(user=self.fremde)
        self.assertEqual(self.hole("Kletterwald").data["gruppen"], [])
        self.assertEqual(self.hole("Brand").data["gruppen"], [])
        self.assertEqual(self.hole("Führung").data["gruppen"], [])

    def test_zu_kurze_eingabe_sagt_es(self):
        antwort = self.hole("ab")
        self.assertEqual(antwort.data["gruppen"], [])
        self.assertIn("Buchstaben", antwort.data["hinweis"])

    def test_leere_eingabe_ohne_hinweis(self):
        antwort = self.hole("")
        self.assertEqual(antwort.data["gruppen"], [])
        self.assertEqual(antwort.data["hinweis"], "")

    def test_ohne_anmeldung_abgewiesen(self):
        self.client.force_authenticate(user=None)
        self.assertIn(
            self.hole("Kletterwald").status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_steuerzeichen_werfen_die_datenbank_nicht(self):
        """
        Ein Suchtext voller Sonderzeichen darf einen Fehler geben - aber
        keinen Fehler 500.
        """
        for boesartig in ['+++', '"unbeendet', 'a* -b (c', "1' OR '1'='1"]:
            antwort = self.hole(boesartig.replace(" ", "%20"))
            self.assertEqual(antwort.status_code, status.HTTP_200_OK, boesartig)

    def test_das_protokoll_kommt_nur_einmal(self):
        """
        „Kletterwald" steht im Thema UND im Punkt. Zwei Zeilen zum selben
        Protokoll waeren fuer den Leser eine Dopplung ohne Aussage.
        """
        treffer = [
            g for g in self.hole("Kletterwald").data["gruppen"]
            if g["art"] == "protokoll"
        ][0]["treffer"]
        nummern = [eintrag["id"] for eintrag in treffer]
        self.assertEqual(len(nummern), len(set(nummern)))

    def test_suche_ohne_gruppe_ist_leer(self):
        allein = User.objects.create_user(
            username="allein", password="testpass123"
        )
        self.client.force_authenticate(user=allein)
        self.assertEqual(self.hole("Kletterwald").data["gruppen"], [])


class SucheDirektTestCase(APITestCase):
    """Die Funktion ohne den Endpunkt - fuer die Faelle, die kein HTTP brauchen."""

    def test_ohne_treffer_bleiben_alle_listen_leer(self):
        konto = User.objects.create_user(username="k", password="testpass123")
        ergebnis = suchen(konto, "Kletterwald")
        self.assertEqual(ergebnis["protokolle"], [])
        self.assertEqual(ergebnis["verlauf"], [])
        self.assertEqual(ergebnis["bewohner"], [])


class SuchePersonalTestCase(APITransactionTestCase):
    """
    Personal findet nur, wer die Personalseite ohnehin oeffnen darf.

    Der Fall, der beim Bauen einer Suche am leichtesten durchrutscht: die
    Suche wird zum bequemen Weg um eine Rechtepruefung herum, und es faellt
    niemandem auf, weil ein Treffer wie ein Erfolg aussieht.
    """

    def setUp(self):
        from django_grp_org.models import Employee, Provider

        self.client = APIClient()
        self.verwaltung = User.objects.create_user(
            username="verwaltung", password="testpass123", is_staff=True
        )
        self.fachkraft = User.objects.create_user(
            username="fach", password="testpass123"
        )

        self.traeger = Provider.objects.create(name="Wegzeichen")
        Employee.objects.create(
            provider=self.traeger,
            first_name="Tobias",
            last_name="Ehlert",
            hired_on=date(2024, 1, 1),
            access_level="specialist",
        )

    def hole(self, frage, konto):
        self.client.force_authenticate(user=konto)
        return self.client.get(f"/api/v1/suche/?q={frage}")

    def test_verwaltung_findet_personal(self):
        gruppen = {
            g["art"]: g for g in self.hole("ehlert", self.verwaltung).data["gruppen"]
        }
        self.assertIn("personal", gruppen)
        self.assertEqual(gruppen["personal"]["treffer"][0]["titel"], "Tobias Ehlert")

    def test_fachkraft_findet_kein_personal(self):
        gruppen = {
            g["art"]: g for g in self.hole("ehlert", self.fachkraft).data["gruppen"]
        }
        self.assertNotIn("personal", gruppen)

    def test_auch_ohne_gruppe(self):
        """
        Eine Personalabteilung hat keine Wohngruppe. Ohne diese Ausnahme
        faende sie ueber die Suche gar nichts.
        """
        self.assertEqual(self.verwaltung.group_set.count(), 0)
        gruppen = {
            g["art"]: g for g in self.hole("tobias", self.verwaltung).data["gruppen"]
        }
        self.assertIn("personal", gruppen)

    def test_personalnummer_zaehlt_mit(self):
        from django_grp_org.models import Employee

        Employee.objects.filter(last_name="Ehlert").update(personnel_number="4711")
        gruppen = {
            g["art"]: g for g in self.hole("4711", self.verwaltung).data["gruppen"]
        }
        self.assertIn("personal", gruppen)
