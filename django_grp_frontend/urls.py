from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("resident/", views.resident, name="resident"),
    path("resident/<int:id>/", views.resident, name="resident"),
    path("add_resident/", views.add_resident, name="add_resident"),
    path("protocol/", views.protocol, name="protocol"),
    path("protocol/<int:id>/", views.protocol, name="protocol"),
    path("add_protocol/", views.add_protocol, name="add_protocol"),
    path("profile/", views.profile, name="profile"),
]