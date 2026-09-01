"""
Anmeldung über OpenID Connect (Roadmap Phase 0).

Ablauf:

1. Der Browser ruft /api/v1/auth/oidc/start/ auf und wird zum Anbieter
   geschickt.
2. Der Anbieter schickt ihn mit einem Code zurück auf
   /api/v1/auth/oidc/callback/.
3. Django tauscht den Code gegen die Nutzerdaten, legt das Konto an oder
   aktualisiert es und erzeugt ein DRF-Token.
4. Statt das Token in die URL zu schreiben, wird ein kurzlebiger
   Austauschcode vergeben. Das Frontend holt sich damit serverseitig das
   Token über /api/v1/auth/oidc/exchange/ und legt es in sein httpOnly-Cookie.

So taucht das Token an keiner Stelle im Browserverlauf auf.
"""

import logging
import secrets

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import redirect
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import OIDCClient

logger = logging.getLogger("django_grp.auth")

# Der Austauschcode lebt nur so lange, wie eine Weiterleitung braucht.
EXCHANGE_TTL_SECONDS = 120
STATE_TTL_SECONDS = 600


def _frontend_url() -> str:
    return getattr(settings, "FRONTEND_URL", "http://localhost:3000").rstrip("/")


class OIDCStartView(APIView):
    """Leitet zum Anmeldedialog des Anbieters weiter."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        client = OIDCClient()
        if not client.configured:
            return Response(
                {"error": "Single Sign-on ist nicht konfiguriert."}, status=501
            )

        state = secrets.token_urlsafe(24)
        cache.set(f"oidc-state:{state}", True, STATE_TTL_SECONDS)

        try:
            return redirect(client.authorization_url(state))
        except Exception:  # noqa: BLE001
            logger.exception("OIDC-Anbieter nicht erreichbar")
            return Response(
                {"error": "Der Anmeldedienst ist nicht erreichbar."}, status=502
            )


class OIDCCallbackView(APIView):
    """Nimmt den Code des Anbieters entgegen und vergibt einen Austauschcode."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        client = OIDCClient()
        if not client.configured:
            return Response(
                {"error": "Single Sign-on ist nicht konfiguriert."}, status=501
            )

        code = request.query_params.get("code")
        state = request.query_params.get("state")

        # Ohne gültigen State könnte die Anfrage untergeschoben sein.
        if not code or not state or not cache.get(f"oidc-state:{state}"):
            return redirect(f"{_frontend_url()}/login?fehler=sso")
        cache.delete(f"oidc-state:{state}")

        try:
            claims = client.exchange(code)
            user = client.user_from_claims(claims)
        except Exception:  # noqa: BLE001
            logger.exception("OIDC-Anmeldung fehlgeschlagen")
            return redirect(f"{_frontend_url()}/login?fehler=sso")

        token, _ = Token.objects.get_or_create(user=user)
        exchange_code = secrets.token_urlsafe(32)
        cache.set(f"oidc-exchange:{exchange_code}", token.key, EXCHANGE_TTL_SECONDS)

        return redirect(f"{_frontend_url()}/api/auth/sso?code={exchange_code}")


class OIDCExchangeView(APIView):
    """
    Tauscht den kurzlebigen Code gegen das Token.

    Wird ausschließlich vom Server des Frontends aufgerufen, nie vom Browser.
    Der Code gilt genau einmal.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        code = request.data.get("code")
        if not code:
            return Response({"success": False, "error": "Code fehlt."}, status=400)

        key = f"oidc-exchange:{code}"
        token = cache.get(key)
        if not token:
            return Response(
                {"success": False, "error": "Code ist abgelaufen oder unbekannt."},
                status=400,
            )
        cache.delete(key)

        instance = Token.objects.filter(key=token).select_related("user").first()
        if instance is None:
            return Response(
                {"success": False, "error": "Token nicht mehr gültig."}, status=400
            )

        user = instance.user
        return Response(
            {
                "success": True,
                "data": {
                    "token": instance.key,
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "email": user.email,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                    },
                },
            }
        )


class AuthMethodsView(APIView):
    """
    Welche Anmeldewege stehen zur Verfügung?

    Das Frontend blendet den SSO-Knopf nur ein, wenn er auch funktioniert.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        client = OIDCClient()
        return Response(
            {
                "password": True,
                "ldap": bool(getattr(settings, "LDAP_SERVER", "")),
                "oidc": client.configured,
                "oidc_start": "/api/v1/auth/oidc/start/" if client.configured else None,
                "oidc_label": getattr(settings, "OIDC_LABEL", "Single Sign-on"),
            }
        )
