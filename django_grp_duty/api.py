"""
API für Dienstplanung, Abwesenheiten und Zeiterfassung (Phasen 2 bis 4)
sowie die SelfService-Sichten aus Phase 7.

## Zugriffsregel

Jedes Konto mit Personaldatensatz sieht und schreibt die eigenen Daten:
Dienste, Abwesenheitsanträge, Zeitbuchungen, Wünsche, Tauschangebote. Dafür
braucht es kein Merkmal der Rechtematrix — die Endpunkte prüfen den
Datensatz.

Was über die eigenen Daten hinausgeht, hängt an einer Zeile der Matrix:

    Dienstplan bearbeiten   Pläne und Dienste, Tausch bestätigen
    Dienstplan freigeben    einen Plan veröffentlichen
    Abwesenheiten           fremde Anträge sehen und entscheiden
    Zeiterfassung           eigene Stunden buchen
    Zeitkonten abschließen  fremde Buchungen sehen, freigeben, Monat schließen
    Dienstarten             Dienstarten und Besetzungsvorgaben
    Nachweise               Lohnübergabe

**Bis zum 13. September 2026 fragte jede dieser Stellen `request.user
.is_staff`** — einen Django-Schalter. Eine Bereichsleitung ohne diesen
Schalter konnte keinen Dienstplan anlegen, obwohl ihre Rolle es vorsah; ein
Konto mit dem Schalter durfte alles, auch wenn die Matrix es ausdrücklich
ausschloss. Beides stand in derselben Datei, zwanzig Mal.

Fremde Abwesenheiten sind der empfindlichste Punkt: eine Krankmeldung ist
ein Gesundheitsdatum (Art. 9 DSGVO). Deshalb hängt schon das *Sehen* am
Recht, über Abwesenheiten zu entscheiden, und nicht am Lesen von
Personalstammdaten — das hat fast jedes Konto.
"""

from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django_grp_org.models import Employee
from django_grp_org.tenancy import limit_to_tenant

from django_grp_backend import rechte
from django_grp_backend.access import WriteNeedsRole
from .models import (
    StaffingRequirement,
    Absence,
    AbsenceType,
    DutyPlan,
    Shift,
    ShiftPreference,
    ShiftSwap,
    ShiftType,
    TimeAccount,
    TimeEntry,
)
from .autofill import autofill_plan, konto_stunden, mitarbeitende
from .bedarf import tagesbedarf
from .rules import check_plan, offene_plaetze
from .services import (
    close_month,
    target_hours_for_month,
    find_substitutes,
    generate_shifts,
    vacation_balance,
)


def current_employee(user):
    """Der Personaldatensatz zum angemeldeten Konto, sofern verknüpft."""
    return Employee.objects.filter(user=user).first()


def require_recht(request, aktion, message=None):
    """
    Verlangt Schreibrecht auf ein Merkmal.

    Hier stand `require_staff(request)`. Der Name war ehrlich — geprüft wurde
    der Schalter — und die Sache falsch: ob jemand einen Dienstplan anlegen
    darf, ist eine andere Frage als ob er in den Django-Admin kommt.
    """
    if not rechte.darf(request.user, aktion, schreiben=True):
        name = rechte.AKTION_LABEL.get(aktion, aktion)
        raise PermissionDenied(message or f"Dafür fehlt das Recht „{name}“.")


def sieht_abwesenheiten(user) -> bool:
    """
    Darf dieses Konto fremde Abwesenheiten sehen?

    Am Recht zu entscheiden und nicht am Lesen der Personalstammdaten: das
    hat fast jedes Konto, und eine Krankmeldung gehört nicht zu den Daten,
    die das ganze Haus sieht.
    """
    return rechte.darf(user, rechte.ABWESENHEIT_GENEHMIGEN)


def sieht_zeiten(user) -> bool:
    """
    Darf dieses Konto fremde Zeitbuchungen sehen?

    Am Abschluss der Zeitkonten: wer einen Monat schließt, muss hineinsehen.
    Eine Gruppenleitung plant Dienste, rechnet aber nicht ab — sie sieht
    deshalb die eigenen Stunden und nicht die des Teams.
    """
    return rechte.darf(user, rechte.ZEITKONTO_ABSCHLIESSEN)


# ---------------------------------------------------------------- Phase 2


class ShiftTypeSerializer(serializers.ModelSerializer):
    duration_hours = serializers.SerializerMethodField()
    on_call_hours = serializers.SerializerMethodField()
    work_hours = serializers.SerializerMethodField()

    class Meta:
        model = ShiftType
        fields = [
            "id",
            "provider",
            "name",
            "short_code",
            "start_time",
            "end_time",
            "break_minutes",
            "color",
            "is_night",
            "on_call_minutes",
            "is_on_call",
            "counts_specialist",
            "duration_hours",
            "on_call_hours",
            "work_hours",
        ]
        # Abgeleitet aus on_call_minutes - siehe ShiftType.save().
        read_only_fields = ["is_on_call"]

    def get_on_call_hours(self, obj):
        return str(obj.on_call_hours)

    def get_work_hours(self, obj):
        return str(obj.work_hours)

    def get_duration_hours(self, obj):
        return str(obj.duration_hours)


class ShiftSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    shift_type_code = serializers.CharField(
        source="shift_type.short_code", read_only=True
    )
    shift_type_name = serializers.CharField(source="shift_type.name", read_only=True)
    color = serializers.CharField(source="shift_type.color", read_only=True)
    start_time = serializers.TimeField(source="shift_type.start_time", read_only=True)
    end_time = serializers.TimeField(source="shift_type.end_time", read_only=True)

    class Meta:
        model = Shift
        fields = [
            "id",
            "plan",
            "date",
            "shift_type",
            "shift_type_code",
            "shift_type_name",
            "color",
            "start_time",
            "end_time",
            "employee",
            "employee_name",
            "is_substitute",
            "note",
        ]
        read_only_fields = ["plan"]

    def get_employee_name(self, obj):
        return obj.employee.get_full_name() if obj.employee_id else None


class DutyPlanSerializer(serializers.ModelSerializer):
    department_name = serializers.SerializerMethodField()
    shift_count = serializers.SerializerMethodField()
    open_shifts = serializers.SerializerMethodField()

    class Meta:
        model = DutyPlan
        fields = [
            "id",
            "department",
            "department_name",
            "year",
            "month",
            "status",
            "note",
            "shift_count",
            "open_shifts",
            "updated_at",
        ]

    def get_department_name(self, obj):
        return str(obj.department)

    def get_shift_count(self, obj):
        return obj.shifts.count()

    def get_open_shifts(self, obj):
        """
        Nur die echten Luecken.

        Vorher war das die Zahl der leeren Plaetze. Der Plan haelt aber je
        Dienstart einen Platz bereit, und besetzt wird davon, was der Tag
        braucht - ein fertiger Monat meldete so sechzig Fehlstellen, die
        keine waren.
        """
        return offene_plaetze(obj)


class ShiftTypeViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, WriteNeedsRole]
    serializer_class = ShiftTypeSerializer
    recht = rechte.ORG_DIENSTARTEN

    def get_queryset(self):
        return limit_to_tenant(ShiftType.objects.all(), self.request.user)

    def perform_create(self, serializer):
        serializer.save()

    def perform_update(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        instance.delete()


class StaffingRequirementSerializer(serializers.ModelSerializer):
    shift_type_name = serializers.CharField(source="shift_type.name", read_only=True)
    scope_label = serializers.CharField(read_only=True)

    class Meta:
        model = StaffingRequirement
        fields = [
            "id",
            "department",
            "shift_type",
            "shift_type_name",
            "starts_at",
            "ends_at",
            "minimum_staff",
            "minimum_specialists",
            "note",
            "scope_label",
        ]

    def validate(self, attrs):
        """
        Genau eine Art von Geltungsbereich - Dienstart oder Uhrzeit-Fenster.

        Die Regel steht im Modell (clean); hier wird sie ausgeloest, damit die
        Schnittstelle eine verstaendliche Meldung liefert statt eines
        Datenbankfehlers. Bei einer Teiländerung (PATCH) kommen nur die
        geänderten Felder an, deshalb werden sie über den vorhandenen Stand
        gelegt.
        """
        from django.core.exceptions import ValidationError as DjangoValidationError

        felder = {
            "department": None,
            "shift_type": None,
            "starts_at": None,
            "ends_at": None,
            "minimum_staff": 0,
            "minimum_specialists": 0,
        }
        stand = {
            name: getattr(self.instance, name, vorgabe) if self.instance else vorgabe
            for name, vorgabe in felder.items()
        }
        entwurf = StaffingRequirement(
            **{
                **stand,
                **{name: wert for name, wert in attrs.items() if name in felder},
            }
        )

        try:
            entwurf.clean()
        except DjangoValidationError as fehler:
            raise ValidationError(fehler.messages)
        return attrs


class StaffingRequirementViewSet(viewsets.ModelViewSet):
    """Besetzungsvorgaben je Bereich - nach Dienstart oder Uhrzeit-Fenster."""

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    serializer_class = StaffingRequirementSerializer
    # Dieselbe Zeile wie die Dienstarten: wer festlegt, welche Dienste es
    # gibt, legt auch fest, wie viele davon besetzt sein muessen.
    recht = rechte.ORG_DIENSTARTEN

    def get_queryset(self):
        queryset = StaffingRequirement.objects.select_related(
            "department", "shift_type"
        )
        bereich = self.request.query_params.get("bereich")
        if bereich:
            queryset = queryset.filter(department_id=bereich)
        return queryset

    def perform_create(self, serializer):
        serializer.save()

    def perform_update(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        instance.delete()


class DutyPlanViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, WriteNeedsRole]
    serializer_class = DutyPlanSerializer
    recht = rechte.DIENSTPLAN_BEARBEITEN

    def get_queryset(self):
        queryset = limit_to_tenant(
            DutyPlan.objects.select_related("department__facility").prefetch_related(
                "shifts"
            ),
            self.request.user,
            "department__facility__site__provider_id",
        )
        department = self.request.query_params.get("bereich")
        year = self.request.query_params.get("jahr")
        month = self.request.query_params.get("monat")
        if department:
            queryset = queryset.filter(department_id=department)
        if year:
            queryset = queryset.filter(year=year)
        if month:
            queryset = queryset.filter(month=month)
        return queryset

    def perform_create(self, serializer):
        serializer.save()

    def perform_update(self, serializer):
        if not serializer.instance.is_editable:
            raise ValidationError("Abgeschlossene Dienstpläne sind gesperrt.")

        # Veröffentlichen ist eine eigene Zeile der Matrix, und hier ist die
        # einzige Stelle, an der es passiert: der Status wandert von
        # „Entwurf" auf „Veröffentlicht". Danach sehen alle den Plan - wer
        # ihn bauen darf, darf ihn nicht zwangsläufig verbindlich machen.
        neuer_status = serializer.validated_data.get(
            "status", serializer.instance.status
        )
        if neuer_status != serializer.instance.status and neuer_status != "draft":
            require_recht(
                self.request,
                rechte.DIENSTPLAN_FREIGEBEN,
                "Einen Dienstplan freigeben darf nur, wer das Recht "
                "„Dienstplan freigeben“ hat.",
            )
        serializer.save()

    def perform_destroy(self, instance):
        instance.delete()


class ShiftViewSet(viewsets.ModelViewSet):
    """Dienste eines Plans, verschachtelt unter /duty-plan/{id}/shift/."""

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    serializer_class = ShiftSerializer
    recht = rechte.DIENSTPLAN_BEARBEITEN

    def get_plan(self):
        plan_id = self.kwargs.get("plan_pk")
        return DutyPlan.objects.filter(id=plan_id).select_related("department").first()

    def get_queryset(self):
        plan = self.get_plan()
        if plan is None:
            return Shift.objects.none()
        return Shift.objects.filter(plan=plan).select_related("shift_type", "employee")

    def _writable_plan(self):
        plan = self.get_plan()
        if plan is None:
            raise ValidationError("Dienstplan nicht gefunden.")
        if not plan.is_editable:
            raise ValidationError("Abgeschlossene Dienstpläne sind gesperrt.")
        return plan

    def perform_create(self, serializer):
        serializer.save(plan=self._writable_plan())

    def perform_update(self, serializer):
        self._writable_plan()
        serializer.save()

    def perform_destroy(self, instance):
        self._writable_plan()
        instance.delete()


class DutyPlanRulesView(APIView):
    """Regelprüfung eines Dienstplans."""

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    recht_lesen = rechte.DIENSTPLAN_BEARBEITEN

    def get(self, request, plan_id: int):
        plan = DutyPlan.objects.filter(id=plan_id).select_related("department").first()
        if plan is None:
            return Response({"error": "Dienstplan nicht gefunden."}, status=404)

        violations = [item.as_dict() for item in check_plan(plan)]
        return Response(
            {
                "plan": plan.id,
                "errors": sum(1 for v in violations if v["severity"] == "error"),
                "warnings": sum(1 for v in violations if v["severity"] == "warning"),
                "violations": violations,
            }
        )


class DutyPlanBedarfView(APIView):
    """
    Was ein Monat nach den Besetzungsvorgaben kosten wuerde - vor dem
    Anlegen.

    Beantwortet die Frage, die man sonst erst nach dem Anlegen und Besetzen
    beantwortet bekam: reicht das Team fuer diesen Plan? Bisher entstanden
    stur drei Plaetze taeglich, und am Monatsende hatten alle Ueberstunden.
    Jetzt steht die Rechnung vorher da.
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    recht_lesen = rechte.DIENSTPLAN_BEARBEITEN

    def get(self, request, plan_id: int):
        plan = DutyPlan.objects.filter(id=plan_id).select_related(
            "department"
        ).first()
        if plan is None:
            return Response({"error": "Dienstplan nicht gefunden."}, status=404)

        roh = request.query_params.get("shift_types", "")
        ids = [int(teil) for teil in roh.split(",") if teil.strip().isdigit()]
        arten = list(
            limit_to_tenant(ShiftType.objects.all(), request.user).filter(id__in=ids)
            if ids
            else limit_to_tenant(ShiftType.objects.all(), request.user)
        )

        bedarf = tagesbedarf(plan.department, arten)
        tage = monthrange(plan.year, plan.month)[1]

        # Gerechnet wird in Kontostunden und nicht in Uhrzeiten: Bereitschaft
        # zaehlt zur Haelfte, wie bei der Zeitbuchung. Sonst sieht ein
        # 24-Stunden-Dienst nach 24 Stunden aus und die Gegenueberstellung
        # mit dem Monatssoll waere schief.
        arten_nach_id = {art.id: art for art in arten}
        stunden_tag = sum(
            (
                konto_stunden(arten_nach_id[art_id]) * anzahl
                for art_id, anzahl in bedarf.items()
                if anzahl and art_id in arten_nach_id
            ),
            Decimal("0"),
        )

        # Dasselbe Team, das auch der Automat besetzen wuerde.
        team = mitarbeitende(plan.department)
        kapazitaet = sum(
            (target_hours_for_month(person, plan.year, plan.month) for person in team),
            Decimal("0"),
        )

        return Response(
            {
                "plan": plan.id,
                "tage": tage,
                "je_tag": [
                    {
                        "shift_type": art.id,
                        "name": art.name,
                        "short_code": art.short_code,
                        "anzahl": bedarf.get(art.id, 0),
                        "stunden": str(konto_stunden(art)),
                    }
                    for art in arten
                    if bedarf.get(art.id, 0)
                ],
                "stunden_tag": str(stunden_tag),
                "stunden_monat": str(stunden_tag * tage),
                "kapazitaet_monat": str(kapazitaet),
                "personen": len(team),
            }
        )


class DutyPlanGenerateView(APIView):
    """Legt die Dienste eines Monats an, zunächst alle unbesetzt."""

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    recht = rechte.DIENSTPLAN_BEARBEITEN

    def post(self, request, plan_id: int):
        plan = DutyPlan.objects.filter(id=plan_id).first()
        if plan is None:
            return Response({"error": "Dienstplan nicht gefunden."}, status=404)
        if not plan.is_editable:
            return Response({"error": "Dienstplan ist gesperrt."}, status=403)

        type_ids = request.data.get("shift_types") or []
        weekdays = request.data.get("weekdays")
        shift_types = ShiftType.objects.filter(id__in=type_ids)
        if not shift_types:
            return Response(
                {"error": "Bitte mindestens eine Dienstart wählen."}, status=400
            )

        created = generate_shifts(plan, shift_types, weekdays)
        return Response({"created": created})


class DutyPlanAutofillView(APIView):
    """Besetzt die offenen Dienste eines Plans automatisch."""

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    recht = rechte.DIENSTPLAN_BEARBEITEN

    def post(self, request, plan_id: int):
        plan = (
            DutyPlan.objects.filter(id=plan_id)
            .select_related("department__facility__site__provider")
            .first()
        )
        if plan is None:
            return Response({"error": "Dienstplan nicht gefunden."}, status=404)
        if not plan.is_editable:
            return Response({"error": "Dienstplan ist gesperrt."}, status=403)

        # Neu verteilen loescht bestehende Einteilungen - das muss die
        # Oberflaeche ausdruecklich verlangen, nicht versehentlich ausloesen.
        overwrite = bool(request.data.get("overwrite"))
        return Response(autofill_plan(plan, overwrite=overwrite))


class SubstituteSearchView(APIView):
    """
    Wer könnte diesen Dienst übernehmen?

    Die Antwort nennt Namen, Qualifikationen und Ruhezeiten fremder Personen.
    Deshalb am Dienstplanrecht und nicht fuer jeden Angemeldeten.
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    recht_lesen = rechte.DIENSTPLAN_BEARBEITEN

    def get(self, request, shift_id: int):
        shift = (
            Shift.objects.filter(id=shift_id)
            .select_related("shift_type", "plan__department__facility__site")
            .first()
        )
        if shift is None:
            return Response({"error": "Dienst nicht gefunden."}, status=404)
        return Response(find_substitutes(shift))


# ---------------------------------------------------------------- Phase 3


class AbsenceTypeSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = AbsenceType
        fields = [
            "id",
            "provider",
            "name",
            "kind",
            "kind_display",
            "reduces_vacation",
            "requires_approval",
            "color",
        ]


class AbsenceSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    type_name = serializers.CharField(source="absence_type.name", read_only=True)
    color = serializers.CharField(source="absence_type.color", read_only=True)
    days = serializers.IntegerField(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Absence
        fields = [
            "id",
            "employee",
            "employee_name",
            "absence_type",
            "type_name",
            "color",
            "start_date",
            "end_date",
            "days",
            "status",
            "status_display",
            "note",
            "decided_by",
            "decided_at",
            "decision_note",
        ]
        read_only_fields = ["decided_by", "decided_at"]

    def get_employee_name(self, obj):
        return obj.employee.get_full_name()

    def validate(self, attrs):
        start = attrs.get("start_date") or getattr(self.instance, "start_date", None)
        end = attrs.get("end_date") or getattr(self.instance, "end_date", None)
        if start and end and end < start:
            raise serializers.ValidationError(
                {"end_date": "Das Ende darf nicht vor dem Beginn liegen."}
            )
        return attrs


class AbsenceTypeViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, WriteNeedsRole]
    # Wer ueber Abwesenheiten entscheidet, legt auch fest, welche Arten es
    # gibt. Eine eigene Zeile dafuer waere eine Zeile zu viel.
    recht = rechte.ABWESENHEIT_GENEHMIGEN
    serializer_class = AbsenceTypeSerializer

    def get_queryset(self):
        return limit_to_tenant(AbsenceType.objects.all(), self.request.user)

    def perform_create(self, serializer):
        serializer.save()

    def perform_update(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        instance.delete()


class AbsenceViewSet(viewsets.ModelViewSet):
    """
    Abwesenheitsanträge.

    Jede Person stellt eigene Anträge - dafür braucht es kein Merkmal. Über
    den Status entscheidet, wer das Recht „Abwesenheiten“ hat; sonst könnte
    sich jede Person den Urlaub selbst genehmigen.

    Fremde Anträge sieht nur, wer sie entscheiden darf. Eine Krankmeldung ist
    ein Gesundheitsdatum, und sie steht hier mit Grund und Zeitraum.
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    serializer_class = AbsenceSerializer
    # Eigene Anträge gehören jedem Konto. Was darüber hinausgeht, prüfen die
    # Methoden unten - mit dem Antrag in der Hand.
    recht = None

    def get_queryset(self):
        queryset = limit_to_tenant(
            Absence.objects.select_related("employee", "absence_type", "decided_by"),
            self.request.user,
            "employee__provider_id",
        )
        if not sieht_abwesenheiten(self.request.user):
            queryset = queryset.filter(employee__user=self.request.user)

        employee = self.request.query_params.get("mitarbeiter")
        status_filter = self.request.query_params.get("status")
        if employee:
            queryset = queryset.filter(employee_id=employee)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset

    def _entscheidet(self) -> bool:
        return rechte.darf(
            self.request.user, rechte.ABWESENHEIT_GENEHMIGEN, schreiben=True
        )

    def _eigener_oder_erlaubt(self, employee_id):
        if self._entscheidet():
            return
        own = current_employee(self.request.user)
        if own is None or own.id != employee_id:
            raise PermissionDenied("Du kannst nur eigene Anträge bearbeiten.")

    def perform_create(self, serializer):
        employee_id = serializer.validated_data["employee"].id
        self._eigener_oder_erlaubt(employee_id)

        # Über den Status entscheidet die Leitung, nicht die antragstellende
        # Person - deshalb startet jeder Antrag als "beantragt".
        status_value = serializer.validated_data.get("status", "requested")
        if not self._entscheidet():
            status_value = "requested"
        serializer.save(status=status_value)

    def perform_update(self, serializer):
        instance = serializer.instance
        self._eigener_oder_erlaubt(instance.employee_id)

        entscheidet = self._entscheidet()
        new_status = serializer.validated_data.get("status", instance.status)
        if new_status != instance.status and not entscheidet:
            # Zurückziehen darf man selbst, genehmigen nicht.
            if new_status != "cancelled":
                raise PermissionDenied("Über Anträge entscheidet die Leitung.")

        extra = {}
        if new_status in ("approved", "rejected") and entscheidet:
            extra = {
                "decided_by": current_employee(self.request.user),
                "decided_at": timezone.now(),
            }
        serializer.save(**extra)

    def perform_destroy(self, instance):
        self._eigener_oder_erlaubt(instance.employee_id)
        instance.delete()


class VacationBalanceView(APIView):
    """Urlaubskonto einer Person für ein Jahr."""

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    recht_lesen = None

    def get(self, request, employee_id: int):
        employee = Employee.objects.filter(id=employee_id).first()
        if employee is None:
            return Response({"error": "Mitarbeitende nicht gefunden."}, status=404)
        fremd = employee.user_id != request.user.id
        if fremd and not sieht_abwesenheiten(request.user):
            raise PermissionDenied("Nur das eigene Urlaubskonto ist einsehbar.")

        year = int(request.query_params.get("jahr") or date.today().year)
        return Response(
            {"employee": employee.id, "year": year, **vacation_balance(employee, year)}
        )


# ---------------------------------------------------------------- Phase 4


class TimeEntrySerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    hours = serializers.SerializerMethodField()
    credited_hours = serializers.SerializerMethodField()
    category_display = serializers.CharField(
        source="get_category_display", read_only=True
    )

    class Meta:
        model = TimeEntry
        fields = [
            "id",
            "employee",
            "employee_name",
            "shift",
            "date",
            "start_time",
            "end_time",
            "break_minutes",
            "category",
            "category_display",
            "note",
            "approved",
            "hours",
            "credited_hours",
        ]
        read_only_fields = ["approved"]

    def get_employee_name(self, obj):
        return obj.employee.get_full_name()

    def get_hours(self, obj):
        return str(obj.hours)

    def get_credited_hours(self, obj):
        return str(obj.credited_hours)


class TimeAccountSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    class Meta:
        model = TimeAccount
        fields = [
            "id",
            "employee",
            "employee_name",
            "year",
            "month",
            "target_hours",
            "actual_hours",
            "carry_over",
            "on_call_hours",
            "night_hours",
            "balance",
            "closed_at",
        ]

    def get_employee_name(self, obj):
        return obj.employee.get_full_name()

    def get_balance(self, obj):
        return str(obj.balance)


class TimeEntryViewSet(viewsets.ModelViewSet):
    """
    Zeitbuchungen.

    Die eigenen bucht jedes Konto mit dem Recht „Zeiterfassung“ - das haben
    auch Aushilfen, weil sonst niemand ihre Stunden erfassen könnte. Fremde
    Buchungen sieht und ändert nur, wer Zeitkonten abschließt.
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    serializer_class = TimeEntrySerializer
    recht = rechte.ZEIT_ERFASSEN

    def get_queryset(self):
        queryset = limit_to_tenant(
            TimeEntry.objects.select_related("employee", "shift__shift_type"),
            self.request.user,
            "employee__provider_id",
        )
        if not sieht_zeiten(self.request.user):
            queryset = queryset.filter(employee__user=self.request.user)

        employee = self.request.query_params.get("mitarbeiter")
        year = self.request.query_params.get("jahr")
        month = self.request.query_params.get("monat")
        if employee:
            queryset = queryset.filter(employee_id=employee)
        if year:
            queryset = queryset.filter(date__year=year)
        if month:
            queryset = queryset.filter(date__month=month)
        return queryset

    def _darf_abschliessen(self) -> bool:
        return rechte.darf(
            self.request.user, rechte.ZEITKONTO_ABSCHLIESSEN, schreiben=True
        )

    def _eigene_oder_erlaubt(self, employee_id):
        if self._darf_abschliessen():
            return
        own = current_employee(self.request.user)
        if own is None or own.id != employee_id:
            raise PermissionDenied("Du kannst nur eigene Zeiten erfassen.")

    def perform_create(self, serializer):
        self._eigene_oder_erlaubt(serializer.validated_data["employee"].id)
        serializer.save()

    def perform_update(self, serializer):
        self._eigene_oder_erlaubt(serializer.instance.employee_id)
        if serializer.instance.approved and not self._darf_abschliessen():
            raise PermissionDenied("Freigegebene Buchungen sind gesperrt.")
        serializer.save()

    def perform_destroy(self, instance):
        self._eigene_oder_erlaubt(instance.employee_id)
        if instance.approved and not self._darf_abschliessen():
            raise PermissionDenied("Freigegebene Buchungen sind gesperrt.")
        instance.delete()


class TimeEntryApprovalView(APIView):
    """Zeitbuchungen freigeben - wer Zeitkonten abschließt."""

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    recht = rechte.ZEITKONTO_ABSCHLIESSEN

    def post(self, request):
        ids = request.data.get("entries") or []
        approved = bool(request.data.get("approved", True))
        count = TimeEntry.objects.filter(id__in=ids).update(approved=approved)
        return Response({"updated": count, "approved": approved})


class TimeAccountViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, WriteNeedsRole]
    serializer_class = TimeAccountSerializer
    # Das eigene Konto sieht jeder, fremde nur wer sie abschließt.
    recht_lesen = None

    def get_queryset(self):
        queryset = limit_to_tenant(
            TimeAccount.objects.select_related("employee"),
            self.request.user,
            "employee__provider_id",
        )
        if not sieht_zeiten(self.request.user):
            queryset = queryset.filter(employee__user=self.request.user)
        year = self.request.query_params.get("jahr")
        if year:
            queryset = queryset.filter(year=year)
        return queryset


class CloseMonthView(APIView):
    """Monatsabschluss: Zeitkonten neu berechnen."""

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    recht = rechte.ZEITKONTO_ABSCHLIESSEN

    def post(self, request):
        year = int(request.data.get("year") or date.today().year)
        month = int(request.data.get("month") or date.today().month)
        employee_ids = request.data.get("employees")

        employees = limit_to_tenant(
            Employee.objects.filter(left_on__isnull=True), request.user
        )
        if employee_ids:
            employees = employees.filter(id__in=employee_ids)

        accounts = [close_month(employee, year, month) for employee in employees]
        return Response(
            TimeAccountSerializer(
                accounts, many=True, context={"request": request}
            ).data
        )


# ---------------------------------------------------------------- Phase 7


class MyDutyView(APIView):
    """
    SelfService: die eigenen Dienste, Abwesenheiten und das Zeitkonto.

    Eine Abfrage statt vier, weil die Startseite der Mitarbeitenden alles
    zusammen zeigt.
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    # Ausschließlich eigene Daten: der Endpunkt liest den Personaldatensatz
    # des angemeldeten Kontos und nimmt keine fremde Nummer an.
    recht_lesen = None

    def get(self, request):
        employee = current_employee(request.user)
        if employee is None:
            return Response(
                {
                    "employee": None,
                    "message": "Zu diesem Konto ist kein Personaldatensatz hinterlegt.",
                    "shifts": [],
                    "absences": [],
                    "time_accounts": [],
                }
            )

        today = date.today()
        shifts = (
            Shift.objects.filter(employee=employee, date__gte=today)
            .select_related("shift_type", "plan__department")
            .order_by("date")[:30]
        )
        absences = (
            Absence.objects.filter(employee=employee)
            .filter(Q(end_date__gte=today) | Q(status="requested"))
            .select_related("absence_type")[:20]
        )
        accounts = TimeAccount.objects.filter(employee=employee).order_by(
            "-year", "-month"
        )[:6]

        return Response(
            {
                "employee": employee.id,
                "employee_name": employee.get_full_name(),
                "shifts": ShiftSerializer(
                    shifts, many=True, context={"request": request}
                ).data,
                "absences": AbsenceSerializer(
                    absences, many=True, context={"request": request}
                ).data,
                "time_accounts": TimeAccountSerializer(
                    accounts, many=True, context={"request": request}
                ).data,
                "vacation": vacation_balance(employee, today.year),
            }
        )


# ---------------------------------------------------------------- Phase 7


class ShiftPreferenceSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    shift_type_code = serializers.SerializerMethodField()

    class Meta:
        model = ShiftPreference
        fields = [
            "id",
            "employee",
            "employee_name",
            "date",
            "shift_type",
            "shift_type_code",
            "kind",
            "kind_display",
            "note",
        ]

    def get_employee_name(self, obj):
        return obj.employee.get_full_name()

    def get_shift_type_code(self, obj):
        return obj.shift_type.short_code if obj.shift_type_id else None


class ShiftSwapSerializer(serializers.ModelSerializer):
    offered_by_name = serializers.SerializerMethodField()
    accepted_by_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    shift_date = serializers.DateField(source="shift.date", read_only=True)
    shift_label = serializers.SerializerMethodField()

    class Meta:
        model = ShiftSwap
        fields = [
            "id",
            "shift",
            "shift_date",
            "shift_label",
            "offered_by",
            "offered_by_name",
            "accepted_by",
            "accepted_by_name",
            "status",
            "status_display",
            "reason",
            "decided_by",
        ]
        read_only_fields = ["decided_by"]

    def get_offered_by_name(self, obj):
        return obj.offered_by.get_full_name()

    def get_accepted_by_name(self, obj):
        return obj.accepted_by.get_full_name() if obj.accepted_by_id else None

    def get_shift_label(self, obj):
        return f"{obj.shift.shift_type.short_code} {obj.shift.shift_type.name}"


class ShiftPreferenceViewSet(viewsets.ModelViewSet):
    """
    Dienstwünsche.

    Jede Person pflegt die eigenen - dafür braucht es kein Merkmal, ein
    Wunsch ist eine Angabe und keine Zusage. Alle Wünsche sieht, wer den Plan
    baut; er muss sie ja berücksichtigen können.
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    serializer_class = ShiftPreferenceSerializer
    recht = None

    def get_queryset(self):
        queryset = limit_to_tenant(
            ShiftPreference.objects.select_related("employee", "shift_type"),
            self.request.user,
            "employee__provider_id",
        )
        if not rechte.darf(self.request.user, rechte.DIENSTPLAN_BEARBEITEN):
            queryset = queryset.filter(employee__user=self.request.user)

        month = self.request.query_params.get("monat")
        year = self.request.query_params.get("jahr")
        if year:
            queryset = queryset.filter(date__year=year)
        if month:
            queryset = queryset.filter(date__month=month)
        return queryset

    def _eigener_oder_erlaubt(self, employee_id):
        if rechte.darf(
            self.request.user, rechte.DIENSTPLAN_BEARBEITEN, schreiben=True
        ):
            return
        own = current_employee(self.request.user)
        if own is None or own.id != employee_id:
            raise PermissionDenied("Du kannst nur eigene Wünsche eintragen.")

    def perform_create(self, serializer):
        self._eigener_oder_erlaubt(serializer.validated_data["employee"].id)
        serializer.save()

    def perform_update(self, serializer):
        self._eigener_oder_erlaubt(serializer.instance.employee_id)
        serializer.save()

    def perform_destroy(self, instance):
        self._eigener_oder_erlaubt(instance.employee_id)
        instance.delete()


class ShiftSwapViewSet(viewsets.ModelViewSet):
    """
    Diensttausch.

    Anbieten und Annehmen darf jede betroffene Person - dafür braucht es
    kein Merkmal. Bestätigen darf, wer den Dienstplan bearbeiten darf: mit
    der Bestätigung wechselt der Dienst, und das ist eine Planänderung.
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    serializer_class = ShiftSwapSerializer
    recht = None

    def get_queryset(self):
        queryset = limit_to_tenant(
            ShiftSwap.objects.select_related(
                "shift__shift_type", "offered_by", "accepted_by"
            ),
            self.request.user,
            "offered_by__provider_id",
        )
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset

    def _plant(self) -> bool:
        return rechte.darf(
            self.request.user, rechte.DIENSTPLAN_BEARBEITEN, schreiben=True
        )

    def perform_create(self, serializer):
        own = current_employee(self.request.user)
        offered_by = serializer.validated_data["offered_by"]
        if not self._plant() and (own is None or own.id != offered_by.id):
            raise PermissionDenied("Du kannst nur eigene Dienste anbieten.")

        shift = serializer.validated_data["shift"]
        if shift.employee_id != offered_by.id:
            raise ValidationError("Dieser Dienst gehört nicht zur angebotenen Person.")
        serializer.save(status="offered")

    def perform_update(self, serializer):
        instance = serializer.instance
        own = current_employee(self.request.user)
        new_status = serializer.validated_data.get("status", instance.status)

        if new_status == "confirmed" and not self._plant():
            raise PermissionDenied("Einen Tausch bestätigt die Dienstplanung.")

        if new_status == "accepted":
            # Wer annimmt, trägt sich selbst ein - nicht jemand anderen.
            accepted_by = serializer.validated_data.get("accepted_by")
            if not self._plant() and (
                own is None or accepted_by is None or accepted_by.id != own.id
            ):
                raise PermissionDenied("Du kannst den Tausch nur selbst annehmen.")

        extra = {}
        if new_status == "confirmed":
            extra["decided_by"] = current_employee(self.request.user)
        serializer.save(**extra)

    def perform_destroy(self, instance):
        own = current_employee(self.request.user)
        if not self._plant() and (own is None or own.id != instance.offered_by_id):
            raise PermissionDenied("Du kannst nur eigene Angebote zurückziehen.")
        instance.delete()


class PayrollExportView(APIView):
    """
    Abrechnungszeilen für die Lohnbuchhaltung (Phase 4).

    Liefert je Person und Lohnart eine Zeile. Fehlende Monatsabschlüsse
    werden mitgeliefert, damit niemand eine unvollständige Übergabe für
    vollständig hält.
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    # Eine GET-Anfrage, und bis hierher reichte dafür `is_staff`. Die Zeilen
    # nennen jede Person mit Stunden, Zuschlägen und Lohnart - das ist die
    # Gehaltsabrechnung des ganzen Hauses.
    recht_lesen = rechte.NACHWEISE

    def get(self, request):
        from .payroll import build_rows, missing_accounts, wage_types

        year = int(request.query_params.get("jahr") or date.today().year)
        month = int(request.query_params.get("monat") or date.today().month)

        return Response(
            {
                "year": year,
                "month": month,
                "wage_types": {
                    key: {"number": number, "label": label}
                    for key, (number, label) in wage_types().items()
                },
                "rows": build_rows(request.user, year, month),
                "missing_accounts": missing_accounts(request.user, year, month),
            }
        )
