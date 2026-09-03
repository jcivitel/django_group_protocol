from django.urls import path, include
from rest_framework import routers
from rest_framework_nested import routers as nested_routers

from django_grp_care import api as care_api
from django_grp_duty import api as duty_api
from django_grp_mail import api as mail_api
from django_grp_org import api as org_api

from . import views
from .views import (
    ProtocolPresenceUpdateView,
    ItemValuesUpdateView,
    RotateImageView,
    MentionAutocompleteView,
    LoginView,
    LogoutView,
    UserProfileView,
    UserMeView,
    ResidentPictureView,
    ResidentPictureUploadView,
    GroupPDFTemplateView,
    ProtocolPresenceListView,
    ProtocolExportedFileView,
    AdminUserListView,
    AdminUserDetailView,
    AdminUserGroupView,
    AdminUserPermissionView,
)

router = routers.DefaultRouter()
router.register(r"protocol", views.ProtocolViewSet, "protocol")
router.register(r"group", views.GroupViewSet, "group")
router.register(r"resident", views.ResidentViewSet, "resident")
router.register(r"template", views.ProtocolTemplateViewSet, "protocol-template")

# ---- Organisation und Personal (Phasen 0 und 1)
router.register(r"provider", org_api.ProviderViewSet, "provider")
router.register(r"site", org_api.SiteViewSet, "site")
router.register(r"facility", org_api.FacilityViewSet, "facility")
router.register(r"department", org_api.DepartmentViewSet, "department")
router.register(r"qualification", org_api.QualificationViewSet, "qualification")
router.register(r"worktime-model", org_api.WorkTimeModelViewSet, "worktime-model")
router.register(r"employee", org_api.EmployeeViewSet, "employee")
router.register(r"contract", org_api.ContractViewSet, "contract")
router.register(
    r"employee-qualification",
    org_api.EmployeeQualificationViewSet,
    "employee-qualification",
)
router.register(r"role", org_api.RoleViewSet, "role")
router.register(r"position", org_api.PositionViewSet, "position")
router.register(
    r"position-assignment", org_api.PositionAssignmentViewSet, "position-assignment"
)

# ---- Dienst, Abwesenheit, Zeit (Phasen 2 bis 4)
router.register(r"shift-type", duty_api.ShiftTypeViewSet, "shift-type")
router.register(
    r"staffing-requirement",
    duty_api.StaffingRequirementViewSet,
    "staffing-requirement",
)
router.register(r"duty-plan", duty_api.DutyPlanViewSet, "duty-plan")
router.register(r"absence-type", duty_api.AbsenceTypeViewSet, "absence-type")
router.register(r"absence", duty_api.AbsenceViewSet, "absence")
router.register(r"time-entry", duty_api.TimeEntryViewSet, "time-entry")
router.register(r"time-account", duty_api.TimeAccountViewSet, "time-account")
router.register(
    r"shift-preference", duty_api.ShiftPreferenceViewSet, "shift-preference"
)
router.register(r"shift-swap", duty_api.ShiftSwapViewSet, "shift-swap")
router.register(r"audit", org_api.AuditEventViewSet, "audit")

# ---- Hilfeplanung und Fallführung (Phase 5)
router.register(r"case-file", care_api.CaseFileViewSet, "case-file")
router.register(r"help-plan", care_api.HelpPlanViewSet, "help-plan")
router.register(r"help-goal", care_api.HelpGoalViewSet, "help-goal")
router.register(r"help-measure", care_api.HelpMeasureViewSet, "help-measure")
router.register(
    r"case-participant", care_api.CaseParticipantViewSet, "case-participant"
)
router.register(r"case-meeting", care_api.CaseMeetingViewSet, "case-meeting")

# Nested router: alles, was direkt an einem Protokoll haengt
protocol_router = nested_routers.NestedSimpleRouter(
    router, r"protocol", lookup="protocol"
)
protocol_router.register(r"todo", views.ProtocolTodoViewSet, basename="protocol-todo")
protocol_router.register(
    r"attendance", views.ProtocolAttendanceViewSet, basename="protocol-attendance"
)
protocol_router.register(
    r"observation", views.ProtocolObservationViewSet, basename="protocol-observation"
)

# Kontakte haengen immer an einer Bewohnerakte.
resident_router = nested_routers.NestedSimpleRouter(
    router, r"resident", lookup="resident"
)
resident_router.register(
    r"contact", views.ResidentContactViewSet, basename="resident-contact"
)

# Dienste haengen immer an einem Dienstplan.
duty_router = nested_routers.NestedSimpleRouter(router, r"duty-plan", lookup="plan")
duty_router.register(r"shift", duty_api.ShiftViewSet, basename="duty-shift")

urlpatterns = [
    path("v1/auth/login/", LoginView.as_view(), name="auth-login"),
    path("v1/mail/settings/", mail_api.MailSettingsView.as_view(), name="mail-settings"),
    path("v1/mail/test/", mail_api.MailTestView.as_view(), name="mail-test"),
    path("v1/mail/outbox/", mail_api.MailOutboxView.as_view(), name="mail-outbox"),
    path(
        "v1/mail/outbox/<int:message_id>/retry/",
        mail_api.MailRetryView.as_view(),
        name="mail-retry",
    ),
    path("v1/auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("v1/user/profile/", UserProfileView.as_view(), name="user-profile"),
    path("v1/user/me/", UserMeView.as_view(), name="user-me"),
    path("v1/", include(router.urls)),
    path("v1/", include(protocol_router.urls)),
    path("v1/", include(duty_router.urls)),
    path("v1/", include(resident_router.urls)),
    # Aktionen bewusst unter eigenen Praefixen, damit sie nicht mit den
    # Detail-Routen der Router kollidieren (z. B. /time-entry/{id}/).
    path(
        "v1/staffing-plan/",
        org_api.StaffingPlanView.as_view(),
        name="staffing-plan",
    ),
    path(
        "v1/duty-plan/<int:plan_id>/rules/",
        duty_api.DutyPlanRulesView.as_view(),
        name="duty-plan-rules",
    ),
    path(
        "v1/duty-plan/<int:plan_id>/generate/",
        duty_api.DutyPlanGenerateView.as_view(),
        name="duty-plan-generate",
    ),
    path(
        "v1/substitutes/<int:shift_id>/",
        duty_api.SubstituteSearchView.as_view(),
        name="substitute-search",
    ),
    path(
        "v1/vacation/<int:employee_id>/",
        duty_api.VacationBalanceView.as_view(),
        name="vacation-balance",
    ),
    path(
        "v1/time-approval/",
        duty_api.TimeEntryApprovalView.as_view(),
        name="time-approval",
    ),
    path("v1/time-close/", duty_api.CloseMonthView.as_view(), name="time-close"),
    path("v1/my/duty/", duty_api.MyDutyView.as_view(), name="my-duty"),
    path("v1/payroll/", duty_api.PayrollExportView.as_view(), name="payroll"),
    # Ohne Anmeldung, damit Monitoring-Systeme sie abfragen koennen.
    path("health/", org_api.HealthView.as_view(), name="health"),
    path(
        "v1/help-plan/<int:plan_id>/continue/",
        care_api.HelpPlanContinueView.as_view(),
        name="help-plan-continue",
    ),
    path(
        "v1/case-timeline/<int:case_id>/",
        care_api.CaseTimelineView.as_view(),
        name="case-timeline",
    ),
    path(
        "v1/help-plan-reviews/",
        care_api.ReviewDueView.as_view(),
        name="help-plan-reviews",
    ),
    path(
        "v1/resident/<int:resident_id>/picture/",
        ResidentPictureView.as_view(),
        name="resident-picture",
    ),
    path(
        "v1/resident/<int:resident_id>/upload-picture/",
        ResidentPictureUploadView.as_view(),
        name="resident-upload-picture",
    ),
    path(
        "v1/employee/<int:employee_id>/picture/",
        org_api.EmployeePictureView.as_view(),
        name="employee-picture",
    ),
    path(
        "v1/group/<int:group_id>/pdf_template/",
        GroupPDFTemplateView.as_view(),
        name="group-pdf-template",
    ),
    path(
        "v1/protocol/<int:protocol_id>/presence/",
        ProtocolPresenceListView.as_view(),
        name="protocol-presence-list",
    ),
    path(
        "v1/protocol/<int:protocol_id>/exported_file/",
        ProtocolExportedFileView.as_view(),
        name="protocol-exported-file",
    ),
    path("v1/presence/", ProtocolPresenceUpdateView.as_view(), name="update-presence"),
    path("v1/item/", ItemValuesUpdateView.as_view(), name="update-item"),
    path("v1/rotate_image/", RotateImageView.as_view(), name="rotate_image"),
    path(
        "v1/mentions/", MentionAutocompleteView.as_view(), name="mention-autocomplete"
    ),
    # Admin endpoints
    path("v1/admin/users/", AdminUserListView.as_view(), name="admin-user-list"),
    path(
        "v1/admin/users/<int:user_id>/",
        AdminUserDetailView.as_view(),
        name="admin-user-detail",
    ),
    path(
        "v1/admin/users/<int:user_id>/groups/",
        AdminUserGroupView.as_view(),
        name="admin-user-groups",
    ),
    path(
        "v1/admin/users/<int:user_id>/groups/<int:group_id>/",
        AdminUserGroupView.as_view(),
        name="admin-user-group-detail",
    ),
    path(
        "v1/admin/users/<int:user_id>/permissions/",
        AdminUserPermissionView.as_view(),
        name="admin-user-permissions",
    ),
    path(
        "v1/admin/users/<int:user_id>/permissions/<int:permission_id>/",
        AdminUserPermissionView.as_view(),
        name="admin-user-permission-detail",
    ),
]
