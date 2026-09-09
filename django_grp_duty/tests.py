"""
Tests der Regelprüfung für Dienstpläne.

Schwerpunkt: nach spätestens sechs Tagen muss ein freier Tag kommen. Die
Grenze stand auf sieben und die Prüfung schlug erst darüber an — eine
durchgearbeitete Woche, Montag bis Sonntag, ging damit glatt durch. Der
Automat kannte die Regel überhaupt nicht.

Rechtlicher Hintergrund: § 9 ArbZG schreibt die Sonntagsruhe vor.
Einrichtungen zur Betreuung von Personen dürfen sonntags arbeiten lassen
(§ 10 Abs. 1 Nr. 3), müssen dafür aber einen Ersatzruhetag geben
(§ 11 Abs. 3). Die Woche hat damit sechs Arbeitstage.
"""

from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from django_grp_backend.models import Group
from django_grp_duty.autofill import autofill_plan
from django_grp_duty.bedarf import tagesbedarf
from django_grp_duty.models import (
    DutyPlan,
    Shift,
    ShiftType,
    StaffingRequirement,
)
from django_grp_duty.services import generate_shifts
from django_grp_duty.rules import (
    MAX_CONSECUTIVE_DAYS,
    check_plan,
    serie_um,
)
from django_grp_org.models import (
    Department,
    Employee,
    Facility,
    Provider,
    Site,
    WorkTimeModel,
)


class SerieUmTestCase(TestCase):
    """Die Hilfsfunktion, auf der beide Seiten aufsetzen."""

    def test_einzelner_tag(self):
        self.assertEqual(serie_um(set(), date(2026, 9, 9)), 1)

    def test_zaehlt_nach_hinten(self):
        tage = {date(2026, 9, 7), date(2026, 9, 8)}
        self.assertEqual(serie_um(tage, date(2026, 9, 9)), 3)

    def test_zaehlt_nach_vorn(self):
        tage = {date(2026, 9, 10), date(2026, 9, 11)}
        self.assertEqual(serie_um(tage, date(2026, 9, 9)), 3)

    def test_verbindet_zwei_serien(self):
        """
        Der Fall, der sonst durchfällt.

        Für sich betrachtet ist der 9. ein einzelner Tag. Er schließt aber
        eine Lücke zwischen zwei Serien und macht aus ihnen eine lange.
        """
        tage = {
            date(2026, 9, 6),
            date(2026, 9, 7),
            date(2026, 9, 8),
            date(2026, 9, 10),
            date(2026, 9, 11),
            date(2026, 9, 12),
        }
        self.assertEqual(serie_um(tage, date(2026, 9, 9)), 7)

    def test_luecke_bleibt_luecke(self):
        tage = {date(2026, 9, 6), date(2026, 9, 11)}
        self.assertEqual(serie_um(tage, date(2026, 9, 8)), 1)


class DienstplanMixin:
    """Ein Bereich, eine Dienstart, eine Person."""

    def aufbauen(self):
        self.traeger = Provider.objects.create(name="Jugendhilfe Musterstadt")
        standort = Site.objects.create(provider=self.traeger, name="Haus Lindenweg")
        einrichtung = Facility.objects.create(site=standort, name="Haus Lindenweg")
        self.gruppe = Group.objects.create(
            name="Gruppe Lindenweg",
            address="Weg 1",
            postalcode="42651",
            city="Solingen",
        )
        self.bereich = Department.objects.create(
            facility=einrichtung,
            name="Wohngruppe",
            group=self.gruppe,
            minimum_staff=1,
            specialist_ratio=0,
        )
        self.dienstart = ShiftType.objects.create(
            provider=self.traeger,
            name="Frühdienst",
            short_code="F",
            start_time=time(6, 0),
            end_time=time(14, 0),
        )
        self.person = Employee.objects.create(
            provider=self.traeger,
            first_name="Miriam",
            last_name="Kern",
            hired_on=date(2026, 1, 1),
        )

    def plan(self, jahr, monat):
        return DutyPlan.objects.create(
            department=self.bereich, year=jahr, month=monat
        )

    def dienste(self, plan, start, tage, person=None):
        """Legt `tage` aufeinanderfolgende Dienste ab `start` an."""
        for versatz in range(tage):
            Shift.objects.create(
                plan=plan,
                date=start + timedelta(days=versatz),
                shift_type=self.dienstart,
                employee=person if person is not None else self.person,
            )


class SerienpruefungTestCase(DienstplanMixin, TestCase):
    def setUp(self):
        self.aufbauen()

    def verstoesse(self, plan):
        return [
            verstoss
            for verstoss in check_plan(plan)
            if verstoss.rule == "consecutive_days"
        ]

    def test_sechs_tage_sind_erlaubt(self):
        plan = self.plan(2026, 9)
        self.dienste(plan, date(2026, 9, 7), 6)
        self.assertEqual(self.verstoesse(plan), [])

    def test_sieben_tage_am_stueck_werden_gemeldet(self):
        """
        Der eigentliche Befund.

        Montag bis Sonntag durchgearbeitet - das ging vorher durch, weil die
        Grenze auf sieben stand und die Prüfung erst darüber anschlug.
        """
        plan = self.plan(2026, 9)
        self.dienste(plan, date(2026, 9, 7), 7)

        verstoesse = self.verstoesse(plan)
        self.assertEqual(len(verstoesse), 1)
        self.assertEqual(verstoesse[0].severity, "error")
        self.assertIn("Kern", verstoesse[0].message)
        self.assertIn("freier Tag", verstoesse[0].message)

    def test_ein_freier_tag_setzt_die_serie_zurueck(self):
        plan = self.plan(2026, 9)
        self.dienste(plan, date(2026, 9, 1), 5)
        # Der 6. bleibt frei.
        self.dienste(plan, date(2026, 9, 7), 5)
        self.assertEqual(self.verstoesse(plan), [])

    def test_serie_ueber_den_monatswechsel(self):
        """
        Zwei Pläne, eine Serie.

        Wer vom 27. bis 31. Januar durcharbeitet und am 1. Februar
        weitermacht, steht in zwei Plänen mit je einer kurzen, unauffälligen
        Serie — und in Wahrheit seit acht Tagen im Dienst. Ohne den Blick
        über den Rand endet jede Prüfung am Monatsersten.
        """
        januar = self.plan(2026, 1)
        februar = self.plan(2026, 2)
        self.dienste(januar, date(2026, 1, 27), 5)  # 27. bis 31.
        self.dienste(februar, date(2026, 2, 1), 3)  # 1. bis 3.

        self.assertEqual(len(self.verstoesse(februar)), 1)

    def test_andere_person_bleibt_unberuehrt(self):
        zweite = Employee.objects.create(
            provider=self.traeger,
            first_name="Jonas",
            last_name="Brand",
            hired_on=date(2026, 1, 1),
        )
        plan = self.plan(2026, 9)
        self.dienste(plan, date(2026, 9, 7), 4)
        self.dienste(plan, date(2026, 9, 11), 4, person=zweite)
        self.assertEqual(self.verstoesse(plan), [])


class AutofillSerieTestCase(DienstplanMixin, TestCase):
    """
    Der Automat darf die Regel nicht erst hinterher verletzen.

    Er kannte sie überhaupt nicht: geprüft wurden Ruhezeit und
    Doppelbelegung, und eine Person ließ sich ohne Weiteres sieben Tage am
    Stück eintragen. Die Regelprüfung meldete das danach — hinterher ist der
    falsche Zeitpunkt, wenn ein Automat den Plan gebaut hat.
    """

    def setUp(self):
        self.aufbauen()
        self.gruppe.group_members.add(
            # Der Automat sucht sein Personal über Stelle oder Gruppe.
            self._konto()
        )

    def _konto(self):
        from django.contrib.auth.models import User

        konto = User.objects.create_user(
            username="m.kern", password="EinGutesPasswort1"
        )
        self.person.user = konto
        self.person.save(update_fields=["user"])
        return konto

    def test_automat_teilt_keine_sieben_tage_am_stueck_ein(self):
        plan = self.plan(2026, 9)
        for versatz in range(8):
            Shift.objects.create(
                plan=plan,
                date=date(2026, 9, 7) + timedelta(days=versatz),
                shift_type=self.dienstart,
            )

        autofill_plan(plan)

        tage = sorted(
            plan.shifts.filter(employee=self.person).values_list("date", flat=True)
        )
        # Sonst liefe der Test leer durch: ohne eine einzige Zuteilung ist
        # jede Serie kurz genug, und der Test bewiese nichts.
        #
        # Erwartet werden sieben Zuteilungen aus acht Diensten: sechs Tage am
        # Stück, dann bleibt der siebte frei, und danach geht es weiter. Der
        # Automat hört also nicht auf, er legt einen Ruhetag ein - genau das
        # soll er tun.
        self.assertEqual(len(tage), 7)

        laengste = 1
        aktuell = 1
        for vorher, jetzt in zip(tage, tage[1:]):
            aktuell = aktuell + 1 if (jetzt - vorher).days == 1 else 1
            laengste = max(laengste, aktuell)

        self.assertLessEqual(laengste, MAX_CONSECUTIVE_DAYS)

    def test_automat_hinterlaesst_keinen_verstoss(self):
        plan = self.plan(2026, 9)
        for versatz in range(10):
            Shift.objects.create(
                plan=plan,
                date=date(2026, 9, 7) + timedelta(days=versatz),
                shift_type=self.dienstart,
            )

        autofill_plan(plan)

        self.assertTrue(
            plan.shifts.filter(employee=self.person).exists(),
            "Ohne Zuteilung beweist der Test nichts",
        )

        serien = [
            verstoss
            for verstoss in check_plan(plan)
            if verstoss.rule == "consecutive_days"
        ]
        self.assertEqual(serien, [])


class OffeneDiensteTest(TestCase):
    """
    Ein leerer Platz ist nur dann eine Luecke, wenn die Zeit auch wirklich
    unbesetzt bleibt.

    Der 24-Stunden-Dienst ist der Anlass: wer ihn uebernimmt, deckt Tag und
    Nacht ab. Der Generator legt trotzdem je Dienstart einen Platz an, weil
    beim Anlegen noch nicht feststeht, wie besetzt wird - und danach stand
    an jedem solchen Tag "Nachtbereitschaft ist nicht besetzt".
    """

    def setUp(self):
        self.provider = Provider.objects.create(name="Träger")
        self.site = Site.objects.create(provider=self.provider, name="Haus")
        self.facility = Facility.objects.create(site=self.site, name="Einrichtung")
        self.department = Department.objects.create(
            facility=self.facility, name="Wohngruppe", minimum_staff=1
        )
        self.tag = ShiftType.objects.create(
            provider=self.provider, name="Tagdienst", short_code="T",
            start_time=time(10, 0), end_time=time(20, 30),
        )
        self.nacht = ShiftType.objects.create(
            provider=self.provider, name="Nachtbereitschaft", short_code="N",
            start_time=time(20, 0), end_time=time(10, 30),
            is_night=True, on_call_minutes=360,
        )
        self.rund = ShiftType.objects.create(
            provider=self.provider, name="24er", short_code="24",
            start_time=time(10, 0), end_time=time(9, 59),
            is_night=True, on_call_minutes=360,
        )
        self.person = Employee.objects.create(
            provider=self.provider, first_name="Rafa", last_name="Schmitz",
            hired_on=date(2020, 1, 1),
        )
        self.plan = DutyPlan.objects.create(
            department=self.department, year=2026, month=9
        )

    def _befunde(self, regel: str):
        return [v for v in check_plan(self.plan) if v.rule == regel]

    def test_leerer_platz_ohne_deckung_bleibt_ein_fehler(self):
        Shift.objects.create(
            plan=self.plan, date=date(2026, 9, 10), shift_type=self.tag
        )

        fehler = self._befunde("open_shift")

        self.assertEqual(len(fehler), 1)
        self.assertEqual(fehler[0].severity, "error")
        # Die Meldung sagt jetzt, wie viel Zeit offen bleibt.
        self.assertIn("10 h 30 min", fehler[0].message)

    def test_der_24er_deckt_den_leeren_tagdienst(self):
        """
        Der Plan haelt je Dienstart einen Platz bereit. Wer den
        24-Stunden-Dienst besetzt, laesst Tag und Nacht leer stehen - und das
        ist keine Luecke, sondern der Normalfall.
        """
        tag = date(2026, 9, 10)
        Shift.objects.create(
            plan=self.plan, date=tag, shift_type=self.rund, employee=self.person
        )
        Shift.objects.create(plan=self.plan, date=tag, shift_type=self.tag)

        self.assertEqual(self._befunde("open_shift"), [])

    def test_zwei_aufeinanderfolgende_24er_decken_die_nacht(self):
        """
        Der 24er endet um 09:59, der naechste beginnt um 10:00. Die
        Nachtbereitschaft laeuft bis 10:30 - die Minute dazwischen darf
        nicht als Luecke zaehlen.
        """
        for tag in (date(2026, 9, 10), date(2026, 9, 11)):
            Shift.objects.create(
                plan=self.plan, date=tag, shift_type=self.rund, employee=self.person
            )
        Shift.objects.create(
            plan=self.plan, date=date(2026, 9, 10), shift_type=self.nacht
        )

        self.assertEqual(self._befunde("open_shift"), [])

    def test_ein_einzelner_24er_laesst_den_naechsten_morgen_offen(self):
        """
        Ohne Folgetag bleibt nach 09:59 tatsaechlich Zeit unbesetzt - und
        das soll die Pruefung auch sagen.
        """
        Shift.objects.create(
            plan=self.plan, date=date(2026, 9, 10), shift_type=self.rund,
            employee=self.person,
        )
        Shift.objects.create(
            plan=self.plan, date=date(2026, 9, 10), shift_type=self.nacht
        )

        self.assertEqual(len(self._befunde("open_shift")), 1)


class TagesbedarfTest(TestCase):
    """
    Was ein Tag wirklich braucht.

    Der Anlass: bei Tagdienst, 24-Stunden-Dienst und Nachtbereitschaft legte
    der Generator drei Plaetze taeglich an. Das sind rund 1440 Dienststunden
    im Monat gegen 860, die sechs Mitarbeitende zusammen vertraglich haben -
    der Plan begann mit einer Ueberlast, die keine Besetzung auffangen kann.
    """

    def setUp(self):
        self.provider = Provider.objects.create(name="Träger")
        self.site = Site.objects.create(provider=self.provider, name="Haus")
        self.facility = Facility.objects.create(site=self.site, name="Einrichtung")
        self.department = Department.objects.create(
            facility=self.facility, name="Wohngruppe", minimum_staff=1
        )
        self.tag = ShiftType.objects.create(
            provider=self.provider, name="Tagdienst", short_code="T",
            start_time=time(10, 0), end_time=time(20, 30),
        )
        self.nacht = ShiftType.objects.create(
            provider=self.provider, name="Nachtbereitschaft", short_code="N",
            start_time=time(20, 0), end_time=time(10, 30),
            is_night=True, on_call_minutes=360,
        )
        self.rund = ShiftType.objects.create(
            provider=self.provider, name="24er", short_code="24",
            start_time=time(10, 0), end_time=time(9, 59),
            is_night=True, on_call_minutes=360,
        )
        self.arten = [self.tag, self.nacht, self.rund]

    def _fenster(self, von, bis, personen=1):
        return StaffingRequirement.objects.create(
            department=self.department, starts_at=von, ends_at=bis,
            minimum_staff=personen, minimum_specialists=1,
        )

    def test_ohne_vorgabe_bleibt_es_bei_einem_platz_je_art(self):
        """Ohne Vorgabe gibt es nichts zu rechnen - das alte Verhalten."""
        bedarf = tagesbedarf(self.department, self.arten)

        self.assertEqual(bedarf, {a.id: 1 for a in self.arten})

    def test_der_24er_allein_deckt_beide_fenster(self):
        """
        Der Fall aus der Praxis: eine Person von 10 bis 20 Uhr, eine von 20
        bis 10 Uhr. Ein 24-Stunden-Dienst erfuellt beides mit 23,5 Stunden,
        Tag plus Nacht braeuchten zwei Menschen und 24 Stunden.
        """
        self._fenster(time(10, 0), time(20, 0))
        self._fenster(time(20, 0), time(10, 0))

        bedarf = tagesbedarf(self.department, self.arten)

        self.assertEqual(bedarf[self.rund.id], 1)
        self.assertEqual(bedarf[self.tag.id], 0)
        self.assertEqual(bedarf[self.nacht.id], 0)

    def test_ohne_24er_bleiben_tag_und_nacht(self):
        """Fehlt die guenstige Kombination, muss die teurere herhalten."""
        self._fenster(time(10, 0), time(20, 0))
        self._fenster(time(20, 0), time(10, 0))

        bedarf = tagesbedarf(self.department, [self.tag, self.nacht])

        self.assertEqual(bedarf[self.tag.id], 1)
        self.assertEqual(bedarf[self.nacht.id], 1)

    def test_zwei_personen_am_tag_brauchen_zwei_plaetze(self):
        """Die Vorgabe ist ein Minimum, keine Obergrenze - aber sie gilt."""
        self._fenster(time(10, 0), time(20, 0), personen=2)
        self._fenster(time(20, 0), time(10, 0))

        bedarf = tagesbedarf(self.department, self.arten)
        belegt_am_tag = bedarf[self.rund.id] + bedarf[self.tag.id]

        self.assertGreaterEqual(belegt_am_tag, 2)

    def test_eine_halbe_stunde_ueberschneidung_deckt_die_nacht_nicht(self):
        """
        Der Tagdienst endet um 20:30 und ragt damit in das Nachtfenster.
        Das macht aus ihm keine Nachtbesetzung - sonst waere die guenstigste
        Antwort ein einzelner Tagdienst, und nachts waere niemand da.
        """
        self._fenster(time(20, 0), time(10, 0))

        bedarf = tagesbedarf(self.department, [self.tag, self.nacht])

        self.assertEqual(bedarf[self.tag.id], 0)
        self.assertEqual(bedarf[self.nacht.id], 1)

    def test_vorgabe_je_dienstart_gilt_weiterhin(self):
        StaffingRequirement.objects.create(
            department=self.department, shift_type=self.tag,
            minimum_staff=2, minimum_specialists=1,
        )

        bedarf = tagesbedarf(self.department, self.arten)

        self.assertEqual(bedarf[self.tag.id], 2)

    def test_der_generator_legt_jede_dienstart_an(self):
        """
        Angelegt wird jede gewaehlte Dienstart an jedem Tag: der Plan haelt
        Plaetze bereit, er schreibt nicht vor, welche besetzt werden. Wer im
        Kalender jemanden in den Spaetdienst ziehen will, braucht dort eine
        Zeile.
        """
        self._fenster(time(10, 0), time(20, 0))
        self._fenster(time(20, 0), time(10, 0))
        plan = DutyPlan.objects.create(
            department=self.department, year=2026, month=9
        )

        angelegt = generate_shifts(plan, self.arten)

        self.assertEqual(angelegt, 90)
        self.assertEqual(
            set(plan.shifts.values_list("shift_type_id", flat=True)),
            {a.id for a in self.arten},
        )


class AutofillKombinationTest(TestCase):
    """
    Der Automat entscheidet je Tag, WELCHE Plaetze er besetzt.

    Der Plan haelt je Dienstart einen Platz bereit. Wer stur alle besetzt,
    verplant bei Tagdienst, 24-Stunden-Dienst und Nachtbereitschaft mehr
    Stunden, als das Team hat - und am Monatsende haben alle Ueberstunden.
    """

    def setUp(self):
        self.provider = Provider.objects.create(name="Träger")
        self.site = Site.objects.create(provider=self.provider, name="Haus")
        self.facility = Facility.objects.create(site=self.site, name="Einrichtung")
        self.gruppe = Group.objects.create(name="Wohngruppe")
        self.department = Department.objects.create(
            facility=self.facility, name="Wohngruppe", minimum_staff=1,
            group=self.gruppe,
        )
        self.tag = ShiftType.objects.create(
            provider=self.provider, name="Tagdienst", short_code="T",
            start_time=time(10, 0), end_time=time(20, 30),
        )
        self.nacht = ShiftType.objects.create(
            provider=self.provider, name="Nachtbereitschaft", short_code="N",
            start_time=time(20, 0), end_time=time(10, 30),
            is_night=True, on_call_minutes=360,
        )
        self.rund = ShiftType.objects.create(
            provider=self.provider, name="24er", short_code="24",
            start_time=time(10, 0), end_time=time(9, 59),
            is_night=True, on_call_minutes=360,
        )
        # Eine Person in jedem Fenster reicht - das Minimum, wie im Haus.
        for von, bis in [(time(10, 0), time(20, 0)), (time(20, 0), time(10, 0))]:
            StaffingRequirement.objects.create(
                department=self.department, starts_at=von, ends_at=bis,
                minimum_staff=1, minimum_specialists=0,
            )

        modell = WorkTimeModel.objects.create(
            provider=self.provider, name="Vollzeit", weekly_hours=Decimal("39"),
        )
        for nummer in range(8):
            konto = User.objects.create_user(username=f"kraft{nummer}")
            self.gruppe.group_members.add(konto)
            Employee.objects.create(
                provider=self.provider, user=konto,
                first_name="Kraft", last_name=str(nummer),
                hired_on=date(2020, 1, 1), work_time_model=modell,
            )

        self.plan = DutyPlan.objects.create(
            department=self.department, year=2026, month=9
        )
        generate_shifts(self.plan, [self.tag, self.nacht, self.rund])

    def test_nicht_jeder_platz_wird_besetzt(self):
        """
        30 Tage mal drei Plaetze sind 90. Das Team hat acht Vollzeitkraefte
        und damit rund 1370 Monatsstunden; alle 90 Plaetze waeren gut 1200
        Kontostunden - besetzt wird davon, was gebraucht wird, nicht alles.
        """
        ergebnis = autofill_plan(self.plan)

        besetzt = self.plan.shifts.filter(employee__isnull=False).count()
        self.assertEqual(self.plan.shifts.count(), 90)
        self.assertLess(besetzt, 90)
        self.assertGreater(besetzt, 30)

    def test_keine_luecke_bleibt_offen(self):
        """Was leer bleibt, ist nicht gebraucht - nicht vergessen."""
        autofill_plan(self.plan)

        self.assertEqual(
            [v for v in check_plan(self.plan) if v.rule == "open_shift"], []
        )

    def test_niemand_bekommt_grobe_ueberstunden(self):
        """
        Der eigentliche Zweck. Vorher lagen die Leute bei 150 bis 250 Prozent
        ihres Solls, weil jeder Platz besetzt wurde.
        """
        ergebnis = autofill_plan(self.plan)

        for zeile in ergebnis["hours"]:
            soll = Decimal(zeile["target"])
            ist = Decimal(zeile["planned"])
            if not soll:
                continue
            self.assertLess(
                ist / soll, Decimal("1.25"),
                f"{zeile['name']} kommt auf {ist} von {soll} Stunden.",
            )

    def test_die_kombination_wechselt(self):
        """
        Mal Tag und Nacht, mal der 24-Stunden-Dienst - je nachdem, wer noch
        Stunden braucht. Immer dieselbe Kombination waere ein Zeichen, dass
        die Rechnung gar nicht greift.
        """
        autofill_plan(self.plan)

        muster = {
            tuple(sorted(
                dienst.shift_type.short_code
                for dienst in self.plan.shifts.filter(
                    date=tag, employee__isnull=False
                ).select_related("shift_type")
            ))
            for tag in {d.date for d in self.plan.shifts.all()}
        }

        self.assertGreater(len(muster), 1)
