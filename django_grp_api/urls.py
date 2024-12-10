from django.urls import path, include
from rest_framework import routers
from . import views

router = routers.DefaultRouter()
router.register(r'protocol', views.ProtocolViewSet, 'protocol')

urlpatterns = [
    path('v1/', include(router.urls)),
]