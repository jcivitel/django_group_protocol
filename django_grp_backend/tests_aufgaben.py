"""
Aufgaben erledigen und die Medikation in der Teambesprechung.

Beide Aenderungen schliessen dieselbe Art von Luecke: etwas war in der
Anwendung nicht darstellbar, und deshalb stimmte die Anzeige dauerhaft
nicht. Aufgaben konnten nie fertig werden und waren irgendwann alle
ueberfaellig; die Medikation stand nur in der Akte und kam in keiner
Besprechung vor.
"""

from datetime import date, timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from django_grp_backend.models import (
    Group,
    Medication,
    Protocol,
    ProtocolTemplate,
    ProtocolTemplateItem,
    ProtocolTodo,
    Resident,
    medikationsuebersicht,
)


class AufgabeErledigenTestCase(APITestCase):
    """
    Eine Aufgabe laesst sich abhaken - und wieder oeffnen.

    Anders als eine Medikamentengabe ist das kein Nachweis einer Handlung am
    Kind, sondern eine Merkliste. Wer sich vertut, hakt wieder ab.
    """

    def setUp(self):
        self.client = APIClient()
        self.konto = User.objects.create_user(
            username="fach", password="testpass123",
            first_name="Mara", last_name="Ott",
        )
        self.gruppe = Group.objects.create(
            name="Ahorn", address="A", postalcode="11111", city="Hier"
        )
        self.gruppe.group_members.add(self.konto)
        self.protokoll = Protocol.objects.create(
            group=self.gruppe, protocol_date=date(2026, 3, 4)
        )
        self.aufgabe = ProtocolTodo.objects.create(
            protocol=self.protokoll,
            what="Zahnarzttermin machen",
            who="Mara",
            when=timezone.now() - timedelta(days=5),
        )
        self.client.force_authenticate(user=self.konto)

    def pfad(self):
        return (
            f"/api/v1/protocol/{self.protokoll.id}/todo/{self.aufgabe.id}/"
        )

    def test_offen_und_ueberfaellig(self):
        self.assertFalse(self.aufgabe.is_done)
        self.assertTrue(self.aufgabe.is_overdue)

    def test_abhaken(self):
        antwort = self.client.patch(
            self.pfad(), {"done_at": timezone.now().isoformat()}, format="json"
        )
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        self.assertTrue(antwort.data["is_done"])
        self.assertEqual(antwort.data["done_by"], "Mara Ott")

    def test_erledigt_ist_nicht_mehr_ueberfaellig(self):
        """Der ganze Fehler: ohne Erledigt-Feld blieb jede Aufgabe rot."""
        self.client.patch(
            self.pfad(), {"done_at": timezone.now().isoformat()}, format="json"
        )
        self.aufgabe.refresh_from_db()
        self.assertFalse(self.aufgabe.is_overdue)

    def test_wieder_oeffnen_nimmt_den_namen_mit(self):
        self.client.patch(
            self.pfad(), {"done_at": timezone.now().isoformat()}, format="json"
        )
        antwort = self.client.patch(self.pfad(), {"done_at": None}, format="json")
        self.assertFalse(antwort.data["is_done"])
        self.assertEqual(antwort.data["done_by"], "")

    def test_wer_abgehakt_hat_kommt_aus_der_anmeldung(self):
        antwort = self.client.patch(
            self.pfad(),
            {"done_at": timezone.now().isoformat(), "done_by": "Jemand anders"},
            format="json",
        )
        self.assertEqual(antwort.data["done_by"], "Mara Ott")


class MedikationImProtokollTestCase(APITestCase):
    """
    Die Medikation als fester Baustein der Teambesprechung.

    Eingefroren und nicht live: ein Protokoll ist ein Nachweis, und im
    Protokoll vom Maerz darf nicht die Lage vom September stehen.
    """

    def setUp(self):
        self.gruppe = Group.objects.create(
            name="Ahorn", address="A", postalcode="11111", city="Hier"
        )
        self.kind = Resident.objects.create(
            first_name="Tim", last_name="Ostermann",
            group=self.gruppe, moved_in_since=date(2024, 1, 1),
        )
        self.medikament = Medication.objects.create(
            resident=self.kind,
            agent="Methylphenidat",
            dose="1 Kapsel",
            times=["07:30"],
            valid_from=date.today() - timedelta(days=30),
            note="zum Frühstück",
        )

        self.vorlage = ProtocolTemplate.objects.create(name="Teambesprechung")
        ProtocolTemplateItem.objects.create(
            template=self.vorlage, name="Medikation", kind="medication", position=0
        )

    def test_uebersicht_enthaelt_das_laufende_medikament(self):
        daten = medikationsuebersicht(self.gruppe)
        self.assertEqual(len(daten["rows"]), 1)
        zeile = daten["rows"][0]
        self.assertEqual(zeile[0], "Tim Ostermann")
        self.assertEqual(zeile[1], "Methylphenidat")
        self.assertIn("07:30", zeile[3])
        self.assertEqual(daten["stand"], date.today().isoformat())

    def test_beendetes_medikament_faellt_raus(self):
        self.medikament.valid_to = date.today() - timedelta(days=1)
        self.medikament.save()
        self.assertEqual(len(medikationsuebersicht(self.gruppe)["rows"]), 0)

    def test_ausgezogene_person_faellt_raus(self):
        self.kind.moved_out_since = date.today() - timedelta(days=2)
        self.kind.save()
        self.assertEqual(len(medikationsuebersicht(self.gruppe)["rows"]), 0)

    def test_nach_bedarf_steht_bei_den_zeiten(self):
        Medication.objects.create(
            resident=self.kind, agent="Ibuprofen", dose="200 mg",
            times=[], as_needed=True, valid_from=date.today(),
        )
        zeiten = {
            zeile[1]: zeile[3] for zeile in medikationsuebersicht(self.gruppe)["rows"]
        }
        self.assertEqual(zeiten["Ibuprofen"], "nach Bedarf")

    def test_protokoll_aus_der_vorlage_traegt_den_plan(self):
        protokoll = Protocol.objects.create(
            group=self.gruppe, protocol_date=date.today(), template=self.vorlage
        )
        punkt = protokoll.items.get(kind="medication")
        self.assertEqual(len(punkt.data["rows"]), 1)
        self.assertEqual(punkt.data["rows"][0][1], "Methylphenidat")

    def test_der_plan_bleibt_stehen(self):
        """
        Der wichtigste Fall. Aendert sich die Verordnung danach, darf das
        alte Protokoll davon nichts mitbekommen - sonst laesst sich nicht
        mehr sagen, was das Team damals vor sich hatte.
        """
        protokoll = Protocol.objects.create(
            group=self.gruppe, protocol_date=date.today(), template=self.vorlage
        )
        self.medikament.dose = "2 Kapseln"
        self.medikament.save()

        punkt = protokoll.items.get(kind="medication")
        punkt.refresh_from_db()
        self.assertEqual(punkt.data["rows"][0][2], "1 Kapsel")

    def test_gruppe_ohne_medikation(self):
        Medication.objects.all().delete()
        protokoll = Protocol.objects.create(
            group=self.gruppe, protocol_date=date.today(), template=self.vorlage
        )
        punkt = protokoll.items.get(kind="medication")
        self.assertEqual(punkt.data["rows"], [])
        self.assertEqual(len(punkt.data["columns"]), 5)

    def test_fremde_gruppe_steht_nicht_drin(self):
        andere = Group.objects.create(
            name="Birke", address="B", postalcode="22222", city="Dort"
        )
        nachbar = Resident.objects.create(
            first_name="Jon", last_name="Nachbar",
            group=andere, moved_in_since=date(2024, 1, 1),
        )
        Medication.objects.create(
            resident=nachbar, agent="Fremd", dose="1", valid_from=date.today()
        )
        namen = {zeile[0] for zeile in medikationsuebersicht(self.gruppe)["rows"]}
        self.assertNotIn("Jon Nachbar", namen)


class TagesprotokollVorlageTestCase(APITestCase):
    """
    Die Vorlage fuer den Alltag - und dass sie vorn steht.

    Gruppenabend, Teambesprechung und Fallbesprechung sind Termine. Das
    Tagesprotokoll ist die Schicht selbst und wird am haeufigsten
    geschrieben; es stand als einziges nicht zur Auswahl.
    """

    def test_vorlage_ist_da_und_steht_vorn(self):
        vorlagen = list(
            ProtocolTemplate.objects.filter(group__isnull=True).order_by("position")
        )
        self.assertEqual(vorlagen[0].name, "Tagesprotokoll")
        self.assertEqual(vorlagen[1].name, "Teambesprechung")

    def test_medikation_ist_ein_eigener_baustein(self):
        vorlage = ProtocolTemplate.objects.get(
            name="Tagesprotokoll", group__isnull=True
        )
        self.assertTrue(vorlage.items.filter(kind="medication").exists())

    def test_aufbau_folgt_dem_dienst(self):
        """Erst die Uebergabe, zuletzt was offen bleibt."""
        vorlage = ProtocolTemplate.objects.get(
            name="Tagesprotokoll", group__isnull=True
        )
        namen = list(vorlage.items.order_by("position").values_list("name", flat=True))
        self.assertEqual(namen[0], "Übergabe")
        self.assertEqual(namen[-1], "Offen für die nächste Schicht")

    def test_protokoll_daraus_traegt_die_medikation(self):
        gruppe = Group.objects.create(
            name="Ahorn", address="A", postalcode="11111", city="Hier"
        )
        kind = Resident.objects.create(
            first_name="Tim", last_name="Ostermann",
            group=gruppe, moved_in_since=date(2024, 1, 1),
        )
        Medication.objects.create(
            resident=kind, agent="Methylphenidat", dose="1 Kapsel",
            times=["07:30"], valid_from=date.today(),
        )
        vorlage = ProtocolTemplate.objects.get(
            name="Tagesprotokoll", group__isnull=True
        )
        protokoll = Protocol.objects.create(
            group=gruppe, protocol_date=date.today(), template=vorlage
        )
        punkt = protokoll.items.get(kind="medication")
        self.assertEqual(punkt.data["rows"][0][1], "Methylphenidat")


class MedikationReihenfolgeTestCase(APITestCase):
    """
    Medikation steht vor "Gruppe und einzelne Bewohner".

    Keine Kosmetik: erst sieht das Team, was gegeben wird, dann redet es
    ueber die Kinder. Andersherum ist die Medikation der Anhang, den man
    liest, wenn die Zeit reicht.
    """

    def test_in_der_teambesprechung(self):
        vorlage = ProtocolTemplate.objects.get(
            name="Teambesprechung", group__isnull=True
        )
        namen = list(
            vorlage.items.order_by("position").values_list("name", flat=True)
        )
        self.assertLess(namen.index("Medikation"), namen.index("Gruppe und einzelne Bewohner"))

    def test_positionen_sind_luecklos(self):
        """
        Der Fehler aus 0036 war ein Verschieben waehrend der Abfrage. Ein
        Loch oder eine doppelte Position faellt sonst niemandem auf.
        """
        for name in ("Teambesprechung", "Tagesprotokoll"):
            vorlage = ProtocolTemplate.objects.get(name=name, group__isnull=True)
            plaetze = list(
                vorlage.items.order_by("position").values_list("position", flat=True)
            )
            self.assertEqual(plaetze, list(range(len(plaetze))), name)
