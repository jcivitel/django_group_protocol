from django.urls import path

from django_grp_exporter import views

urlpatterns = [
    path("protocol/<int:protocol_id>/", views.view_protocol, name="export-protocol"),
]
