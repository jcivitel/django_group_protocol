from django.urls import path, include
from rest_framework import routers
from . import views

router = routers.DefaultRouter()
router.register(r"protocol", views.ProtocolViewSet, "protocol")
router.register(r"group", views.GroupViewSet, "group")
router.register(r"resident", views.ResidentViewSet, "resident")

urlpatterns = [
    path("v1/", include(router.urls)),
]
