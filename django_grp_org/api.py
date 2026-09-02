"""
API für Organisationsstruktur und Personalstammdaten (Phasen 0 und 1).

Lesen darf jede angemeldete Person, schreiben nur Personal (is_staff).
Personaldaten sind sensibel: wer kein Personal ist, sieht von anderen nur
Name und Qualifikation, nicht Vertrag oder Geburtsdatum.
"""

from decimal import Decimal

from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django_grp_backend.access import WriteNeedsRole, is_admin
from .audit import AuditEvent
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

    permission_classes = [IsAuthenticated, WriteNeedsRole]

    def _require_staff(self):
        if not is_admin(self.request.user):
            raise PermissionDenied("Nur die Verwaltung darf Stammdaten ändern.")

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

    # Der Zugang gehört zur Person, nicht in eine zweite Liste.
    access_level_display = serializers.CharField(
        source="get_access_level_display", read_only=True
    )
    username = serializers.SerializerMethodField()
    account_active = serializers.SerializerMethodField()
    group_ids = serializers.SerializerMethodField()

    # Nur schreibend: das Passwort verlaesst den Server nie wieder.
    password = serializers.CharField(
        write_only=True, required=False, allow_blank=True, min_length=8
    )
    set_username = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    set_account_active = serializers.BooleanField(write_only=True, required=False)
    set_group_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )

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
            "access_level",
            "access_level_display",
            "username",
            "account_active",
            "group_ids",
            "password",
            "set_username",
            "set_account_active",
            "set_group_ids",
        ]

    def get_full_name(self, obj):
        return obj.get_full_name()

    def get_qualification_names(self, obj):
        return [item.name for item in obj.qualifications.all()]

    def get_work_time_model_name(self, obj):
        return obj.work_time_model.name if obj.work_time_model_id else None

    def get_username(self, obj):
        return obj.user.username if obj.user_id else None

    def get_account_active(self, obj):
        """None heisst: diese Person hat (noch) keinen Zugang."""
        return obj.user.is_active if obj.user_id else None

    def get_group_ids(self, obj):
        """In welchen Wohngruppen die Person mitarbeitet."""
        if not obj.user_id:
            return []
        return list(obj.user.group_set.values_list("id", flat=True))

    # ------------------------------------------------------------ Zugang
    #
    # Person und Konto sind ein Datensatz. Deshalb legt derselbe Aufruf,
    # der die Person anlegt, auch ihren Zugang an - vorher musste man
    # beides getrennt tun und von Hand zusammenhalten.

    def _apply_account(self, employee, data):
        from django.contrib.auth.models import User

        from django_grp_backend.models import Group

        username = (data.pop("set_username", None) or "").strip()
        password = data.pop("password", None)
        active = data.pop("set_account_active", None)
        group_ids = data.pop("set_group_ids", None)

        user = employee.user

        if username and user is None:
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": employee.first_name,
                    "last_name": employee.last_name,
                    "email": employee.email,
                },
            )
            employee.user = user
            employee.save(update_fields=["user"])
        elif username and user.username != username:
            user.username = username
            user.save(update_fields=["username"])

        if user is None:
            return

        changed = []
        if password:
            user.set_password(password)
            changed.append("password")
        if active is not None:
            user.is_active = active
            changed.append("is_active")
        if changed:
            user.save(update_fields=changed)

        if group_ids is not None:
            user.group_set.set(Group.objects.filter(id__in=group_ids))

    def create(self, validated_data):
        account = {
            key: validated_data.pop(key)
            for key in ("password", "set_username", "set_account_active", "set_group_ids")
            if key in validated_data
        }
        employee = super().create(validated_data)
        self._apply_account(employee, account)
        # Das Signal an Employee zieht is_staff nach; nach dem Anlegen des
        # Kontos muss es deshalb noch einmal laufen.
        employee.save(update_fields=["access_level"])
        return employee

    def update(self, instance, validated_data):
        account = {
            key: validated_data.pop(key)
            for key in ("password", "set_username", "set_account_active", "set_group_ids")
            if key in validated_data
        }
        employee = super().update(instance, validated_data)
        self._apply_account(employee, account)
        employee.save(update_fields=["access_level"])
        return employee

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

    permission_classes = [IsAuthenticated, WriteNeedsRole]

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


# ---------------------------------------------------------------- Phase 1/9


class AuditEventSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "model",
            "object_id",
            "label",
            "action",
            "action_display",
            "changes",
            "username",
            "created_at",
        ]


class AuditEventViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Änderungsprotokoll sensibler Stammdaten.

    Nur lesbar und nur für Personal: ein Protokoll, das sich ändern lässt,
    ist keins.
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    serializer_class = AuditEventSerializer

    def get_queryset(self):
        if not self.request.user.is_staff:
            return AuditEvent.objects.none()

        queryset = AuditEvent.objects.all()
        model = self.request.query_params.get("art")
        if model:
            queryset = queryset.filter(model=model)
        return queryset[:500]


class HealthView(APIView):
    """
    Betriebszustand (Roadmap Phase 9).

    Ohne Anmeldung erreichbar, damit Monitoring-Systeme sie abfragen können -
    und bewusst ohne Fachdaten: nur, ob Datenbank und Anwendung antworten.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        from django.db import connection

        database = "ok"
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception as error:  # noqa: BLE001
            database = f"fehler: {type(error).__name__}"

        pending = []
        try:
            from django.db.migrations.executor import MigrationExecutor

            executor = MigrationExecutor(connection)
            pending = [
                f"{migration.app_label}.{migration.name}"
                for migration, _ in executor.migration_plan(
                    executor.loader.graph.leaf_nodes()
                )
            ]
        except Exception:  # noqa: BLE001
            pending = ["unbekannt"]

        healthy = database == "ok" and not pending
        return Response(
            {
                "status": "ok" if healthy else "degraded",
                "database": database,
                "pending_migrations": pending,
            },
            status=200 if healthy else 503,
        )
