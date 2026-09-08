"""
Einrichtung und Betriebszustand.

Der alte Weg (SetupRedirectView auf "/" und InfoView auf "/info/") ist
entfallen: er rendert HTML-Vorlagen aus templates/ und stammt aus der Zeit
vor dem Assistenten im Frontend. Zwei Einrichtungswege nebeneinander sind
einer zu viel - und der alte legte Superuser an, solange noch keiner
existierte, ohne dass jemand darauf gefasst war (S12).
"""

from django.urls import path

from .organisation_setup import OrganisationSetupView
from .views import SetupStatusView, SetupWizardView

app_name = "django_grp_core"

urlpatterns = [
    path("setup/status/", SetupStatusView.as_view(), name="setup-status"),
    path("setup/init/", SetupWizardView.as_view(), name="setup-init"),
    path(
        "setup/organisation/",
        OrganisationSetupView.as_view(),
        name="setup-organisation",
    ),
]
