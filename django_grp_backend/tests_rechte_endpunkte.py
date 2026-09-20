"""
Greift die Rechtematrix an den Endpunkten, die sie vorher nicht erreichte?

Die Matrix führt achtzehn Zeilen. Bis zum 13. September 2026 setzte
`WriteNeedsRole` an jedem Endpunkt dasselbe durch — `Protokolle` schreiben —
und die Stammdaten hingen sämtlich an `Organisation`. Wer also *Dienstplan:
kein Zugriff* setzte, nahm einen Knopf weg und kein Recht.

Dieses Modul prüft je Zeile das Paar, auf das es ankommt:

  * das Merkmal auf „kein Zugriff", das Recht auf Protokolle auf „schreiben"
    — der Endpunkt muss trotzdem ablehnen,
  * und umgekehrt das Merkmal allein, ohne Protokolle — der Endpunkt muss
    durchlassen.

Nur das zweite Paar beweist etwas. Ein Test, der nur sperrt, ist auch mit
einem Endpunkt zufrieden, der alles sperrt.

Geprüft wird gegen die echten Adressen und nicht gegen `darf()`. Die
Funktion war nie das Problem.
"""

from datetime import date, timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from django_grp_backend import rechte, zweitfaktor
from django_grp_backend.models import Group, Rechtezuweisung, Resident, ZweiterFaktor
from django_grp_care.models import CaseFile
from django_grp_duty.models import (
    Absence,
    AbsenceType,
    DutyPlan,
    ShiftType,
    TimeEntry,
)
from django_grp_org.models import (
    Department,
    Employee,
    Facility,
    Provider,
    Site,
    WorkTimeModel,
)


def setze(user, **merkmale):
    """Setzt eine vollstaendige Matrix; alles Ungenannte ist kein Zugriff."""
    for aktion in rechte.ALLE_AKTIONEN:
        Rechtezuweisung.objects.update_or_create(
            user=user,
            aktion=aktion,
            defaults={"stufe": merkmale.get(aktion, rechte.KEIN)},
        )


def zeilen(antwort):
    """
    Die Datensaetze einer Listenantwort, mit oder ohne Blaetterung.

    Manche Endpunkte blaettern und liefern `{"results": [...]}`, andere die
    Liste selbst. Ein Test, der das verwechselt, scheitert mit einem
    TypeError und sieht aus wie ein Rechtefehler.
    """
    daten = antwort.data
    if isinstance(daten, dict) and "results" in daten:
        return daten["results"]
    return daten


def mit_faktor(user):
    """Ein bestaetigter zweiter Faktor - fuer die Stammdatenendpunkte."""
    eintrag = ZweiterFaktor(user=user, bestaetigt_am=timezone.now())
    eintrag.geheimnis = zweitfaktor.geheimnis_erzeugen()
    eintrag.save()
    return eintrag


class EndpunktBasis(APITestCase):
    """Ein Träger, ein Haus, eine Gruppe, eine Fachkraft, ein Kind."""

    def setUp(self):
        self.client = APIClient()
        self.traeger = Provider.objects.create(name="Wegzeichen")
        self.standort = Site.objects.create(provider=self.traeger, name="Nord")
        self.haus = Facility.objects.create(site=self.standort, name="Haus Ahorn")

        self.gruppe = Group.objects.create(
            name="Ahorn 1", address="A 1", postalcode="11111", city="Hier"
        )
        self.bereich = Department.objects.create(
            facility=self.haus, name="Wohngruppe 1", group=self.gruppe
        )

        self.fachkraft = User.objects.create_user(
            username="fach", password="testpass123", first_name="Mara", last_name="Ott"
        )
        self.personal = Employee.objects.create(
            user=self.fachkraft,
            provider=self.traeger,
            first_name="Mara",
            last_name="Ott",
            hired_on=date(2024, 1, 1),
            access_level="specialist",
        )
        self.gruppe.group_members.add(self.fachkraft)

        self.kind = Resident.objects.create(
            first_name="Nele",
            last_name="Beispiel",
            moved_in_since=date(2024, 1, 1),
            group=self.gruppe,
        )

        self.client.force_authenticate(user=self.fachkraft)


class DienstplanTestCase(EndpunktBasis):
    """
    Die Zeile *Dienstplan*.

    Vorher: `require_staff(self.request)`. Eine Bereichsleitung ohne den
    Django-Schalter kam nicht an den Plan, ein Konto mit dem Schalter kam
    immer hinein.
    """

    def plan_anlegen(self):
        return self.client.post(
            "/api/v1/duty-plan/",
            {"department": self.bereich.id, "year": 2026, "month": 10},
            format="json",
        )

    def test_ohne_dienstplanrecht_kein_plan(self):
        setze(self.fachkraft, **{rechte.PROTOKOLLE: rechte.SCHREIBEN})
        self.assertEqual(
            self.plan_anlegen().status_code, status.HTTP_403_FORBIDDEN
        )
        self.assertFalse(DutyPlan.objects.exists())

    def test_mit_dienstplanrecht_schon(self):
        """Und ausdruecklich ohne das Recht auf Protokolle."""
        setze(self.fachkraft, **{rechte.DIENSTPLAN_BEARBEITEN: rechte.SCHREIBEN})
        self.assertEqual(
            self.plan_anlegen().status_code, status.HTTP_201_CREATED
        )

    def test_freigeben_ist_eine_eigene_zeile(self):
        """
        Wer den Plan baut, macht ihn nicht zwangsläufig verbindlich. Nach der
        Freigabe sehen ihn alle.
        """
        setze(self.fachkraft, **{rechte.DIENSTPLAN_BEARBEITEN: rechte.SCHREIBEN})
        plan = DutyPlan.objects.create(
            department=self.bereich, year=2026, month=10, status="draft"
        )

        antwort = self.client.patch(
            f"/api/v1/duty-plan/{plan.id}/",
            {"status": "published"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)
        plan.refresh_from_db()
        self.assertEqual(plan.status, "draft")

    def test_mit_freigaberecht_geht_es(self):
        setze(
            self.fachkraft,
            **{
                rechte.DIENSTPLAN_BEARBEITEN: rechte.SCHREIBEN,
                rechte.DIENSTPLAN_FREIGEBEN: rechte.SCHREIBEN,
            },
        )
        plan = DutyPlan.objects.create(
            department=self.bereich, year=2026, month=10, status="draft"
        )

        antwort = self.client.patch(
            f"/api/v1/duty-plan/{plan.id}/",
            {"status": "published"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        plan.refresh_from_db()
        self.assertEqual(plan.status, "published")

    def test_dienstarten_haengen_an_ihrer_eigenen_zeile(self):
        setze(self.fachkraft, **{rechte.DIENSTPLAN_BEARBEITEN: rechte.SCHREIBEN})
        antwort = self.client.post(
            "/api/v1/shift-type/",
            {
                "provider": self.traeger.id,
                "name": "Frühdienst",
                "short_code": "F",
                "start_time": "06:00",
                "end_time": "14:00",
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)

        setze(self.fachkraft, **{rechte.ORG_DIENSTARTEN: rechte.SCHREIBEN})
        antwort = self.client.post(
            "/api/v1/shift-type/",
            {
                "provider": self.traeger.id,
                "name": "Frühdienst",
                "short_code": "F",
                "start_time": "06:00",
                "end_time": "14:00",
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)


class AbwesenheitTestCase(EndpunktBasis):
    """
    Die Zeile *Abwesenheiten*.

    Sie entscheidet zweierlei: wer entscheidet, und wer fremde Anträge
    überhaupt sieht. Das zweite ist der empfindlichere Teil — eine
    Krankmeldung ist ein Gesundheitsdatum (Art. 9 DSGVO).
    """

    def setUp(self):
        super().setUp()
        self.art = AbsenceType.objects.create(
            provider=self.traeger, name="Urlaub", kind="vacation"
        )
        self.kollegin = User.objects.create_user(
            username="koll", password="testpass123"
        )
        self.kollegin_personal = Employee.objects.create(
            user=self.kollegin,
            provider=self.traeger,
            first_name="Tomke",
            last_name="Spreen",
            hired_on=date(2024, 1, 1),
            access_level="specialist",
        )
        self.fremder_antrag = Absence.objects.create(
            employee=self.kollegin_personal,
            absence_type=self.art,
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 5),
            status="requested",
        )

    def test_eigene_antraege_brauchen_kein_merkmal(self):
        """
        Sonst könnte eine Aushilfe keinen Urlaub beantragen - und das ist
        keine Rechtefrage, sondern eine Arbeitnehmerin mit einem Anliegen.
        """
        setze(self.fachkraft)  # alles auf kein Zugriff

        antwort = self.client.post(
            "/api/v1/absence/",
            {
                "employee": self.personal.id,
                "absence_type": self.art.id,
                "start_date": "2026-11-02",
                "end_date": "2026-11-06",
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)
        self.assertEqual(antwort.data["status"], "requested")

    def test_fremde_antraege_bleiben_unsichtbar(self):
        setze(self.fachkraft, **{rechte.PROTOKOLLE: rechte.SCHREIBEN})

        antwort = self.client.get("/api/v1/absence/")
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        nummern = [zeile["id"] for zeile in zeilen(antwort)]
        self.assertNotIn(self.fremder_antrag.id, nummern)

    def test_mit_dem_merkmal_sind_sie_sichtbar(self):
        setze(self.fachkraft, **{rechte.ABWESENHEIT_GENEHMIGEN: rechte.LESEN})

        antwort = self.client.get("/api/v1/absence/")
        nummern = [zeile["id"] for zeile in zeilen(antwort)]
        self.assertIn(self.fremder_antrag.id, nummern)

    def test_lesen_genuegt_nicht_zum_entscheiden(self):
        setze(self.fachkraft, **{rechte.ABWESENHEIT_GENEHMIGEN: rechte.LESEN})

        antwort = self.client.patch(
            f"/api/v1/absence/{self.fremder_antrag.id}/",
            {"status": "approved"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)
        self.fremder_antrag.refresh_from_db()
        self.assertEqual(self.fremder_antrag.status, "requested")

    def test_mit_schreibrecht_wird_entschieden(self):
        setze(self.fachkraft, **{rechte.ABWESENHEIT_GENEHMIGEN: rechte.SCHREIBEN})

        antwort = self.client.patch(
            f"/api/v1/absence/{self.fremder_antrag.id}/",
            {"status": "approved"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        self.fremder_antrag.refresh_from_db()
        self.assertEqual(self.fremder_antrag.status, "approved")
        self.assertIsNotNone(self.fremder_antrag.decided_at)

    def test_niemand_genehmigt_sich_selbst(self):
        setze(self.fachkraft)
        eigener = Absence.objects.create(
            employee=self.personal,
            absence_type=self.art,
            start_date=date(2026, 12, 1),
            end_date=date(2026, 12, 5),
            status="requested",
        )

        antwort = self.client.patch(
            f"/api/v1/absence/{eigener.id}/",
            {"status": "approved"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)


class ZeitTestCase(EndpunktBasis):
    """Die Zeilen *Zeiterfassung* und *Zeitkonten abschließen*."""

    def setUp(self):
        super().setUp()
        self.kollegin_personal = Employee.objects.create(
            provider=self.traeger,
            first_name="Tomke",
            last_name="Spreen",
            hired_on=date(2024, 1, 1),
            access_level="specialist",
        )
        self.fremde_buchung = TimeEntry.objects.create(
            employee=self.kollegin_personal,
            date=date(2026, 9, 1),
            start_time="08:00",
            end_time="16:00",
        )

    def test_eigene_zeit_buchen_braucht_nur_zeiterfassung(self):
        setze(self.fachkraft, **{rechte.ZEIT_ERFASSEN: rechte.SCHREIBEN})

        antwort = self.client.post(
            "/api/v1/time-entry/",
            {
                "employee": self.personal.id,
                "date": "2026-09-02",
                "start_time": "08:00",
                "end_time": "16:00",
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)

    def test_ohne_zeiterfassung_geht_nichts(self):
        setze(self.fachkraft, **{rechte.PROTOKOLLE: rechte.SCHREIBEN})

        antwort = self.client.post(
            "/api/v1/time-entry/",
            {
                "employee": self.personal.id,
                "date": "2026-09-02",
                "start_time": "08:00",
                "end_time": "16:00",
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)

    def test_fremde_buchungen_bleiben_unsichtbar(self):
        setze(self.fachkraft, **{rechte.ZEIT_ERFASSEN: rechte.SCHREIBEN})

        antwort = self.client.get("/api/v1/time-entry/")
        nummern = [zeile["id"] for zeile in zeilen(antwort)]
        self.assertNotIn(self.fremde_buchung.id, nummern)

    def test_wer_abschliesst_sieht_sie(self):
        setze(
            self.fachkraft,
            **{
                rechte.ZEIT_ERFASSEN: rechte.SCHREIBEN,
                rechte.ZEITKONTO_ABSCHLIESSEN: rechte.LESEN,
            },
        )

        antwort = self.client.get("/api/v1/time-entry/")
        nummern = [zeile["id"] for zeile in zeilen(antwort)]
        self.assertIn(self.fremde_buchung.id, nummern)

    def test_freigeben_braucht_den_abschluss(self):
        setze(self.fachkraft, **{rechte.ZEIT_ERFASSEN: rechte.SCHREIBEN})

        antwort = self.client.post(
            "/api/v1/time-approval/",
            {"entries": [self.fremde_buchung.id], "approved": True},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)
        self.fremde_buchung.refresh_from_db()
        self.assertFalse(self.fremde_buchung.approved)

    def test_mit_dem_abschluss_geht_es(self):
        setze(self.fachkraft, **{rechte.ZEITKONTO_ABSCHLIESSEN: rechte.SCHREIBEN})

        antwort = self.client.post(
            "/api/v1/time-approval/",
            {"entries": [self.fremde_buchung.id], "approved": True},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)
        self.fremde_buchung.refresh_from_db()
        self.assertTrue(self.fremde_buchung.approved)

    def test_monatsabschluss_ebenso(self):
        setze(self.fachkraft, **{rechte.ZEIT_ERFASSEN: rechte.SCHREIBEN})
        antwort = self.client.post(
            "/api/v1/time-close/", {"year": 2026, "month": 8}, format="json"
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)

    def test_die_lohnuebergabe_haengt_an_den_nachweisen(self):
        """
        Eine GET-Anfrage, und vorher genügte dafür der Django-Schalter. Die
        Antwort ist die Gehaltsabrechnung des ganzen Hauses.
        """
        setze(self.fachkraft, **{rechte.ZEIT_ERFASSEN: rechte.SCHREIBEN})
        antwort = self.client.get("/api/v1/payroll/?jahr=2026&monat=8")
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)

        setze(self.fachkraft, **{rechte.NACHWEISE: rechte.LESEN})
        antwort = self.client.get("/api/v1/payroll/?jahr=2026&monat=8")
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)


class FallakteTestCase(EndpunktBasis):
    """Die Zeile *Fallakten*, vorher am Recht auf Protokolle."""

    def test_ohne_fallaktenrecht_keine_akte(self):
        setze(self.fachkraft, **{rechte.PROTOKOLLE: rechte.SCHREIBEN})

        antwort = self.client.post(
            "/api/v1/case-file/",
            {
                "provider": self.traeger.id,
                "resident": self.kind.id,
                "opened_on": "2026-09-01",
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(CaseFile.objects.exists())

    def test_mit_fallaktenrecht_schon(self):
        setze(self.fachkraft, **{rechte.FALLAKTE: rechte.SCHREIBEN})

        antwort = self.client.post(
            "/api/v1/case-file/",
            {
                "provider": self.traeger.id,
                "resident": self.kind.id,
                "opened_on": "2026-09-01",
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)

    def test_lesen_erlaubt_das_lesen_und_nicht_das_schreiben(self):
        akte = CaseFile.objects.create(
            provider=self.traeger, resident=self.kind, opened_on=date(2026, 9, 1)
        )
        setze(self.fachkraft, **{rechte.FALLAKTE: rechte.LESEN})

        self.assertEqual(
            self.client.get(f"/api/v1/case-file/{akte.id}/").status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/v1/case-file/{akte.id}/",
                {"status": "closed"},
                format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )


class BewohnerTestCase(EndpunktBasis):
    """Die Zeile *Bewohner*, vorher ebenfalls am Recht auf Protokolle."""

    def test_protokollrecht_oeffnet_die_bewohnerakte_nicht(self):
        setze(self.fachkraft, **{rechte.PROTOKOLLE: rechte.SCHREIBEN})

        antwort = self.client.patch(
            f"/api/v1/resident/{self.kind.id}/",
            {"last_name": "Geändert"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)
        self.kind.refresh_from_db()
        self.assertEqual(self.kind.last_name, "Beispiel")

    def test_mit_bewohnerrecht_schon(self):
        setze(self.fachkraft, **{rechte.BEWOHNER: rechte.SCHREIBEN})

        antwort = self.client.patch(
            f"/api/v1/resident/{self.kind.id}/",
            {"last_name": "Geändert"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)

    def test_allergien_folgen_derselben_zeile(self):
        setze(self.fachkraft, **{rechte.PROTOKOLLE: rechte.SCHREIBEN})
        antwort = self.client.post(
            f"/api/v1/resident/{self.kind.id}/allergy/",
            {"name": "Erdnuss", "kind": "food", "severity": "severe"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)

        setze(self.fachkraft, **{rechte.BEWOHNER: rechte.SCHREIBEN})
        antwort = self.client.post(
            f"/api/v1/resident/{self.kind.id}/allergy/",
            {"name": "Erdnuss", "kind": "food", "severity": "severe"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)

    def test_gruppen_haengen_an_der_organisation(self):
        """
        Eine Gruppe zu löschen kaskadiert auf ihre Bewohner und Protokolle.
        Das ist Organisationsstruktur und nicht Bewohnerakte.
        """
        setze(self.fachkraft, **{rechte.BEWOHNER: rechte.SCHREIBEN})
        antwort = self.client.post(
            "/api/v1/group/",
            {
                "name": "Ahorn 2",
                "address": "A 2",
                "postalcode": "11111",
                "city": "Hier",
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)


class StammdatenTestCase(EndpunktBasis):
    """
    Die sechs Verwaltungszeilen, vorher alle an *Organisation*.

    Beide Richtungen waren falsch: eine Personalsachbearbeitung konnte keinen
    Vertrag eintragen, und wer Trägerdaten schreiben durfte, änderte
    Personaldatensätze und Rollenzuweisungen mit.
    """

    def setUp(self):
        super().setUp()
        mit_faktor(self.fachkraft)
        self.modell = WorkTimeModel.objects.create(
            provider=self.traeger, name="Vollzeit", weekly_hours=39
        )

    def personal_anlegen(self):
        return self.client.post(
            "/api/v1/employee/",
            {
                "provider": self.traeger.id,
                "first_name": "Neu",
                "last_name": "Eingestellt",
                "hired_on": "2026-09-01",
                "access_level": "specialist",
                "work_time_model": self.modell.id,
            },
            format="json",
        )

    def test_personalrecht_allein_genuegt(self):
        """Der Fall, der vorher scheiterte."""
        setze(self.fachkraft, **{rechte.PERSONAL_STAMMDATEN: rechte.SCHREIBEN})
        self.assertEqual(
            self.personal_anlegen().status_code, status.HTTP_201_CREATED
        )

    def test_organisationsrecht_allein_genuegt_nicht(self):
        """Der Fall, der vorher durchging."""
        setze(self.fachkraft, **{rechte.ORG_STRUKTUR: rechte.SCHREIBEN})
        self.assertEqual(
            self.personal_anlegen().status_code, status.HTTP_403_FORBIDDEN
        )

    def test_feiertage_haengen_am_kalender(self):
        setze(self.fachkraft, **{rechte.ORG_STRUKTUR: rechte.SCHREIBEN})
        antwort = self.client.post(
            "/api/v1/holiday/",
            {
                "provider": self.traeger.id,
                "date": "2026-12-25",
                "name": "1. Weihnachtstag",
                "factor": 0,
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)

        setze(self.fachkraft, **{rechte.ORG_KALENDER: rechte.SCHREIBEN})
        antwort = self.client.post(
            "/api/v1/holiday/",
            {
                "provider": self.traeger.id,
                "date": "2026-12-25",
                "name": "1. Weihnachtstag",
                "factor": 0,
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)

    def test_qualifikationen_haengen_an_ihrer_zeile(self):
        setze(self.fachkraft, **{rechte.PERSONAL_STAMMDATEN: rechte.SCHREIBEN})
        antwort = self.client.post(
            "/api/v1/qualification/",
            {"name": "Deeskalation nach Probe"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)

        setze(self.fachkraft, **{rechte.PERSONAL_QUALIFIKATION: rechte.SCHREIBEN})
        antwort = self.client.post(
            "/api/v1/qualification/",
            {"name": "Deeskalation nach Probe"},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)

    def test_rollenzuweisungen_haengen_am_vergaberecht(self):
        """
        Unter `RECHTE_QUELLE=rollen` entscheiden diese Zeilen, was jemand
        darf. Sie an *Organisation* zu hängen hieße, Rechtevergabe an
        Trägerdaten zu hängen.
        """
        setze(self.fachkraft, **{rechte.ORG_STRUKTUR: rechte.SCHREIBEN})
        antwort = self.client.post(
            "/api/v1/role/",
            {
                "employee": self.personal.id,
                "role": "facility_lead",
                "provider": self.traeger.id,
                "facility": self.haus.id,
                "valid_from": "2026-09-01",
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)

        setze(self.fachkraft, **{rechte.PERSONAL_ROLLEN: rechte.SCHREIBEN})
        antwort = self.client.post(
            "/api/v1/role/",
            {
                "employee": self.personal.id,
                "role": "facility_lead",
                "provider": self.traeger.id,
                "facility": self.haus.id,
                "valid_from": "2026-09-01",
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)

    def test_ohne_zweiten_faktor_keine_stammdaten(self):
        """
        Die Pflicht greift genau hier. Sie hält niemanden aus der Anwendung
        heraus, sondern aus den Stammdaten.
        """
        ZweiterFaktor.objects.filter(user=self.fachkraft).delete()
        setze(self.fachkraft, **{rechte.PERSONAL_STAMMDATEN: rechte.SCHREIBEN})

        self.assertEqual(
            self.personal_anlegen().status_code, status.HTTP_403_FORBIDDEN
        )


class AenderungsprotokollTestCase(EndpunktBasis):
    """
    Die Zeile *Änderungsprotokoll*.

    Vorher prüfte `get_queryset` den Django-Schalter und gab eine leere Liste
    zurück. Das sah aus wie „noch nichts passiert" und war „du darfst das
    nicht sehen".
    """

    def test_ohne_das_merkmal_403_und_nicht_leer(self):
        setze(self.fachkraft, **{rechte.PROTOKOLLE: rechte.SCHREIBEN})
        antwort = self.client.get("/api/v1/audit/")
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)

    def test_mit_dem_merkmal_sichtbar(self):
        setze(self.fachkraft, **{rechte.AENDERUNGSPROTOKOLL: rechte.LESEN})
        antwort = self.client.get("/api/v1/audit/")
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)


class KontenTestCase(EndpunktBasis):
    """
    Ein Konto mit `is_staff` anzulegen ist eine Rechtevergabe.

    Ohne Personaldatensatz leitet `access_level()` die Stufe aus diesem
    Schalter ab — „Mitarbeiter", und das heißt in der Rückfalltabelle jedes
    der achtzehn Merkmale auf schreiben. Wer nur Personal führen darf, könnte
    sich damit in zwei Schritten ein Konto mit allen Rechten bauen.
    """

    def setUp(self):
        super().setUp()
        mit_faktor(self.fachkraft)

    def konto_anlegen(self, **zusatz):
        daten = {
            "username": "neu",
            "password": "testpass123",
            "email": "neu@beispiel.de",
        }
        daten.update(zusatz)
        return self.client.post("/api/v1/admin/users/", daten, format="json")

    def test_ein_gewoehnliches_konto_darf_die_personalstelle_anlegen(self):
        setze(self.fachkraft, **{rechte.PERSONAL_STAMMDATEN: rechte.SCHREIBEN})
        antwort = self.konto_anlegen()
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)
        self.assertFalse(User.objects.get(username="neu").is_staff)

    def test_ein_verwaltungskonto_braucht_das_vergaberecht(self):
        setze(self.fachkraft, **{rechte.PERSONAL_STAMMDATEN: rechte.SCHREIBEN})
        antwort = self.konto_anlegen(is_staff=True)
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(User.objects.filter(username="neu").exists())

    def test_mit_vergaberecht_und_faktor_geht_es(self):
        setze(
            self.fachkraft,
            **{
                rechte.PERSONAL_STAMMDATEN: rechte.SCHREIBEN,
                rechte.PERSONAL_ROLLEN: rechte.SCHREIBEN,
            },
        )
        antwort = self.konto_anlegen(is_staff=True)
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.get(username="neu").is_staff)

    def test_die_kontenliste_haengt_am_personalrecht(self):
        setze(self.fachkraft, **{rechte.PROTOKOLLE: rechte.SCHREIBEN})
        self.assertEqual(
            self.client.get("/api/v1/admin/users/").status_code,
            status.HTTP_403_FORBIDDEN,
        )

        setze(self.fachkraft, **{rechte.PERSONAL_STAMMDATEN: rechte.LESEN})
        self.assertEqual(
            self.client.get("/api/v1/admin/users/").status_code,
            status.HTTP_200_OK,
        )


class ZweitfaktorPflichtTestCase(EndpunktBasis):
    """
    Die Pflicht muss genauso weit reichen wie das Recht zum Zurücksetzen.

    Sie hing an *Organisation: schreiben*. Eine Einrichtungsleitung hat nach
    der Vorlage *Organisation: lesen* und *Rechte vergeben: schreiben* — sie
    konnte die Matrix jedes Kontos setzen, hatte keine Pflicht, und
    `zweitfaktor_erfuellt` gab für sie deshalb True zurück.
    """

    def test_vergaberecht_allein_begruendet_die_pflicht(self):
        setze(self.fachkraft, **{rechte.PERSONAL_ROLLEN: rechte.SCHREIBEN})
        self.assertTrue(rechte.zweitfaktor_pflicht(self.fachkraft))
        self.assertFalse(rechte.zweitfaktor_erfuellt(self.fachkraft))

    def test_personalrecht_allein_ebenso(self):
        setze(self.fachkraft, **{rechte.PERSONAL_STAMMDATEN: rechte.SCHREIBEN})
        self.assertTrue(rechte.zweitfaktor_pflicht(self.fachkraft))

    def test_eine_reine_fachkraft_hat_keine_pflicht(self):
        setze(
            self.fachkraft,
            **{
                rechte.PROTOKOLLE: rechte.SCHREIBEN,
                rechte.BEWOHNER: rechte.SCHREIBEN,
                rechte.FALLAKTE: rechte.SCHREIBEN,
                rechte.ZEIT_ERFASSEN: rechte.SCHREIBEN,
            },
        )
        self.assertFalse(rechte.zweitfaktor_pflicht(self.fachkraft))
        self.assertTrue(rechte.zweitfaktor_erfuellt(self.fachkraft))

    def test_ohne_faktor_keine_matrix_fuer_andere(self):
        setze(self.fachkraft, **{rechte.PERSONAL_ROLLEN: rechte.SCHREIBEN})
        ziel = User.objects.create_user(username="ziel", password="testpass123")

        antwort = self.client.put(
            f"/api/v1/rechte/{ziel.id}/",
            {"rechte": {a: rechte.KEIN for a in rechte.ALLE_AKTIONEN}},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_403_FORBIDDEN)

    def test_mit_faktor_geht_es(self):
        setze(self.fachkraft, **{rechte.PERSONAL_ROLLEN: rechte.SCHREIBEN})
        mit_faktor(self.fachkraft)
        ziel = User.objects.create_user(username="ziel", password="testpass123")

        antwort = self.client.put(
            f"/api/v1/rechte/{ziel.id}/",
            {"rechte": {rechte.PROTOKOLLE: rechte.SCHREIBEN}},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_200_OK)


class SelbstschutzTestCase(EndpunktBasis):
    """
    Was am eigenen Konto nicht geht - auch als Superuser nicht.

    Entschieden am 13. September 2026: die eigenen Rechte nicht ändern, das
    eigene Konto nicht löschen. Beides wäre ein Weg, eine Beschränkung
    loszuwerden, die jemand anders gesetzt hat.
    """

    def setUp(self):
        super().setUp()
        self.root = User.objects.create_superuser(
            username="root", password="testpass123", email=""
        )
        mit_faktor(self.root)

    def test_der_superuser_loescht_sich_nicht_selbst(self):
        self.client.force_authenticate(user=self.root)
        antwort = self.client.delete(f"/api/v1/admin/users/{self.root.id}/")

        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(User.objects.filter(id=self.root.id).exists())

    def test_der_superuser_legt_sich_nicht_selbst_still(self):
        self.client.force_authenticate(user=self.root)
        antwort = self.client.put(
            f"/api/v1/admin/users/{self.root.id}/",
            {"is_active": False},
            format="json",
        )

        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)
        self.root.refresh_from_db()
        self.assertTrue(self.root.is_active)

    def test_niemand_setzt_die_eigene_matrix(self):
        self.client.force_authenticate(user=self.root)
        antwort = self.client.put(
            f"/api/v1/rechte/{self.root.id}/",
            {"rechte": {rechte.PROTOKOLLE: rechte.SCHREIBEN}},
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_400_BAD_REQUEST)


class VorratTestCase(EndpunktBasis):
    """
    Die Stellen, die jedem Konto offen bleiben müssen.

    Eine Rechteumstellung, die das eigene Profil sperrt, sperrt die
    Oberfläche aus: sie erfährt dort, welche Knöpfe sie zeichnen darf.
    """

    def test_das_eigene_profil_bleibt_offen(self):
        setze(self.fachkraft)  # alles auf kein Zugriff

        self.assertEqual(
            self.client.get("/api/v1/user/me/").status_code, status.HTTP_200_OK
        )
        self.assertEqual(
            self.client.get("/api/v1/user/profile/").status_code,
            status.HTTP_200_OK,
        )

    def test_die_eigenen_dienste_bleiben_offen(self):
        setze(self.fachkraft)
        self.assertEqual(
            self.client.get("/api/v1/my/duty/").status_code,
            status.HTTP_200_OK,
        )

    def test_der_eigene_stand_zum_zweiten_faktor_bleibt_offen(self):
        setze(self.fachkraft)
        self.assertEqual(
            self.client.get("/api/v1/zweitfaktor/").status_code,
            status.HTTP_200_OK,
        )

    def test_das_profil_meldet_genau_das_was_die_endpunkte_zulassen(self):
        """
        Eine zweite Rechnung für die Anzeige wäre genau der Fehler, den diese
        Umstellung behebt.
        """
        setze(
            self.fachkraft,
            **{
                rechte.DIENSTPLAN_BEARBEITEN: rechte.SCHREIBEN,
                rechte.BEWOHNER: rechte.LESEN,
            },
        )
        gemeldet = self.client.get("/api/v1/user/me/").data["rechte"]

        self.assertEqual(gemeldet[rechte.DIENSTPLAN_BEARBEITEN], "schreiben")
        self.assertEqual(gemeldet[rechte.BEWOHNER], "lesen")
        self.assertEqual(gemeldet[rechte.PROTOKOLLE], "kein")

        # Und die Probe am Endpunkt, nicht an der Funktion.
        self.assertEqual(
            self.client.post(
                "/api/v1/duty-plan/",
                {"department": self.bereich.id, "year": 2026, "month": 11},
                format="json",
            ).status_code,
            status.HTTP_201_CREATED,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/v1/resident/{self.kind.id}/",
                {"last_name": "Geändert"},
                format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )


class StufeOhneMatrixTestCase(EndpunktBasis):
    """
    Konten ohne eigene Matrix - heute alle.

    Für sie entscheidet die Rückfalltabelle `STUFE_RECHTE`. Sie stand an vier
    Zeilen zu hoch, und das war harmlos, solange die Endpunkte `is_staff`
    fragten. Mit der durchgesetzten Matrix wäre daraus ein Recht geworden,
    das niemand vergeben hat.
    """

    def test_eine_fachkraft_gibt_keinen_dienstplan_frei(self):
        self.assertFalse(rechte.hat_eigene_matrix(self.fachkraft))
        self.assertFalse(
            rechte.darf(self.fachkraft, rechte.DIENSTPLAN_FREIGEBEN, schreiben=True)
        )

    def test_eine_fachkraft_entscheidet_keine_abwesenheiten(self):
        self.assertFalse(
            rechte.darf(
                self.fachkraft, rechte.ABWESENHEIT_GENEHMIGEN, schreiben=True
            )
        )
        self.assertFalse(rechte.darf(self.fachkraft, rechte.ABWESENHEIT_GENEHMIGEN))

    def test_eine_fachkraft_legt_keine_dienstart_an(self):
        self.assertFalse(
            rechte.darf(self.fachkraft, rechte.ORG_DIENSTARTEN, schreiben=True)
        )

    def test_eine_fachkraft_dokumentiert_weiter(self):
        """Die Gegenprobe: nichts von dem, was sie täglich tut, fällt weg."""
        for aktion in (
            rechte.PROTOKOLLE,
            rechte.BEWOHNER,
            rechte.FALLAKTE,
            rechte.ZEIT_ERFASSEN,
        ):
            with self.subTest(aktion=aktion):
                self.assertTrue(
                    rechte.darf(self.fachkraft, aktion, schreiben=True)
                )

    def test_eine_aushilfe_buacht_ihre_eigene_zeit(self):
        """
        Die eine Zeile, die mehr erlaubt als bisher. `WriteNeedsRole` sperrte
        der Aushilfe jede Schreiboperation, also auch die eigene
        Stundenbuchung - ein Fehler und keine Regel.
        """
        self.personal.access_level = "assistant"
        self.personal.save()

        self.assertTrue(
            rechte.darf(self.fachkraft, rechte.ZEIT_ERFASSEN, schreiben=True)
        )
        self.assertFalse(
            rechte.darf(self.fachkraft, rechte.PROTOKOLLE, schreiben=True)
        )

        antwort = self.client.post(
            "/api/v1/time-entry/",
            {
                "employee": self.personal.id,
                "date": (date.today() - timedelta(days=1)).isoformat(),
                "start_time": "08:00",
                "end_time": "16:00",
            },
            format="json",
        )
        self.assertEqual(antwort.status_code, status.HTTP_201_CREATED)
