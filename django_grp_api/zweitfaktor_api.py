"""
Ein- und ausschalten des zweiten Faktors.

Vier Wege, und der vierte ist der, auf den es ankommt:

    GET  /api/v1/zweitfaktor/              Stand des eigenen Kontos
    POST /api/v1/zweitfaktor/einrichten/   Geheimnis erzeugen
    POST /api/v1/zweitfaktor/bestaetigen/  mit einem Code scharf schalten
    POST /api/v1/zweitfaktor/aus/          abschalten, mit einem Code
    POST /api/v1/zweitfaktor/zuruecksetzen/  die Verwaltung fuer ein anderes
                                             Konto - der Notfallweg

Der letzte ist der einzige Weg zurueck, wenn ein Telefon verloren geht.
Wiederherstellungscodes gibt es bewusst nicht (Entscheidung vom
11. September 2026). Deshalb steht jedes Zuruecksetzen im
Aenderungsprotokoll, und deshalb braucht jedes Konto, das zuruecksetzen
darf, selbst einen zweiten Faktor.
"""

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from django_grp_backend import zweitfaktor
from django_grp_backend.models import ZweiterFaktor
from django_grp_backend.rechte import verwaltet, zweitfaktor_pflicht

HERAUSGEBER = "Gruppenprotokoll"


def stand(user) -> dict:
    """
    Was die Oberflaeche ueber den eigenen Faktor wissen muss.

    `pflicht` steht auch dann drin, wenn der Faktor schon aktiv ist: die
    Oberflaeche blendet den Ausschalten-Knopf danach aus, statt ihn
    anzubieten und die Absage erst vom Server zu holen.
    """
    eintrag = ZweiterFaktor.objects.filter(user=user).first()
    return {
        "aktiv": bool(eintrag and eintrag.ist_aktiv),
        "eingerichtet": bool(eintrag),
        "pflicht": zweitfaktor_pflicht(user),
    }


class ZweitfaktorStandView(APIView):
    """Der eigene Stand."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(stand(request.user), status=status.HTTP_200_OK)


class ZweitfaktorEinrichtenView(APIView):
    """
    Erzeugt ein Geheimnis und gibt es einmal heraus.

    Danach ist es nicht mehr abrufbar: die Anwendung gibt es genau hier
    heraus, die App legt es weg, und der naechste Aufruf erzeugt ein neues.
    Waere es jederzeit lesbar, genuegte ein gestohlener Anmeldetoken, um den
    zweiten Faktor mitzunehmen - und dann waere er keiner.

    Ein bereits aktiver Faktor wird nicht ueberschrieben. Wer wechseln will,
    schaltet erst ab.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        eintrag = ZweiterFaktor.objects.filter(user=request.user).first()
        if eintrag and eintrag.ist_aktiv:
            return Response(
                {
                    "success": False,
                    "error": (
                        "Der zweite Faktor ist bereits aktiv. Zum Wechseln erst "
                        "abschalten."
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        geheimnis = zweitfaktor.geheimnis_erzeugen()
        if eintrag is None:
            eintrag = ZweiterFaktor(user=request.user)
        eintrag.geheimnis = geheimnis
        eintrag.bestaetigt_am = None
        eintrag.letzter_schritt = None
        eintrag.save()

        return Response(
            {
                "success": True,
                "data": {
                    "geheimnis": geheimnis,
                    "otpauth": zweitfaktor.otpauth(
                        geheimnis, request.user.username, HERAUSGEBER
                    ),
                },
            },
            status=status.HTTP_200_OK,
        )


class ZweitfaktorBestaetigenView(APIView):
    """
    Schaltet scharf, sobald ein Code stimmt.

    Der Schritt zwischen Einrichten und Bestaetigen ist kein Formalismus: er
    beweist, dass die App das Geheimnis wirklich hat und dass die Uhren
    zusammenpassen. Ohne ihn sperrt sich aus, wer die Einrichtung abbricht.
    """

    permission_classes = [IsAuthenticated]
    # Sechs Stellen sind eine Million Moeglichkeiten. Ohne Bremse ist das in
    # einer halben Stunde durchprobiert.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        eintrag = ZweiterFaktor.objects.filter(user=request.user).first()
        if eintrag is None or not eintrag.geheim_verschluesselt:
            return Response(
                {"success": False, "error": "Es ist nichts eingerichtet."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        schritt = zweitfaktor.pruefen(
            eintrag.geheimnis, request.data.get("code", "")
        )
        if schritt is None:
            return Response(
                {"success": False, "error": "Der Code stimmt nicht."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        eintrag.bestaetigt_am = timezone.now()
        eintrag.letzter_schritt = schritt
        eintrag.zuletzt_verwendet = timezone.now()
        eintrag.save()

        return Response(
            {"success": True, "data": stand(request.user)},
            status=status.HTTP_200_OK,
        )


class ZweitfaktorAusView(APIView):
    """
    Abschalten, mit einem gueltigen Code.

    Der Code ist noetig, weil sonst ein gestohlener Anmeldetoken genuegte,
    um den Faktor zu entfernen. Wer Pflicht hat, kann nicht abschalten - dort
    fuehrt der Weg ueber die Verwaltung.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        if zweitfaktor_pflicht(request.user):
            return Response(
                {
                    "success": False,
                    "error": (
                        "Für Konten mit Verwaltungsrechten ist der zweite "
                        "Faktor Pflicht und lässt sich nicht abschalten."
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        eintrag = ZweiterFaktor.objects.filter(user=request.user).first()
        if eintrag is None or not eintrag.ist_aktiv:
            return Response(
                {"success": True, "data": stand(request.user)},
                status=status.HTTP_200_OK,
            )

        if (
            zweitfaktor.pruefen(
                eintrag.geheimnis,
                request.data.get("code", ""),
                zuletzt=eintrag.letzter_schritt,
            )
            is None
        ):
            return Response(
                {"success": False, "error": "Der Code stimmt nicht."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        eintrag.delete()
        return Response(
            {"success": True, "data": stand(request.user)},
            status=status.HTTP_200_OK,
        )


class ZweitfaktorZuruecksetzenView(APIView):
    """
    Die Verwaltung setzt den Faktor eines anderen Kontos zurueck.

    Der einzige Weg zurueck nach einem verlorenen Telefon, und damit der
    empfindlichste Endpunkt der Anwendung: er hebt fuer ein fremdes Konto
    den zweiten Faktor auf.

    Drei Schranken:

    1. Nur wer verwalten darf. Dieselbe Zeile der Rechtematrix, an der auch
       die Pflicht haengt - wer zuruecksetzen darf, hat selbst einen Faktor.
    2. Nicht fuer das eigene Konto. Sonst waere es kein Notfallweg, sondern
       ein Abschalten ohne Code an der Pruefung in `ZweitfaktorAusView`
       vorbei.
    3. Jedes Zuruecksetzen steht im Aenderungsprotokoll. Das Modell ist dort
       eingetragen; die Zeile entsteht durch das Loeschen von selbst.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not verwaltet(request.user):
            return Response(
                {
                    "success": False,
                    "error": "Dafür fehlen die Rechte.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        konto_id = request.data.get("user")
        konto = User.objects.filter(id=konto_id).first() if konto_id else None
        if konto is None:
            return Response(
                {"success": False, "error": "Konto nicht gefunden."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if konto == request.user:
            return Response(
                {
                    "success": False,
                    "error": (
                        "Das eigene Konto lässt sich hier nicht zurücksetzen. "
                        "Zum Wechseln den Faktor abschalten und neu einrichten."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        ZweiterFaktor.objects.filter(user=konto).delete()

        return Response(
            {
                "success": True,
                "data": {
                    "user": konto.id,
                    "hinweis": (
                        f"Der zweite Faktor von {konto.username} ist "
                        "zurückgesetzt. Die Person richtet ihn beim nächsten "
                        "Anmelden neu ein."
                    ),
                },
            },
            status=status.HTTP_200_OK,
        )
