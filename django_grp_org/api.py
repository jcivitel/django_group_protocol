"""
API für Organisationsstruktur und Personalstammdaten (Phasen 0 und 1).

Lesen darf jede angemeldete Person, schreiben nur Personal (is_staff).
Personaldaten sind sensibel: wer kein Personal ist, sieht von anderen nur
Name und Qualifikation, nicht Vertrag oder Geburtsdatum.
"""

from decimal import Decimal

from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .tenancy import limit_to_tenant, tenant_providers
from .models import (
    Contract,
    Department,
    Employee,
    EmployeeQualification,
    Facility,
    Position,
    PositionAssignment,
    Provider,
    Qualification,
    Role,
    Site,
    WorkTimeModel,
)


class StaffWritableViewSet(viewsets.ModelViewSet):
    """Lesen für alle Angemeldeten, Ändern nur für Personal."""

    permission_classes = [IsAuthenticated]

    def _require_staff(self):
        if not self.request.user.is_staff:
            raise PermissionDenied("Nur Mitarbeitende dürfen Stammdaten ändern.")

    def perform_create(self, serializer):
        self._require_staff()
        serializer.save()

    def perform_update(self, serializer):
        self._require_staff()
        serializer.save()

    def perform_destroy(self, instance):
        self._require_staff()
        instance.delete()


# ---------------------------------------------------------------- Struktur


class ProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Provider
        fields = [
            "id",
            "name",
            "short_name",
            "address",
            "postalcode",
            "city",
            "is_active",
        ]


class SiteSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source="provider.name", read_only=True)

    class Meta:
        model = Site
        fields = [
            "id",
            "provider",
            "provider_name",
            "name",
            "address",
            "postalcode",
            "city",
        ]


class FacilitySerializer(serializers.ModelSerializer):
    site_name = serializers.CharField(source="site.name", read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = Facility
        fields = [
            "id",
            "site",
            "site_name",
            "name",
            "kind",
            "kind_display",
            "is_active",
        ]


class DepartmentSerializer(serializers.ModelSerializer):
    facility_name = serializers.CharField(source="facility.name", read_only=True)
    group_name = serializers.SerializerMethodField()
    position_count = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = [
            "id",
            "facility",
            "facility_name",
            "name",
            "group",
            "group_name",
            "minimum_staff",
            "specialist_ratio",
            "position_count",
        ]

    def get_group_name(self, obj):
        return obj.group.name if obj.group_id else None

    def get_position_count(self, obj):
        return obj.positions.count()


# ---------------------------------------------------------------- Personal


class QualificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Qualification
        fields = ["id", "name", "is_specialist", "description"]


class WorkTimeModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkTimeModel
        fields = [
            "id",
            "provider",
            "name",
            "weekly_hours",
            "days_per_week",
            "vacation_days",
            "notes",
        ]


class EmployeeQualificationSerializer(serializers.ModelSerializer):
    qualification_name = serializers.CharField(
        source="qualification.name", read_only=True
    )
    is_specialist = serializers.BooleanField(
        source="qualification.is_specialist", read_only=True
    )

    class Meta:
        model = EmployeeQualification
        fields = [
            "id",
            "employee",
            "qualification",
            "qualification_name",
            "is_specialist",
            "acquired_on",
            "expires_on",
        ]


class ContractSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    fte = serializers.SerializerMethodField()

    class Meta:
        model = Contract
        fields = [
            "id",
            "employee",
            "kind",
            "kind_display",
            "weekly_hours",
            "pay_grade",
            "valid_from",
            "valid_to",
            "notes",
            "fte",
        ]

    def get_fte(self, obj):
        return str(obj.fte)


class EmployeeSerializer(serializers.ModelSerializer):
    """
    Personaldaten.

    Vertragliche und persönliche Angaben blendet to_representation für
    Nicht-Personal aus - im Dienstplan braucht man den Namen, nicht das
    Geburtsdatum.
    """

    full_name = serializers.SerializerMethodField()
    is_specialist = serializers.BooleanField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    qualification_names = serializers.SerializerMethodField()
    work_time_model_name = serializers.SerializerMethodField()

    SENSITIVE_FIELDS = ("birth_date", "personnel_number", "phone", "notes", "email")

    class Meta:
        model = Employee
        fields = [
            "id",
            "provider",
            "user",
            "personnel_number",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "phone",
            "birth_date",
            "hired_on",
            "left_on",
            "work_time_model",
            "work_time_model_name",
            "qualification_names",
            "is_specialist",
            "is_active",
            "notes",
        ]

    def get_full_name(self, obj):
        return obj.get_full_name()

    def get_qualification_names(self, obj):
        return [item.name for item in obj.qualifications.all()]

    def get_work_time_model_name(self, obj):
        return obj.work_time_model.name if obj.work_time_model_id else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None)

        if user and not user.is_staff:
            own = instance.user_id == user.id
            if not own:
                for field in self.SENSITIVE_FIELDS:
                    data.pop(field, None)
        return data


class RoleSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source="get_role_display", read_only=True)
    employee_name = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = [
            "id",
            "employee",
            "employee_name",
            "role",
            "role_display",
            "provider",
            "facility",
            "department",
            "valid_from",
            "valid_to",
        ]

    def get_employee_name(self, obj):
        return obj.employee.get_full_name()


class PositionAssignmentSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()

    class Meta:
        model = PositionAssignment
        fields = [
            "id",
            "position",
            "employee",
            "employee_name",
            "fte",
            "valid_from",
            "valid_to",
        ]

    def get_employee_name(self, obj):
        return obj.employee.get_full_name()


class PositionSerializer(serializers.ModelSerializer):
    assignments = PositionAssignmentSerializer(many=True, read_only=True)
    assigned_fte = serializers.SerializerMethodField()
    state = serializers.CharField(read_only=True)
    department_name = serializers.SerializerMethodField()

    class Meta:
        model = Position
        fields = [
            "id",
            "department",
            "department_name",
            "title",
            "target_fte",
            "requires_specialist",
            "notes",
            "assignments",
            "assigned_fte",
            "state",
        ]

    def get_assigned_fte(self, obj):
        return str(obj.assigned_fte)

    def get_department_name(self, obj):
        return str(obj.department)


# ---------------------------------------------------------------- ViewSets


class ProviderViewSet(StaffWritableViewSet):
    serializer_class = ProviderSerializer

    def get_queryset(self):
        return tenant_providers(self.request.user)


class SiteViewSet(StaffWritableViewSet):
    serializer_class = SiteSerializer

    def get_queryset(self):
        return limit_to_tenant(
            Site.objects.select_related("provider"), self.request.user
        )


class FacilityViewSet(StaffWritableViewSet):
    serializer_class = FacilitySerializer

    def get_queryset(self):
        return limit_to_tenant(
            Facility.objects.select_related("site"),
            self.request.user,
            "site__provider_id",
        )


class DepartmentViewSet(StaffWritableViewSet):
    serializer_class = DepartmentSerializer

    def get_queryset(self):
        return limit_to_tenant(
            Department.objects.select_related("facility", "group").prefetch_related(
                "positions"
            ),
            self.request.user,
            "facility__site__provider_id",
        )


class QualificationViewSet(StaffWritableViewSet):
    serializer_class = QualificationSerializer
    queryset = Qualification.objects.all()


class WorkTimeModelViewSet(StaffWritableViewSet):
    serializer_class = WorkTimeModelSerializer

    def get_queryset(self):
        return limit_to_tenant(WorkTimeModel.objects.all(), self.request.user)


class EmployeeViewSet(StaffWritableViewSet):
    serializer_class = EmployeeSerializer

    def get_queryset(self):
        queryset = limit_to_tenant(
            Employee.objects.select_related("work_time_model").prefetch_related(
                "qualifications"
            ),
            self.request.user,
        )
        if self.request.query_params.get("aktiv") == "1":
            queryset = queryset.filter(left_on__isnull=True)
        return queryset


class ContractViewSet(StaffWritableViewSet):
    serializer_class = ContractSerializer

    def get_queryset(self):
        # Verträge sieht nur Personal, sonst ausschließlich den eigenen.
        queryset = Contract.objects.select_related("employee")
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(employee__user=self.request.user)


class EmployeeQualificationViewSet(StaffWritableViewSet):
    serializer_class = EmployeeQualificationSerializer
    queryset = EmployeeQualification.objects.select_related("qualification", "employee")


class RoleViewSet(StaffWritableViewSet):
    serializer_class = RoleSerializer
    queryset = Role.objects.select_related(
        "employee", "provider", "facility", "department"
    )


class PositionViewSet(StaffWritableViewSet):
    serializer_class = PositionSerializer

    def get_queryset(self):
        queryset = limit_to_tenant(
            Position.objects.select_related("department").prefetch_related(
                "assignments__employee"
            ),
            self.request.user,
            "department__facility__site__provider_id",
        )
        department = self.request.query_params.get("bereich")
        if department:
            queryset = queryset.filter(department_id=department)
        return queryset


class PositionAssignmentViewSet(StaffWritableViewSet):
    serializer_class = PositionAssignmentSerializer
    queryset = PositionAssignment.objects.select_related("employee", "position")


class StaffingPlanView(APIView):
    """
    Stellplan je Bereich: Soll, Ist und der Zustand jeder Stelle.

    Fasst zusammen, was der Roadmap-Punkt „freie, besetzte und überbesetzte
    Stellen" verlangt, ohne dass die Oberfläche selbst rechnen muss.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        departments = limit_to_tenant(
            Department.objects.select_related("facility__site").prefetch_related(
                "positions__assignments__employee"
            ),
            request.user,
            "facility__site__provider_id",
        )

        data = []
        for department in departments:
            positions = list(department.positions.all())
            target = sum((position.target_fte for position in positions), Decimal("0"))
            assigned = sum(
                (position.assigned_fte for position in positions), Decimal("0")
            )

            data.append(
                {
                    "department": department.id,
                    "department_name": department.name,
                    "facility_name": department.facility.name,
                    "group": department.group_id,
                    "target_fte": str(target),
                    "assigned_fte": str(assigned),
                    "vacant": sum(1 for p in positions if p.state == "vacant"),
                    "understaffed": sum(
                        1 for p in positions if p.state == "understaffed"
                    ),
                    "filled": sum(1 for p in positions if p.state == "filled"),
                    "overstaffed": sum(
                        1 for p in positions if p.state == "overstaffed"
                    ),
                    "positions": PositionSerializer(
                        positions, many=True, context={"request": request}
                    ).data,
                }
            )

        return Response(data)
