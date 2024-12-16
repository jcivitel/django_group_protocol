from django.urls import path, include
from rest_framework import routers

from . import views
from .views import ProtocolPresenceUpdateView

router = routers.DefaultRouter()
router.register(r"protocol", views.ProtocolViewSet, "protocol")
router.register(r"group", views.GroupViewSet, "group")
router.register(r"resident", views.ResidentViewSet, "resident")

urlpatterns = [
    path("v1/", include(router.urls)),
    path("v1/presence/", ProtocolPresenceUpdateView.as_view(), name="update-presence"),
]
