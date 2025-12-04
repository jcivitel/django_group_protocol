from django.urls import path
from .views import SetupStatusView, SetupWizardView, SetupRedirectView, InfoView

app_name = 'django_grp_core'

urlpatterns = [
    # Root setup/info endpoints
    path("", SetupRedirectView.as_view(), name="setup-redirect"),
    path("setup/status/", SetupStatusView.as_view(), name="setup-status"),
    path("setup/init/", SetupWizardView.as_view(), name="setup-init"),
    path("info/", InfoView.as_view(), name="info"),
]
