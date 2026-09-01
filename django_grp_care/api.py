"""
API für Hilfeplanung und Fallführung (Phase 5).

Fallakten enthalten die schutzbedürftigsten Daten des Systems. Zugriff hat
deshalb nur Personal oder wer Mitglied der Gruppe ist, in der die Person
lebt - dieselbe Regel wie bei Protokollen und Bewohnern.
"""

from django.db.models import Q
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django_grp_backend.models import ProtocolObservation

from .models import (
    CaseFile,
    CaseMeeting,
    CaseParticipant,
    HelpGoal,
    HelpMeasure,
    HelpPlan,
)


def accessible_case_files(user):
    """Fallakten, die diese Person sehen darf."""
    queryset = CaseFile.objects.select_related("resident", "responsible")
    if user.is_staff:
        return queryset
    return queryset.filter(resident__group__group_members=user).distinct()


class CaseScopedMixin:
    """Prüft bei jedem Zugriff, ob die Fallakte sichtbar ist."""

    permission_classes = [IsAuthenticated]

    def visible_case_ids(self):
        return accessible_case_files(self.request.user).values_list("id", flat=True)

    def guard_case(self, case_file_id):
        if case_file_id not in set(self.visible_case_ids()):
            raise PermissionDenied("Kein Zugriff auf diese Fallakte.")


class HelpMeasureSerializer(serializers.ModelSerializer):
    class Meta:
        model = HelpMeasure
        fields = [
            "id",
            "goal",
            "title",
            "description",
            "responsible",
            "frequency",
            "is_done",
            "position",
        ]


class HelpGoalSerializer(serializers.ModelSerializer):
    measures = HelpMeasureSerializer(many=True, read_only=True)
    category_display = serializers.CharField(
        source="get_category_display", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = HelpGoal
        fields = [
            "id",
            "help_plan",
            "title",
            "description",
            "category",
            "category_display",
            "status",
            "status_display",
            "target_date",
            "position",
            "measures",
        ]


class HelpPlanSerializer(serializers.ModelSerializer):
    goals = HelpGoalSerializer(many=True, read_only=True)
    legal_basis_display = serializers.CharField(
        source="get_legal_basis_display", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    goal_progress = serializers.IntegerField(read_only=True)
    resident_name = serializers.SerializerMethodField()

    class Meta:
        model = HelpPlan
        fields = [
            "id",
            "case_file",
            "resident_name",
            "version",
            "previous",
            "legal_basis",
            "legal_basis_display",
            "help_form",
            "valid_from",
            "valid_to",
            "status",
            "status_display",
            "situation",
            "review_date",
            "goal_progress",
            "goals",
        ]

    def get_resident_name(self, obj):
        return obj.case_file.resident.get_full_name()


class CaseParticipantSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = CaseParticipant
        fields = [
            "id",
            "case_file",
            "kind",
            "kind_display",
            "name",
            "organisation",
            "contact",
            "note",
        ]


class CaseMeetingSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = CaseMeeting
        fields = [
            "id",
            "case_file",
            "help_plan",
            "kind",
            "kind_display",
            "date",
            "location",
            "participants",
            "minutes",
            "decisions",
            "next_meeting",
        ]


class CaseFileSerializer(serializers.ModelSerializer):
    resident_name = serializers.SerializerMethodField()
    responsible_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    current_plan = serializers.SerializerMethodField()
    plan_count = serializers.SerializerMethodField()

    class Meta:
        model = CaseFile
        fields = [
            "id",
            "provider",
            "resident",
            "resident_name",
            "case_number",
            "youth_office",
            "case_manager",
            "responsible",
            "responsible_name",
            "opened_on",
            "closed_on",
            "status",
            "status_display",
            "note",
            "current_plan",
            "plan_count",
        ]

    def get_resident_name(self, obj):
        return obj.resident.get_full_name()

    def get_responsible_name(self, obj):
        return obj.responsible.get_full_name() if obj.responsible_id else None

    def get_current_plan(self, obj):
        plan = obj.current_plan
        return (
            {
                "id": plan.id,
                "version": plan.version,
                "legal_basis": plan.get_legal_basis_display(),
                "valid_from": plan.valid_from,
                "review_date": plan.review_date,
                "goal_progress": plan.goal_progress,
            }
            if plan
            else None
        )

    def get_plan_count(self, obj):
        return obj.help_plans.count()


class CaseFileViewSet(CaseScopedMixin, viewsets.ModelViewSet):
    serializer_class = CaseFileSerializer

    def get_queryset(self):
        queryset = accessible_case_files(self.request.user).prefetch_related(
            "help_plans__goals"
        )
        resident = self.request.query_params.get("bewohner")
        if resident:
            queryset = queryset.filter(resident_id=resident)
        return queryset

    def perform_create(self, serializer):
        if not self.request.user.is_staff:
            raise PermissionDenied("Nur Mitarbeitende dürfen Fallakten anlegen.")
        serializer.save()

    def perform_update(self, serializer):
        self.guard_case(serializer.instance.id)
        serializer.save()

    def perform_destroy(self, instance):
        if not self.request.user.is_staff:
            raise PermissionDenied("Nur Mitarbeitende dürfen Fallakten löschen.")
        instance.delete()


class HelpPlanViewSet(CaseScopedMixin, viewsets.ModelViewSet):
    serializer_class = HelpPlanSerializer

    def get_queryset(self):
        queryset = (
            HelpPlan.objects.filter(case_file_id__in=self.visible_case_ids())
            .select_related("case_file__resident")
            .prefetch_related("goals__measures")
        )
        case_file = self.request.query_params.get("fallakte")
        if case_file:
            queryset = queryset.filter(case_file_id=case_file)
        return queryset

    def perform_create(self, serializer):
        case_file = serializer.validated_data["case_file"]
        self.guard_case(case_file.id)
        serializer.save()

    def perform_update(self, serializer):
        self.guard_case(serializer.instance.case_file_id)
        serializer.save()

    def perform_destroy(self, instance):
        self.guard_case(instance.case_file_id)
        instance.delete()


class HelpPlanContinueView(APIView):
    """
    Hilfeplan fortschreiben.

    Legt eine neue Fassung mit denselben Zielen an und setzt die alte auf
    „fortgeschrieben". So bleibt nachvollziehbar, was wann galt, statt dass
    ein Datensatz überschrieben wird.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, plan_id: int):
        plan = (
            HelpPlan.objects.filter(
                id=plan_id, case_file_id__in=accessible_case_files(request.user)
            )
            .prefetch_related("goals__measures")
            .first()
        )
        if plan is None:
            return Response({"error": "Hilfeplan nicht gefunden."}, status=404)
        if not request.user.is_staff:
            raise PermissionDenied("Nur Mitarbeitende dürfen fortschreiben.")

        successor = HelpPlan.objects.create(
            case_file=plan.case_file,
            version=plan.version + 1,
            previous=plan,
            legal_basis=plan.legal_basis,
            help_form=plan.help_form,
            valid_from=request.data.get("valid_from")
            or plan.valid_to
            or plan.valid_from,
            status="draft",
            situation=plan.situation,
        )

        # Offene Ziele wandern mit, erreichte bleiben in der alten Fassung.
        for goal in plan.goals.exclude(status="achieved"):
            copy = HelpGoal.objects.create(
                help_plan=successor,
                title=goal.title,
                description=goal.description,
                category=goal.category,
                status=goal.status,
                target_date=goal.target_date,
                position=goal.position,
            )
            for measure in goal.measures.filter(is_done=False):
                HelpMeasure.objects.create(
                    goal=copy,
                    title=measure.title,
                    description=measure.description,
                    responsible=measure.responsible,
                    frequency=measure.frequency,
                    position=measure.position,
                )

        plan.status = "superseded"
        plan.save(update_fields=["status"])

        return Response(
            HelpPlanSerializer(successor, context={"request": request}).data,
            status=201,
        )


class HelpGoalViewSet(CaseScopedMixin, viewsets.ModelViewSet):
    serializer_class = HelpGoalSerializer

    def get_queryset(self):
        return HelpGoal.objects.filter(
            help_plan__case_file_id__in=self.visible_case_ids()
        ).prefetch_related("measures")

    def perform_create(self, serializer):
        self.guard_case(serializer.validated_data["help_plan"].case_file_id)
        serializer.save()

    def perform_update(self, serializer):
        self.guard_case(serializer.instance.help_plan.case_file_id)
        serializer.save()

    def perform_destroy(self, instance):
        self.guard_case(instance.help_plan.case_file_id)
        instance.delete()


class HelpMeasureViewSet(CaseScopedMixin, viewsets.ModelViewSet):
    serializer_class = HelpMeasureSerializer

    def get_queryset(self):
        return HelpMeasure.objects.filter(
            goal__help_plan__case_file_id__in=self.visible_case_ids()
        )

    def perform_create(self, serializer):
        self.guard_case(serializer.validated_data["goal"].help_plan.case_file_id)
        serializer.save()

    def perform_update(self, serializer):
        self.guard_case(serializer.instance.goal.help_plan.case_file_id)
        serializer.save()

    def perform_destroy(self, instance):
        self.guard_case(instance.goal.help_plan.case_file_id)
        instance.delete()


class CaseParticipantViewSet(CaseScopedMixin, viewsets.ModelViewSet):
    serializer_class = CaseParticipantSerializer

    def get_queryset(self):
        return CaseParticipant.objects.filter(case_file_id__in=self.visible_case_ids())

    def perform_create(self, serializer):
        self.guard_case(serializer.validated_data["case_file"].id)
        serializer.save()

    def perform_update(self, serializer):
        self.guard_case(serializer.instance.case_file_id)
        serializer.save()

    def perform_destroy(self, instance):
        self.guard_case(instance.case_file_id)
        instance.delete()


class CaseMeetingViewSet(CaseScopedMixin, viewsets.ModelViewSet):
    serializer_class = CaseMeetingSerializer

    def get_queryset(self):
        return CaseMeeting.objects.filter(case_file_id__in=self.visible_case_ids())

    def perform_create(self, serializer):
        self.guard_case(serializer.validated_data["case_file"].id)
        serializer.save()

    def perform_update(self, serializer):
        self.guard_case(serializer.instance.case_file_id)
        serializer.save()

    def perform_destroy(self, instance):
        self.guard_case(instance.case_file_id)
        instance.delete()


class CaseTimelineView(APIView):
    """
    Zeitleiste einer Fallakte.

    Führt zusammen, was fachlich zusammengehört, aber getrennt erfasst wird:
    Hilfepläne, Fallgespräche und die Verlaufseinträge aus den
    Gruppenprotokollen zu dieser Person.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, case_id: int):
        case_file = accessible_case_files(request.user).filter(id=case_id).first()
        if case_file is None:
            return Response({"error": "Fallakte nicht gefunden."}, status=404)

        events = []

        for plan in case_file.help_plans.all():
            events.append(
                {
                    "kind": "help_plan",
                    "date": str(plan.valid_from),
                    "title": f"Hilfeplan Fassung {plan.version}",
                    "detail": plan.get_legal_basis_display(),
                    "reference": plan.id,
                }
            )

        for meeting in case_file.meetings.all():
            events.append(
                {
                    "kind": "meeting",
                    "date": str(meeting.date),
                    "title": meeting.get_kind_display(),
                    "detail": meeting.decisions or meeting.minutes,
                    "reference": meeting.id,
                }
            )

        observations = (
            ProtocolObservation.objects.filter(resident=case_file.resident_id)
            .select_related("protocol")
            .order_by("-protocol__protocol_date")[:50]
        )
        for observation in observations:
            events.append(
                {
                    "kind": "observation",
                    "date": str(observation.protocol.protocol_date),
                    "title": observation.get_category_display(),
                    "detail": observation.text,
                    "reference": observation.protocol_id,
                }
            )

        events.sort(key=lambda item: item["date"], reverse=True)
        return Response({"case_file": case_file.id, "events": events})


class ReviewDueView(APIView):
    """Hilfepläne, deren Fortschreibung ansteht - Termine für den Kalender."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        plans = (
            HelpPlan.objects.filter(
                case_file_id__in=accessible_case_files(request.user),
                status="active",
                review_date__isnull=False,
            )
            .select_related("case_file__resident")
            .order_by("review_date")
        )

        return Response(
            [
                {
                    "plan": plan.id,
                    "case_file": plan.case_file_id,
                    "resident": plan.case_file.resident_id,
                    "resident_name": plan.case_file.resident.get_full_name(),
                    "review_date": str(plan.review_date),
                    "legal_basis": plan.get_legal_basis_display(),
                }
                for plan in plans
            ]
        )
