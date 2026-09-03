"""
Endpunkte fuer den E-Mail-Versand.

Alles hier ist Administrationssache: wer den Mailserver umstellt, kann im
Namen der Einrichtung schreiben. Deshalb steckt in jedem View dieselbe
Pruefung auf is_admin, und nicht bloss eine ausgeblendete Schaltflaeche im
Frontend.

Das Passwort geht nur in eine Richtung. Rein ja, raus nie - die API meldet
lediglich, ob eines hinterlegt ist.
"""

from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django_grp_backend.access import is_admin

from .models import MailMessage, MailSettings
from .service import einstellen, versenden

KEIN_ZUTRITT = {"error": "Die E-Mail-Einstellungen darf nur die Verwaltung ändern."}


class MailSettingsSerializer(serializers.ModelSerializer):
    """
    Die Einstellungen, wie das Frontend sie sieht.

    password ist write_only und darf leer bleiben: ein leeres Feld heisst
    "nicht anfassen", nicht "loeschen". Sonst wuerde jedes Speichern des
    Formulars das Passwort verwerfen, weil das Frontend es nie kennt.
    """

    password = serializers.CharField(
        write_only=True, required=False, allow_blank=True, trim_whitespace=False
    )
    has_password = serializers.BooleanField(read_only=True)
    ready = serializers.BooleanField(read_only=True)

    class Meta:
        model = MailSettings
        fields = [
            "host",
            "port",
            "use_tls",
            "use_ssl",
            "username",
            "password",
            "has_password",
            "from_address",
            "from_name",
            "timeout_seconds",
            "enabled",
            "ready",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]

    def validate(self, attrs):
        tls = attrs.get("use_tls", getattr(self.instance, "use_tls", True))
        ssl = attrs.get("use_ssl", getattr(self.instance, "use_ssl", False))
        if tls and ssl:
            raise serializers.ValidationError(
                {"use_ssl": "STARTTLS und SSL schließen sich aus. Bitte nur eines."}
            )
        return attrs

    def update(self, instance, validated_data):
        klartext = validated_data.pop("password", None)
        for feld, wert in validated_data.items():
            setattr(instance, feld, wert)
        if klartext:
            instance.password = klartext
        instance.save()
        return instance


class MailMessageSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = MailMessage
        fields = [
            "id",
            "to_address",
            "subject",
            "body",
            "kind",
            "kind_display",
            "status",
            "status_display",
            "error",
            "attempts",
            "created_at",
            "sent_at",
        ]


class MailSettingsView(APIView):
    """GET und PUT auf den einen Einstellungssatz."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_admin(request.user):
            return Response(KEIN_ZUTRITT, status=status.HTTP_403_FORBIDDEN)
        return Response(MailSettingsSerializer(MailSettings.laden()).data)

    def put(self, request):
        if not is_admin(request.user):
            return Response(KEIN_ZUTRITT, status=status.HTTP_403_FORBIDDEN)
        serializer = MailSettingsSerializer(
            MailSettings.laden(), data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class MailTestView(APIView):
    """
    Verschickt eine Testmail und wartet auf das Ergebnis.

    Bewusst nicht ueber Celery: wer auf "Test verschicken" drueckt, will
    wissen, ob es geklappt hat, und nicht, dass die Mail eingereiht wurde.
    Deshalb geht dieser eine Fall direkt raus.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not is_admin(request.user):
            return Response(KEIN_ZUTRITT, status=status.HTTP_403_FORBIDDEN)

        empfaenger = (request.data.get("to") or request.user.email or "").strip()
        if not empfaenger:
            return Response(
                {"error": "Bitte eine Empfängeradresse angeben."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        einstellungen = MailSettings.laden()
        if not einstellungen.host:
            return Response(
                {"error": "Es ist noch kein Server eingetragen."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not einstellungen.from_address:
            return Response(
                {"error": "Es fehlt die Absenderadresse."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        nachricht = MailMessage.objects.create(
            to_address=empfaenger,
            subject="Testmail aus dem Gruppenprotokoll",
            body=(
                "Diese Mail bestätigt, dass der Versand eingerichtet ist.\n\n"
                f"Server:   {einstellungen.host}:{einstellungen.port}\n"
                f"Absender: {einstellungen.absender}\n"
            ),
            kind="test",
        )
        nachricht = versenden(nachricht.id)

        daten = MailMessageSerializer(nachricht).data
        if nachricht.status == "sent":
            return Response(daten)
        return Response(daten, status=status.HTTP_502_BAD_GATEWAY)


class MailOutboxView(APIView):
    """Die letzten Mails - was rausging und was nicht."""

    permission_classes = [IsAuthenticated]

    # Der Postausgang ist eine Ansicht zum Nachschauen, kein Archiv. Wer
    # weiter zurueck muss, schaut ins Aenderungsprotokoll.
    GRENZE = 100

    def get(self, request):
        if not is_admin(request.user):
            return Response(KEIN_ZUTRITT, status=status.HTTP_403_FORBIDDEN)

        nachrichten = MailMessage.objects.all()
        stand = request.query_params.get("status")
        if stand:
            nachrichten = nachrichten.filter(status=stand)
        return Response(
            MailMessageSerializer(nachrichten[: self.GRENZE], many=True).data
        )


class MailRetryView(APIView):
    """Eine liegengebliebene Mail noch einmal versuchen."""

    permission_classes = [IsAuthenticated]

    def post(self, request, message_id: int):
        if not is_admin(request.user):
            return Response(KEIN_ZUTRITT, status=status.HTTP_403_FORBIDDEN)

        nachricht = MailMessage.objects.filter(id=message_id).first()
        if nachricht is None:
            return Response(
                {"error": "Diese Mail gibt es nicht."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if nachricht.status == "sent":
            return Response(
                {"error": "Diese Mail ist bereits verschickt."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        nachricht = versenden(nachricht.id)
        daten = MailMessageSerializer(nachricht).data
        if nachricht.status == "sent":
            return Response(daten)
        return Response(daten, status=status.HTTP_502_BAD_GATEWAY)


__all__ = [
    "MailSettingsView",
    "MailTestView",
    "MailOutboxView",
    "MailRetryView",
    "einstellen",
]
