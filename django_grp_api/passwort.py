"""
Passwort vergessen.

Bis hierhin gab es keinen Weg zurück: wer sein Passwort vergaß, brauchte
jemanden mit Zugang zur Verwaltung — und wenn das die einzige Person mit
Zugang war, eine Kommandozeile. Für einen Realbetrieb ist das keine Option
(Analyse P0 8).

Zwei Endpunkte:

    POST /api/v1/auth/passwort-vergessen/   {email}
    POST /api/v1/auth/passwort-neu/         {uid, token, password}

Drei Dinge, auf die es dabei ankommt:

**Keine Auskunft darüber, welche Adressen es gibt.** Der erste Endpunkt
antwortet immer gleich — ob die Adresse zu einem Konto gehört oder nicht.
Sonst wird aus "Passwort vergessen" ein Verzeichnis der Beschäftigten.

**Der Link läuft ab und gilt einmal.** Djangos `default_token_generator`
bindet den Token an den bisherigen Passwort-Hash und den Zeitpunkt der
letzten Anmeldung; nach dem Setzen des neuen Passworts ist er wertlos. Die
Frist steht in PASSWORD_RESET_TIMEOUT.

**Das alte API-Token stirbt mit.** Wer ein Passwort zurücksetzt, tut das oft,
weil etwas nicht stimmt. Eine Sitzung, die danach weiterläuft, wäre genau
das Gegenteil dessen, was die Person erreichen wollte.
"""

import logging

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.conf import settings
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

logger = logging.getLogger("django_grp.auth")

# Dieselbe Antwort in jedem Fall - siehe Modulkopf.
STILLE_ANTWORT = {
    "success": True,
    "message": (
        "Wenn zu dieser Adresse ein Konto gehört, ist eine E-Mail mit einem "
        "Link unterwegs. Der Link gilt eine Stunde."
    ),
}


def _link(uid: str, token: str) -> str:
    basis = (settings.PUBLIC_WEB_URL or "").rstrip("/")
    return f"{basis}/passwort-neu?uid={uid}&token={token}"


def _text(user: User, link: str) -> str:
    anrede = user.get_full_name().strip() or user.get_username()
    return (
        f"Hallo {anrede},\n\n"
        "für dein Konto im Gruppenprotokoll wurde ein neues Passwort "
        "angefordert.\n\n"
        f"Hier setzt du es: {link}\n\n"
        "Der Link gilt eine Stunde und lässt sich nur einmal verwenden.\n\n"
        "Warst du das nicht, brauchst du nichts zu tun — dein bisheriges "
        "Passwort bleibt gültig.\n"
    )


class PasswortVergessenView(APIView):
    """Stößt das Zurücksetzen an. Antwortet immer gleich."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "passwort"

    def post(self, request):
        adresse = (request.data.get("email") or "").strip()
        if not adresse:
            return Response(
                {"error": "Bitte eine E-Mail-Adresse angeben."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # iexact und nicht exact: Groß- und Kleinschreibung entscheidet bei
        # E-Mail-Adressen nichts, und niemand tippt sie zweimal gleich.
        konten = list(User.objects.filter(email__iexact=adresse, is_active=True))

        if len(konten) == 1:
            self._verschicken(konten[0])
        elif len(konten) > 1:
            # Kann seit der Eindeutigkeitsprüfung nicht mehr entstehen, in
            # Altbeständen aber vorhanden sein. Kein Link, dafür ein Eintrag
            # im Log - hier muss jemand aufräumen.
            logger.warning(
                "Passwort zurücksetzen: %s gehört zu mehreren Konten", adresse
            )

        return Response(STILLE_ANTWORT, status=status.HTTP_200_OK)

    @staticmethod
    def _verschicken(user: User) -> None:
        from django_grp_mail.service import einstellen

        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        try:
            einstellen(
                to=user.email,
                subject="Neues Passwort für das Gruppenprotokoll",
                body=_text(user, _link(uid, token)),
                kind="password_reset",
            )
        except Exception:  # noqa: BLE001 - der Mailweg darf nichts kippen
            logger.exception("Mail zum Zurücksetzen konnte nicht eingestellt werden")


class PasswortNeuView(APIView):
    """Setzt das Passwort, wenn der Link noch gilt."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "passwort"

    def post(self, request):
        uid = request.data.get("uid") or ""
        token = request.data.get("token") or ""
        passwort = request.data.get("password") or ""

        if not uid or not token or not passwort:
            return Response(
                {"error": "Link und neues Passwort werden gebraucht."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = self._konto(uid)
        if user is None or not default_token_generator.check_token(user, token):
            return Response(
                {
                    "error": (
                        "Dieser Link gilt nicht mehr. Bitte fordere einen "
                        "neuen an."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_password(passwort, user)
        except DjangoValidationError as fehler:
            return Response(
                {"error": " ".join(fehler.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(passwort)
        user.save(update_fields=["password"])

        # Bestehende Sitzung beenden: wer zurücksetzt, will meist genau das.
        from rest_framework.authtoken.models import Token

        Token.objects.filter(user=user).delete()

        logger.info("Passwort zurückgesetzt für %s", user.get_username())
        return Response(
            {
                "success": True,
                "message": "Das Passwort ist gesetzt. Du kannst dich anmelden.",
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _konto(uid: str) -> User | None:
        try:
            pk = force_str(urlsafe_base64_decode(uid))
            return User.objects.get(pk=pk, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return None
