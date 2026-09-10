"""
Rollen mit Geltungsbereich.

Die Rechtematrix aus rollenkonzept.md, Abschnitt 4, ist hier die
Testspezifikation. Geprueft wird beides: dass die Umstellung heute nichts
aendert (Betriebsart "stufe"), und dass sie das Richtige tut, wenn man sie
scharf schaltet (Betriebsart "rollen").
"""

from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from django_grp_backend import rechte
from django_grp_backend.models import Group, Resident
from django_grp_care.models import CaseFile
from django_grp_org.models import (
    Department,
    Employee,
    Facility,
    Provider,
    Role,
    Site,
)


class RechteBasis(TestCase):
    """
    Ein Traeger, ein Standort, eine Einrichtung, zwei Bereiche.

    Zwei Bereiche sind das Mindeste, an dem sich ein Geltungsbereich zeigen
    laesst: eine Rolle, die ueberall gilt, ist keine.
    """

    def setUp(self):
        self.traeger = Provider.objects.create(name="Wegzeichen")
        self.standort = Site.objects.create(
            provider=self.traeger, name="Talheim", city="Talheim"
        )
        self.haus = Facility.objects.create(site=self.standort, name="Haus Ahorn")

        self.gruppe_a = Group.objects.create(
            name="Ahorn", address="A", postalcode="11111", city="Talheim"
        )
        self.gruppe_b = Group.objects.create(
            name="Birke", address="B", postalcode="11111", city="Talheim"
        )
        self.bereich_a = Department.objects.create(
            facility=self.haus, name="Wohngruppe Ahorn", group=self.gruppe_a
        )
        self.bereich_b = Department.objects.create(
            facility=self.haus, name="Wohngruppe Birke", group=self.gruppe_b
        )

        self.kind = Resident.objects.create(
            first_name="Nele",
            last_name="Beispiel",
            group=self.gruppe_a,
            moved_in_since=date(2024, 1, 1),
        )

    def person(self, benutzername, stufe="specialist"):
        konto = User.objects.create_user(
            username=benutzername, password="testpass123"
        )
        mitarbeit = Employee.objects.create(
            provider=self.traeger,
            user=konto,
            first_name=benutzername.title(),
            last_name="Beispiel",
            hired_on=date(2024, 1, 1),
            access_level=stufe,
        )
        return konto, mitarbeit

    def rolle(self, mitarbeit, rolle, **bereich):
        return Role.objects.create(
            employee=mitarbeit,
            role=rolle,
            provider=self.traeger,
            valid_from=date(2024, 1, 1),
            **bereich,
        )


class GeltungsbereichTestCase(RechteBasis):
    """Die Ebene entscheidet, nicht nur die Rolle."""

    def test_ebene_wird_aus_den_gesetzten_feldern_gelesen(self):
        konto, mitarbeit = self.person("leitung")
        traegerweit = self.rolle(mitarbeit, "executive")
        im_bereich = self.rolle(mitarbeit, "group_lead", department=self.bereich_a)

        self.assertEqual(traegerweit.scope_level, "S1")
        self.assertEqual(im_bereich.scope_level, "S4")

    def test_abgelaufene_zuweisung_gilt_nicht_mehr(self):
        """
        Der Zeitraum ist der Grund, warum ein befristeter Zugang ablaeuft,
        statt vergessen zu werden.
        """
        konto, mitarbeit = self.person("springer")
        rolle = self.rolle(mitarbeit, "specialist", department=self.bereich_a)
        rolle.valid_to = date.today() - timedelta(days=1)
        rolle.save()

        self.assertFalse(rolle.is_current())

    def test_kuenftige_zuweisung_gilt_noch_nicht(self):
        konto, mitarbeit = self.person("neu")
        rolle = self.rolle(mitarbeit, "specialist", department=self.bereich_a)
        rolle.valid_from = date.today() + timedelta(days=7)
        rolle.save()

        self.assertFalse(rolle.is_current())
        self.assertTrue(rolle.is_current(date.today() + timedelta(days=8)))


@override_settings(RECHTE_QUELLE="rollen")
class RollenEntscheidenTestCase(RechteBasis):
    """Scharf geschaltet: die Zuweisungen antworten."""

    def test_gruppenleitung_nur_im_eigenen_bereich(self):
        """
        Der Fall, um den es bei der ganzen Uebung geht: wer den Dienstplan
        einer Gruppe freigeben darf, darf heute alles.
        """
        konto, mitarbeit = self.person("gruppenleitung")
        self.rolle(mitarbeit, "group_lead", department=self.bereich_a)

        self.assertTrue(
            rechte.darf(konto, rechte.PROTOKOLLE, self.gruppe_a, schreiben=True)
        )
        self.assertFalse(
            rechte.darf(konto, rechte.PROTOKOLLE, self.gruppe_b, schreiben=True)
        )

    def test_gruppenleitung_verstellt_den_traeger_nicht(self):
        konto, mitarbeit = self.person("gruppenleitung")
        self.rolle(mitarbeit, "group_lead", department=self.bereich_a)

        self.assertFalse(
            rechte.darf(konto, rechte.ORG_STRUKTUR, schreiben=True)
        )
        self.assertTrue(rechte.darf(konto, rechte.ORG_STRUKTUR))

    def test_einrichtungsleitung_sieht_beide_bereiche(self):
        """Eine Rolle wirkt auf alles unterhalb ihrer Ebene."""
        konto, mitarbeit = self.person("hausleitung")
        self.rolle(mitarbeit, "facility_lead", facility=self.haus)

        for gruppe in (self.gruppe_a, self.gruppe_b):
            self.assertTrue(
                rechte.darf(
                    konto, rechte.DIENSTPLAN_BEARBEITEN, gruppe, schreiben=True
                )
            )

    def test_dienstplanung_plant_gibt_aber_nicht_frei(self):
        """
        Die neue Rolle. Sie baut Plaene und sieht keine Fachdokumentation -
        in groesseren Haeusern macht das eine Planungskraft.
        """
        konto, mitarbeit = self.person("planung")
        self.rolle(mitarbeit, "duty_planner", facility=self.haus)

        self.assertTrue(
            rechte.darf(
                konto, rechte.DIENSTPLAN_BEARBEITEN, self.gruppe_a, schreiben=True
            )
        )
        self.assertFalse(
            rechte.darf(
                konto, rechte.DIENSTPLAN_FREIGEBEN, self.gruppe_a, schreiben=True
            )
        )
        self.assertFalse(rechte.darf(konto, rechte.PROTOKOLLE, self.gruppe_a))
        self.assertFalse(rechte.darf(konto, rechte.FALLAKTE, self.gruppe_a))

    def test_verwaltung_sieht_keine_paedagogische_dokumentation(self):
        """
        Heute haengt beides an derselben Stufe, und die Lohnbuchhaltung
        sieht jedes Gruppenprotokoll.
        """
        konto, mitarbeit = self.person("lohn")
        self.rolle(mitarbeit, "administration")

        self.assertTrue(
            rechte.darf(konto, rechte.ZEITKONTO_ABSCHLIESSEN, schreiben=True)
        )
        self.assertFalse(rechte.darf(konto, rechte.PROTOKOLLE, self.gruppe_a))
        self.assertFalse(rechte.darf(konto, rechte.FALLAKTE, self.gruppe_a))

    def test_ergaenzungskraft_liest_und_schreibt_nicht(self):
        konto, mitarbeit = self.person("aushilfe", stufe="assistant")
        self.rolle(mitarbeit, "assistant", department=self.bereich_a)

        self.assertTrue(rechte.darf(konto, rechte.PROTOKOLLE, self.gruppe_a))
        self.assertFalse(
            rechte.darf(konto, rechte.PROTOKOLLE, self.gruppe_a, schreiben=True)
        )
        # Die eigene Zeit erfasst auch die Aushilfe.
        self.assertTrue(rechte.darf(konto, rechte.ZEIT_ERFASSEN, schreiben=True))

    def test_geschuetzte_vermerke_nur_fallfuehrung_und_leitung(self):
        """
        Entschieden am 10. September 2026: die Leitung sieht sie. Die
        Fachkraft ohne Fallfuehrung nicht.
        """
        akte = CaseFile.objects.create(
            provider=self.traeger,
            resident=self.kind,
            opened_on=date(2024, 1, 1),
        )

        fachkraft, m_fach = self.person("fachkraft")
        self.rolle(m_fach, "specialist", department=self.bereich_a)

        bezug, m_bezug = self.person("bezug")
        self.rolle(m_bezug, "case_lead", case_file=akte)

        leitung, m_leitung = self.person("leitung")
        self.rolle(m_leitung, "facility_lead", facility=self.haus)

        self.assertFalse(rechte.darf(fachkraft, rechte.FALLAKTE_GESCHUETZT, akte))
        self.assertTrue(rechte.darf(bezug, rechte.FALLAKTE_GESCHUETZT, akte))
        self.assertTrue(rechte.darf(leitung, rechte.FALLAKTE_GESCHUETZT, akte))

    def test_externe_lesekraft_sieht_genau_einen_fall(self):
        """Jugendamt, Vormund, Therapie: befristet, lesend, auf benannte Faelle."""
        akte = CaseFile.objects.create(
            provider=self.traeger,
            resident=self.kind,
            opened_on=date(2024, 1, 1),
        )
        zweites_kind = Resident.objects.create(
            first_name="Jon",
            last_name="Nachbar",
            group=self.gruppe_b,
            moved_in_since=date(2024, 1, 1),
        )
        andere_akte = CaseFile.objects.create(
            provider=self.traeger,
            resident=zweites_kind,
            opened_on=date(2024, 1, 1),
        )

        konto, mitarbeit = self.person("jugendamt")
        zuweisung = self.rolle(mitarbeit, "external_reader", case_file=akte)

        self.assertTrue(rechte.darf(konto, rechte.FALLAKTE, akte))
        self.assertFalse(rechte.darf(konto, rechte.FALLAKTE, andere_akte))
        self.assertFalse(rechte.darf(konto, rechte.FALLAKTE, akte, schreiben=True))
        self.assertFalse(rechte.darf(konto, rechte.PROTOKOLLE, self.gruppe_a))

        # Nach Ablauf ohne weiteres Zutun.
        zuweisung.valid_to = date.today() - timedelta(days=1)
        zuweisung.save()
        self.assertFalse(rechte.darf(konto, rechte.FALLAKTE, akte))

    def test_springer_in_drei_bereichen_befristet(self):
        konto, mitarbeit = self.person("springer")
        zuweisung = self.rolle(
            mitarbeit, "specialist", department=self.bereich_b
        )
        zuweisung.valid_from = date.today() - timedelta(days=5)
        zuweisung.valid_to = date.today() + timedelta(days=5)
        zuweisung.save()

        self.assertTrue(rechte.darf(konto, rechte.PROTOKOLLE, self.gruppe_b))
        self.assertFalse(rechte.darf(konto, rechte.PROTOKOLLE, self.gruppe_a))

    def test_ohne_zuweisung_nichts(self):
        konto, mitarbeit = self.person("neuling")
        self.assertFalse(rechte.darf(konto, rechte.PROTOKOLLE, self.gruppe_a))
        self.assertFalse(rechte.darf(konto, rechte.ZEIT_ERFASSEN, schreiben=True))

    def test_superuser_bleibt_handlungsfaehig(self):
        """
        Der Notausgang. Wer die Anwendung einrichtet, hat noch keine Rolle -
        und eine Migration, die den Einrichtenden aussperrt, ist keine.
        """
        konto = User.objects.create_superuser(
            username="root", password="testpass123", email=""
        )
        self.assertTrue(
            rechte.darf(konto, rechte.ORG_STRUKTUR, schreiben=True)
        )


class StufeEntscheidetTestCase(RechteBasis):
    """
    Voreinstellung: es bleibt beim Alten.

    Schritt 2 aus dem Konzept aendert kein Verhalten. Diese Faelle wuerden
    unter "rollen" anders ausgehen - genau deshalb stehen sie hier.
    """

    def test_mitarbeiter_darf_weiterhin_alles(self):
        konto, mitarbeit = self.person("chefin", stufe="admin")
        self.assertTrue(rechte.darf(konto, rechte.ORG_STRUKTUR, schreiben=True))
        self.assertTrue(
            rechte.darf(konto, rechte.PROTOKOLLE, self.gruppe_a, schreiben=True)
        )

    def test_fachkraft_schreibt_ueberall_wo_sie_hinsieht(self):
        """
        Die fehlende Achse: ohne Rollen gibt es keinen Geltungsbereich, und
        die Fachkraft schreibt in beiden Gruppen.
        """
        konto, mitarbeit = self.person("fachkraft")
        self.rolle(mitarbeit, "specialist", department=self.bereich_a)

        for gruppe in (self.gruppe_a, self.gruppe_b):
            self.assertTrue(
                rechte.darf(konto, rechte.PROTOKOLLE, gruppe, schreiben=True)
            )

    def test_aushilfe_liest_nur(self):
        konto, mitarbeit = self.person("aushilfe", stufe="assistant")
        self.assertTrue(rechte.darf(konto, rechte.PROTOKOLLE, self.gruppe_a))
        self.assertFalse(
            rechte.darf(konto, rechte.PROTOKOLLE, self.gruppe_a, schreiben=True)
        )

    def test_ohne_anmeldung_nichts(self):
        self.assertFalse(rechte.darf(None, rechte.PROTOKOLLE))


@override_settings(RECHTE_QUELLE="vergleich")
class VergleichTestCase(RechteBasis):
    """
    Die Stufe entscheidet, die Rollen rechnen mit.

    Der Weg, auf dem sich die Umstellung ohne einen Tag Ausfall vorbereiten
    laesst: die Abweichung steht im Protokoll, bevor sie jemandem fehlt.
    """

    def test_die_stufe_bleibt_massgeblich(self):
        konto, mitarbeit = self.person("fachkraft")
        self.rolle(mitarbeit, "specialist", department=self.bereich_a)

        # Nach Rollen waere das falsch - die Stufe sagt wahr, und sie zaehlt.
        with self.assertLogs("django_grp.rechte", level="WARNING") as protokoll:
            erlaubt = rechte.darf(
                konto, rechte.PROTOKOLLE, self.gruppe_b, schreiben=True
            )

        self.assertTrue(erlaubt)
        self.assertIn("Rechte weichen ab", protokoll.output[0])

    def test_einigkeit_erzeugt_keine_meldung(self):
        konto, mitarbeit = self.person("fachkraft")
        self.rolle(mitarbeit, "specialist", department=self.bereich_a)

        with self.assertNoLogs("django_grp.rechte", level="WARNING"):
            self.assertTrue(
                rechte.darf(
                    konto, rechte.PROTOKOLLE, self.gruppe_a, schreiben=True
                )
            )


class MatrixTestCase(TestCase):
    """
    Die Tabelle selbst.

    Kein Verhalten, sondern eine Zusicherung ueber die Daten: was in
    rollenkonzept.md steht, steht auch im Code.
    """

    def test_jede_rolle_hat_eine_zeile(self):
        for wert, _ in Role.ROLE_CHOICES:
            self.assertIn(wert, rechte.MATRIX, f"Rolle {wert} fehlt in der Matrix")

    def test_keine_rolle_zu_viel(self):
        bekannt = {wert for wert, _ in Role.ROLE_CHOICES}
        self.assertEqual(set(rechte.MATRIX) - bekannt, set())

    def test_geschuetzte_vermerke_bleiben_die_ausnahme(self):
        """
        Wer sie sehen darf, ist die eine Zeile, die sich nicht aus Versehen
        aendern soll.
        """
        duerfen = {
            rolle
            for rolle, rechte_der_rolle in rechte.MATRIX.items()
            if rechte_der_rolle.get(rechte.FALLAKTE_GESCHUETZT, 0) > 0
        }
        self.assertEqual(duerfen, {"executive", "facility_lead", "case_lead"})

    def test_die_stufentabelle_ist_nicht_die_matrix(self):
        """
        Waeren beide gleich, waere die Betriebsart „vergleich" nutzlos - sie
        wuerde nie eine Abweichung finden.
        """
        self.assertNotEqual(
            rechte.STUFE_RECHTE["specialist"], rechte.MATRIX["specialist"]
        )
