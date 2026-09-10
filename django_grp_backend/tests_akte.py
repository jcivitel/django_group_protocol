"""
Die uebrige Bewohnerakte: Abwesenheit, Medikation, Vorkommnisse,
Checkliste, Barbetrag.

Geprueft wird, was schiefgehen kann und teuer waere: ein Nachweis, der sich
nachtraeglich aendern laesst, ein Medikament, das an der falschen Person
haengt, eine Gruppe, die in die Akten der Nachbargruppe sieht.
"""

from datetime import date, datetime, timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from django_grp_backend.models import (
    ChecklistItem,
    Group,
    Incident,
    Medication,
    MedicationAdministration,
    PocketMoneyEntry,
    Resident,
    ResidentAbsence,
)


def eintraege(antwort):
    """Die Zeilen einer Listenantwort, seitenweise oder nicht."""
    daten = antwort.data
    if isinstance(daten, dict) and "results" in daten:
        return daten["results"]
    return daten


class AkteBasis(APITestCase):
    """Zwei Gruppen, zwei Konten, ein Kind - der immer gleiche Aufbau."""

    def setUp(self):
        self.client = APIClient()
        self.fachkraft = User.objects.create_user(
            username="fach", password="testpass123", first_name="Mara", last_name="Ott"
        )
        self.fremde = User.objects.create_user(
            username="fremd", password="testpass123"
        )

        self.gruppe = Group.objects.create(
            name="Haus Ahorn", address="A", postalcode="11111", city="Hier"
        )
        self.andere = Group.objects.create(
            name="Haus Birke", address="B", postalcode="22222", city="Dort"
        )
        self.gruppe.group_members.add(self.fachkraft)
        self.andere.group_members.add(self.fremde)

        self.kind = Resident.objects.create(
            first_name="Nele",
            last_name="Beispiel",
            moved_in_since=date(2024, 1, 1),
            group=self.gruppe,
        )
        self.client.force_authenticate(user=self.fachkraft)


class AbwesenheitTestCase(AkteBasis):
    """
    An- und Abwesenheit.

    Zwei Fragen an denselben Zeilen: ist das Kind heute Nacht da, und rechnet
    der Tag als belegt.
    """

    def anlegen(self, **felder):
        daten = {
            "kind": "home",
            "start_date": date.today().isoformat(),
            "counts_as_occupied": True,
        }
        daten.update(felder)
        return self.client.post(
            f"/api/v1/resident/{self.kind.id}/absence/", daten, format="json"
        )

    def test_anlegen_und_lesen(self):
        antwort = self.anlegen(note="Wochenende bei der Mutter")
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)
        self.assertEqual(antwort.data["kind_display"], "Heimfahrt")
        self.assertTrue(antwort.data["is_running"])

    def test_offene_abwesenheit_laeuft_noch(self):
        """Ohne Enddatum laeuft sie - das ist der Alltagsfall am Freitag."""
        eintrag = ResidentAbsence.objects.create(
            resident=self.kind, kind="clinic", start_date=date.today() - timedelta(days=3)
        )
        self.assertTrue(eintrag.is_running)

    def test_abgeschlossene_abwesenheit_laeuft_nicht_mehr(self):
        eintrag = ResidentAbsence.objects.create(
            resident=self.kind,
            kind="home",
            start_date=date.today() - timedelta(days=9),
            end_date=date.today() - timedelta(days=7),
        )
        self.assertFalse(eintrag.is_running)

    def test_bewohner_kommt_aus_der_url(self):
        """
        Eine mitgeschickte Bewohnernummer darf nicht greifen - sonst legt
        jemand eine Abwesenheit in der Nachbargruppe an.
        """
        nachbar = Resident.objects.create(
            first_name="Jon",
            last_name="Nachbar",
            moved_in_since=date(2024, 1, 1),
            group=self.andere,
        )
        antwort = self.anlegen(resident=nachbar.id)
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)
        self.assertEqual(antwort.data["resident"], self.kind.id)

    def test_fremde_gruppe_sieht_nichts(self):
        self.anlegen()
        self.client.force_authenticate(user=self.fremde)
        antwort = self.client.get(f"/api/v1/resident/{self.kind.id}/absence/")
        self.assertEqual(len(eintraege(antwort)), 0)


class MedikationTestCase(AkteBasis):
    """
    Der Medikationsplan und der Nachweis der Gabe.

    Hier sitzt die strengste Regel der ganzen Anwendung: eine eingetragene
    Gabe bleibt stehen. Wer sie berichtigen muss, legt eine neue Zeile an.
    """

    def setUp(self):
        super().setUp()
        self.medikament = Medication.objects.create(
            resident=self.kind,
            agent="Methylphenidat",
            product="Medikinet retard 20 mg",
            dose="1 Kapsel",
            times=["07:30"],
            prescribed_by="Dr. Linde, Kinderarztpraxis am Markt",
            valid_from=date.today() - timedelta(days=30),
        )

    def test_plan_lesen(self):
        antwort = self.client.get(f"/api/v1/resident/{self.kind.id}/medication/")
        zeilen = eintraege(antwort)
        self.assertEqual(len(zeilen), 1)
        self.assertTrue(zeilen[0]["is_current"])
        self.assertEqual(zeilen[0]["times"], ["07:30"])

    def test_abgelaufenes_medikament_ist_nicht_aktuell(self):
        alt = Medication.objects.create(
            resident=self.kind,
            agent="Ibuprofen",
            dose="200 mg",
            valid_from=date.today() - timedelta(days=40),
            valid_to=date.today() - timedelta(days=10),
        )
        self.assertFalse(alt.is_current)

    def test_gabe_traegt_den_namen_aus_der_anmeldung(self):
        """
        Wer eintraegt, steht im Nachweis - und zwar nicht, weil er es
        hingeschrieben hat.
        """
        antwort = self.client.post(
            f"/api/v1/resident/{self.kind.id}/administration/",
            {
                "medication": self.medikament.id,
                "scheduled_for": timezone.now().isoformat(),
                "given_at": timezone.now().isoformat(),
                "amount": "1 Kapsel",
                "given_by_name": "Jemand anders",
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)
        self.assertEqual(antwort.data["given_by_name"], "Mara Ott")
        self.assertEqual(antwort.data["given_by"], self.fachkraft.id)

    def test_gabe_laesst_sich_nicht_aendern(self):
        gabe = MedicationAdministration.objects.create(
            medication=self.medikament,
            scheduled_for=timezone.now(),
            given_at=timezone.now(),
            given_by=self.fachkraft,
            given_by_name="Mara Ott",
        )
        gabe.amount = "2 Kapseln"
        with self.assertRaises(ValueError):
            gabe.save()

    def test_gabe_laesst_sich_nicht_loeschen(self):
        gabe = MedicationAdministration.objects.create(
            medication=self.medikament,
            scheduled_for=timezone.now(),
            given_at=timezone.now(),
        )
        with self.assertRaises(ValueError):
            gabe.delete()

    def test_kein_put_und_kein_delete_auf_der_route(self):
        gabe = MedicationAdministration.objects.create(
            medication=self.medikament,
            scheduled_for=timezone.now(),
            given_at=timezone.now(),
        )
        pfad = f"/api/v1/resident/{self.kind.id}/administration/{gabe.id}/"
        self.assertEqual(
            self.client.put(pfad, {}, format="json").status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.delete(pfad).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def test_berichtigung_laeuft_ueber_eine_neue_zeile(self):
        erste = MedicationAdministration.objects.create(
            medication=self.medikament,
            scheduled_for=timezone.now(),
            given_at=timezone.now(),
            amount="1 Kapsel",
        )
        antwort = self.client.post(
            f"/api/v1/resident/{self.kind.id}/administration/",
            {
                "medication": self.medikament.id,
                "scheduled_for": timezone.now().isoformat(),
                "given_at": timezone.now().isoformat(),
                "amount": "eine halbe Kapsel",
                "reason": "Dosis falsch eingetragen",
                "corrects": erste.id,
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)
        self.assertEqual(antwort.data["corrects"], erste.id)
        self.assertEqual(MedicationAdministration.objects.count(), 2)

    def test_ausgelassene_gabe_braucht_einen_grund(self):
        antwort = self.client.post(
            f"/api/v1/resident/{self.kind.id}/administration/",
            {
                "medication": self.medikament.id,
                "scheduled_for": timezone.now().isoformat(),
                "skipped": True,
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("reason", antwort.data)

    def test_gabe_zu_fremdem_medikament_wird_abgewiesen(self):
        """
        Die Nummer des Medikaments steht im Rumpf der Anfrage. Niemand hat
        sie geprueft - also hier.
        """
        nachbar = Resident.objects.create(
            first_name="Jon",
            last_name="Nachbar",
            moved_in_since=date(2024, 1, 1),
            group=self.andere,
        )
        fremdes = Medication.objects.create(
            resident=nachbar, agent="Fremd", dose="1", valid_from=date.today()
        )
        antwort = self.client.post(
            f"/api/v1/resident/{self.kind.id}/administration/",
            {
                "medication": fremdes.id,
                "scheduled_for": timezone.now().isoformat(),
                "given_at": timezone.now().isoformat(),
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)

    def test_fremde_gruppe_sieht_den_plan_nicht(self):
        self.client.force_authenticate(user=self.fremde)
        antwort = self.client.get(f"/api/v1/resident/{self.kind.id}/medication/")
        self.assertEqual(len(eintraege(antwort)), 0)


class VorkommnisTestCase(AkteBasis):
    """
    Besondere Vorkommnisse nach § 47 SGB VIII.

    Haengt an der Gruppe, nicht am Bewohner: ein Brand betrifft alle.
    """

    def anlegen(self, **felder):
        daten = {
            "group": self.gruppe.id,
            "kind": "absence",
            "occurred_at": timezone.now().isoformat(),
            "description": "Nele ist gegen 22 Uhr nicht zurueckgekehrt.",
        }
        daten.update(felder)
        return self.client.post("/api/v1/incident/", daten, format="json")

    def test_anlegen_und_lesen(self):
        antwort = self.anlegen(resident=self.kind.id)
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)
        self.assertEqual(antwort.data["kind_display"], "Unerlaubte Abwesenheit")
        self.assertEqual(antwort.data["resident_name"], "Nele Beispiel")
        self.assertEqual(antwort.data["recorded_by_name"], "Mara Ott")

    def test_ohne_person_geht(self):
        """Ein Vorkommnis ohne Zuordnung ist der Normalfall, nicht der Fehler."""
        antwort = self.anlegen(kind="accident", description="Wasserschaden im Bad.")
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(antwort.data["resident"])
        self.assertEqual(antwort.data["resident_name"], "")

    def test_offen_und_unmeldet_faellt_auf(self):
        antwort = self.anlegen()
        self.assertTrue(antwort.data["needs_report"])

        gemeldet = Incident.objects.get(id=antwort.data["id"])
        gemeldet.status = "reported"
        gemeldet.reported_to = "Landesjugendamt"
        gemeldet.reported_at = timezone.now()
        gemeldet.save()
        self.assertFalse(gemeldet.needs_report)

    def test_nur_eigene_gruppen(self):
        Incident.objects.create(
            group=self.andere,
            kind="other",
            occurred_at=timezone.now(),
            description="Nicht meine Gruppe.",
        )
        self.anlegen()
        antwort = self.client.get("/api/v1/incident/")
        zeilen = eintraege(antwort)
        self.assertEqual(len(zeilen), 1)
        self.assertEqual(zeilen[0]["group"], self.gruppe.id)

    def test_nach_bewohner_filtern(self):
        self.anlegen(resident=self.kind.id)
        self.anlegen(kind="accident", description="Wasserschaden.")
        antwort = self.client.get(f"/api/v1/incident/?bewohner={self.kind.id}")
        self.assertEqual(len(eintraege(antwort)), 1)

    def test_fremde_gruppe_beim_anlegen_wird_abgewiesen(self):
        antwort = self.anlegen(group=self.andere.id)
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)

    def test_fremde_person_beim_anlegen_wird_abgewiesen(self):
        """
        Die eigene Gruppe genuegt nicht: auch `resident` kommt aus dem Rumpf
        der Anfrage.
        """
        nachbar = Resident.objects.create(
            first_name="Jon",
            last_name="Nachbar",
            moved_in_since=date(2024, 1, 1),
            group=self.andere,
        )
        antwort = self.anlegen(resident=nachbar.id)
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)


class ChecklisteTestCase(AkteBasis):
    """Aufnahme und Entlassung - abhakbar, damit man sieht, was offen ist."""

    def anlegen(self, **felder):
        daten = {"kind": "admission", "title": "Krankenversicherungskarte"}
        daten.update(felder)
        return self.client.post(
            f"/api/v1/resident/{self.kind.id}/checklist/", daten, format="json"
        )

    def test_anlegen_und_abhaken(self):
        antwort = self.anlegen()
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(antwort.data["done_on"])

        punkt = antwort.data["id"]
        erledigt = self.client.patch(
            f"/api/v1/resident/{self.kind.id}/checklist/{punkt}/",
            {"done_on": date.today().isoformat(), "done_by": "Mara Ott"},
            format="json",
        )
        self.assertEqual(erledigt.status_code, status.HTTP_200_OK)
        self.assertEqual(erledigt.data["done_on"], date.today().isoformat())

    def test_reihenfolge_nach_art_und_position(self):
        ChecklistItem.objects.create(
            resident=self.kind, kind="discharge", title="Zeugnis", position=0
        )
        ChecklistItem.objects.create(
            resident=self.kind, kind="admission", title="Zweites", position=1
        )
        ChecklistItem.objects.create(
            resident=self.kind, kind="admission", title="Erstes", position=0
        )
        antwort = self.client.get(f"/api/v1/resident/{self.kind.id}/checklist/")
        titel = [zeile["title"] for zeile in eintraege(antwort)]
        self.assertEqual(titel, ["Erstes", "Zweites", "Zeugnis"])


class BarbetragTestCase(AkteBasis):
    """
    Der Barbetrag nach § 39 SGB VIII.

    Kein gespeicherter Saldo: der Stand ist die Summe der Buchungen.
    """

    def buchen(self, **felder):
        daten = {
            "date": date.today().isoformat(),
            "kind": "payout",
            "amount": "15.00",
        }
        daten.update(felder)
        return self.client.post(
            f"/api/v1/resident/{self.kind.id}/pocket-money/", daten, format="json"
        )

    def test_gutschrift_und_auszahlung_rechnen_gegeneinander(self):
        self.buchen(kind="credit", amount="40.00", note="Monat Maerz")
        self.buchen(kind="payout", amount="15.00", note="Kino")
        stand = sum(
            eintrag.signed_amount
            for eintrag in PocketMoneyEntry.objects.filter(resident=self.kind)
        )
        self.assertEqual(str(stand), "25.00")

    def test_vorzeichen_steht_in_der_antwort(self):
        antwort = self.buchen(kind="payout", amount="15.00")
        self.assertEqual(antwort.data["signed_amount"], "-15.00")
        self.assertEqual(antwort.data["kind_display"], "Auszahlung")

    def test_wer_gebucht_hat_kommt_aus_der_anmeldung(self):
        antwort = self.buchen(recorded_by="Jemand anders")
        self.assertEqual(antwort.data["recorded_by"], "Mara Ott")

    def test_fremde_gruppe_sieht_nichts(self):
        self.buchen()
        self.client.force_authenticate(user=self.fremde)
        antwort = self.client.get(f"/api/v1/resident/{self.kind.id}/pocket-money/")
        self.assertEqual(len(eintraege(antwort)), 0)


class SchuleTestCase(AkteBasis):
    """Schule steht in der Akte, nicht im Kopf der Bezugsbetreuung."""

    def test_felder_lassen_sich_pflegen(self):
        antwort = self.client.patch(
            f"/api/v1/resident/{self.kind.id}/",
            {
                "school": "Gesamtschule Nordstadt",
                "school_class": "7b",
                "school_contact": "Frau Harms, Klassenleitung",
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        self.assertEqual(antwort.data["school_class"], "7b")
