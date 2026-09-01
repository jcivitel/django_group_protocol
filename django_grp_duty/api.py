"""
API für Dienstplanung, Abwesenheiten und Zeiterfassung (Phasen 2 bis 4)
sowie die SelfService-Sichten aus Phase 7.

Zugriffsregel: Personal sieht alles, alle anderen ausschließlich die eigenen
Daten. Das gilt für Dienste, Abwesenheitsanträge, Zeitbuchungen und
Zeitkonten gleichermaßen.
"""

from datetime import date

from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django_grp_org.models import Employee

from .models import (
    Absence,
    AbsenceType,
    DutyPlan,
    Shift,
    ShiftType,
    TimeAccount,
    TimeEntry,
)
from .rules import check_plan
from .services import (
    close_month,
    find_substitutes,
    generate_shifts,
    vacation_balance,
)


def current_employee(user):
    """Der Personaldatensatz zum angemeldeten Konto, sofern verknüpft."""
    return Employee.objects.filter(user=user).first()


def require_staff(request, message="Nur Mitarbeitende dürfen das ändern."):
    if not request.user.is_staff:
        raise PermissionDenied(message)


# ---------------------------------------------------------------- Phase 2


class ShiftTypeSerializer(serializers.ModelSerializer):
    duration_hours = serializers.SerializerMethodField()

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
            "is_on_call",
            "counts_specialist",
            "duration_hours",
        ]

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
        return obj.shifts.filter(employee__isnull=True).count()


class ShiftTypeViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ShiftTypeSerializer
    queryset = ShiftType.objects.all()

    def perform_create(self, serializer):
        require_staff(self.request)
        serializer.save()

    def perform_update(self, serializer):
        require_staff(self.request)
        serializer.save()

    def perform_destroy(self, instance):
        require_staff(self.request)
        instance.delete()


class DutyPlanViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = DutyPlanSerializer
    queryset = DutyPlan.objects.select_related("department__facility").prefetch_related(
        "shifts"
    )

    def get_queryset(self):
        queryset = super().get_queryset()
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
        require_staff(self.request, "Nur Mitarbeitende dürfen Dienstpläne anlegen.")
        serializer.save()

    def perform_update(self, serializer):
        require_staff(self.request, "Nur Mitarbeitende dürfen Dienstpläne ändern.")
        if not serializer.instance.is_editable:
            raise ValidationError("Abgeschlossene Dienstpläne sind gesperrt.")
        serializer.save()

    def perform_destroy(self, instance):
        require_staff(self.request, "Nur Mitarbeitende dürfen Dienstpläne löschen.")
        instance.delete()


class ShiftViewSet(viewsets.ModelViewSet):
    """Dienste eines Plans, verschachtelt unter /duty-plan/{id}/shift/."""

    permission_classes = [IsAuthenticated]
    serializer_class = ShiftSerializer

    def get_plan(self):
        plan_id = self.kwargs.get("plan_pk")
        return DutyPlan.objects.filter(id=plan_id).select_related("department").first()

    def get_queryset(self):
        plan = self.get_plan()
        if plan is None:
            return Shift.objects.none()
        return Shift.objects.filter(plan=plan).select_related("shift_type", "employee")

    def _writable_plan(self):
        require_staff(self.request, "Nur Mitarbeitende dürfen Dienste ändern.")
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

    permission_classes = [IsAuthenticated]

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


class DutyPlanGenerateView(APIView):
    """Legt die Dienste eines Monats an, zunächst alle unbesetzt."""

    permission_classes = [IsAuthenticated]

    def post(self, request, plan_id: int):
        require_staff(request, "Nur Mitarbeitende dürfen Dienste anlegen.")
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


class SubstituteSearchView(APIView):
    """Wer könnte diesen Dienst übernehmen?"""

    permission_classes = [IsAuthenticated]

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
    permission_classes = [IsAuthenticated]
    serializer_class = AbsenceTypeSerializer
    queryset = AbsenceType.objects.all()

    def perform_create(self, serializer):
        require_staff(self.request)
        serializer.save()

    def perform_update(self, serializer):
        require_staff(self.request)
        serializer.save()

    def perform_destroy(self, instance):
        require_staff(self.request)
        instance.delete()


class AbsenceViewSet(viewsets.ModelViewSet):
    """
    Abwesenheitsanträge.

    Wer kein Personal ist, sieht und stellt nur eigene Anträge. Über den
    Status entscheidet ausschließlich Personal - sonst könnte sich jede
    Person den Urlaub selbst genehmigen.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = AbsenceSerializer

    def get_queryset(self):
        queryset = Absence.objects.select_related(
            "employee", "absence_type", "decided_by"
        )
        if not self.request.user.is_staff:
            queryset = queryset.filter(employee__user=self.request.user)

        employee = self.request.query_params.get("mitarbeiter")
        status_filter = self.request.query_params.get("status")
        if employee:
            queryset = queryset.filter(employee_id=employee)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset

    def _own_or_staff(self, employee_id):
        if self.request.user.is_staff:
            return
        own = current_employee(self.request.user)
        if own is None or own.id != employee_id:
            raise PermissionDenied("Du kannst nur eigene Anträge bearbeiten.")

    def perform_create(self, serializer):
        employee_id = serializer.validated_data["employee"].id
        self._own_or_staff(employee_id)

        # Über den Status entscheidet die Leitung, nicht die antragstellende
        # Person - deshalb startet jeder Antrag als "beantragt".
        status_value = serializer.validated_data.get("status", "requested")
        if not self.request.user.is_staff:
            status_value = "requested"
        serializer.save(status=status_value)

    def perform_update(self, serializer):
        instance = serializer.instance
        self._own_or_staff(instance.employee_id)

        new_status = serializer.validated_data.get("status", instance.status)
        if new_status != instance.status and not self.request.user.is_staff:
            # Zurückziehen darf man selbst, genehmigen nicht.
            if new_status != "cancelled":
                raise PermissionDenied("Über Anträge entscheidet die Leitung.")

        extra = {}
        if new_status in ("approved", "rejected") and self.request.user.is_staff:
            extra = {
                "decided_by": current_employee(self.request.user),
                "decided_at": timezone.now(),
            }
        serializer.save(**extra)

    def perform_destroy(self, instance):
        self._own_or_staff(instance.employee_id)
        instance.delete()


class VacationBalanceView(APIView):
    """Urlaubskonto einer Person für ein Jahr."""

    permission_classes = [IsAuthenticated]

    def get(self, request, employee_id: int):
        employee = Employee.objects.filter(id=employee_id).first()
        if employee is None:
            return Response({"error": "Mitarbeitende nicht gefunden."}, status=404)
        if not request.user.is_staff and employee.user_id != request.user.id:
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
    permission_classes = [IsAuthenticated]
    serializer_class = TimeEntrySerializer

    def get_queryset(self):
        queryset = TimeEntry.objects.select_related("employee", "shift__shift_type")
        if not self.request.user.is_staff:
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

    def _own_or_staff(self, employee_id):
        if self.request.user.is_staff:
            return
        own = current_employee(self.request.user)
        if own is None or own.id != employee_id:
            raise PermissionDenied("Du kannst nur eigene Zeiten erfassen.")

    def perform_create(self, serializer):
        self._own_or_staff(serializer.validated_data["employee"].id)
        serializer.save()

    def perform_update(self, serializer):
        self._own_or_staff(serializer.instance.employee_id)
        if serializer.instance.approved and not self.request.user.is_staff:
            raise PermissionDenied("Freigegebene Buchungen sind gesperrt.")
        serializer.save()

    def perform_destroy(self, instance):
        self._own_or_staff(instance.employee_id)
        if instance.approved and not self.request.user.is_staff:
            raise PermissionDenied("Freigegebene Buchungen sind gesperrt.")
        instance.delete()


class TimeEntryApprovalView(APIView):
    """Zeitbuchungen freigeben - nur durch Personal."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_staff(request, "Nur Mitarbeitende dürfen Zeiten freigeben.")
        ids = request.data.get("entries") or []
        approved = bool(request.data.get("approved", True))
        count = TimeEntry.objects.filter(id__in=ids).update(approved=approved)
        return Response({"updated": count, "approved": approved})


class TimeAccountViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = TimeAccountSerializer

    def get_queryset(self):
        queryset = TimeAccount.objects.select_related("employee")
        if not self.request.user.is_staff:
            queryset = queryset.filter(employee__user=self.request.user)
        year = self.request.query_params.get("jahr")
        if year:
            queryset = queryset.filter(year=year)
        return queryset


class CloseMonthView(APIView):
    """Monatsabschluss: Zeitkonten neu berechnen."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_staff(request, "Nur Mitarbeitende dürfen Monate abschließen.")
        year = int(request.data.get("year") or date.today().year)
        month = int(request.data.get("month") or date.today().month)
        employee_ids = request.data.get("employees")

        employees = Employee.objects.filter(left_on__isnull=True)
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

    permission_classes = [IsAuthenticated]

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
