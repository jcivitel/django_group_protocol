from django.urls import path, include
from rest_framework import routers

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

urlpatterns = [
    path("v1/auth/login/", LoginView.as_view(), name="auth-login"),
    path("v1/auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("v1/user/profile/", UserProfileView.as_view(), name="user-profile"),
    path("v1/user/me/", UserMeView.as_view(), name="user-me"),
    path("v1/", include(router.urls)),
    path("v1/resident/<int:resident_id>/picture/", ResidentPictureView.as_view(), name="resident-picture"),
    path("v1/group/<int:group_id>/pdf_template/", GroupPDFTemplateView.as_view(), name="group-pdf-template"),
    path("v1/protocol/<int:protocol_id>/presence/", ProtocolPresenceListView.as_view(), name="protocol-presence-list"),
    path("v1/protocol/<int:protocol_id>/exported_file/", ProtocolExportedFileView.as_view(), name="protocol-exported-file"),
    path("v1/presence/", ProtocolPresenceUpdateView.as_view(), name="update-presence"),
    path("v1/item/", ItemValuesUpdateView.as_view(), name="update-item"),
    path("v1/rotate_image/", RotateImageView.as_view(), name="rotate_image"),
    path("v1/mentions/", MentionAutocompleteView.as_view(), name="mention-autocomplete"),
    # Admin endpoints
    path("v1/admin/users/", AdminUserListView.as_view(), name="admin-user-list"),
    path("v1/admin/users/<int:user_id>/", AdminUserDetailView.as_view(), name="admin-user-detail"),
    path("v1/admin/users/<int:user_id>/groups/", AdminUserGroupView.as_view(), name="admin-user-groups"),
    path("v1/admin/users/<int:user_id>/groups/<int:group_id>/", AdminUserGroupView.as_view(), name="admin-user-group-detail"),
    path("v1/admin/users/<int:user_id>/permissions/", AdminUserPermissionView.as_view(), name="admin-user-permissions"),
    path("v1/admin/users/<int:user_id>/permissions/<int:permission_id>/", AdminUserPermissionView.as_view(), name="admin-user-permission-detail"),
]
