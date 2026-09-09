import logging
import os
from datetime import timedelta

from PIL import Image
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets, status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from .guards import ProtokollGesperrt, protokoll_fuer, schreibbares_protokoll
from django_grp_backend.access import WriteNeedsRole, is_admin, may_read_only
from django_grp_backend.functions import upload_too_large
from django_grp_backend.models import (
    Allergy,
    Consent,
    Protocol,
    Group,
    Resident,
    ResidentContact,
    ProtocolAttendance,
    ProtocolObservation,
    ProtocolPresence,
    ProtocolItem,
    ProtocolTemplate,
    ProtocolTodo,
)
from .serializers import (
    ProtocolAttendanceSerializer,
    ProtocolObservationSerializer,
    ProtocolTemplateSerializer,
    ProtocolSerializer,
    ProtocolSummarySerializer,
    GroupSerializer,
    ResidentSerializer,
    AllergySerializer,
    ConsentSerializer,
    ResidentContactSerializer,
    ResidentPictureUploadSerializer,
    ItemSerializer,
    ProtocolTodoSerializer,
    UserProfileSerializer,
    UserDetailedProfileSerializer,
    ProtocolPresenceSerializer,
    GroupPDFTemplateSerializer,
    UserStaffSerializer,
    UserDetailSerializer,
)

logger = logging.getLogger("django_grp.api")


def serverfehler(vorgang: str, fehler: Exception) -> Response:
    """
    Ein unerwarteter Fehler, ohne Innereien nach aussen.

    Vorher stand an gut einem Dutzend Stellen `{"error": str(e)}` - und damit
    gingen Datenbankmeldungen, Dateipfade und Feldnamen an den Client (S9).
    Was passiert ist, gehoert ins Log, wo es jemand lesen kann, der es
    einordnen darf.
    """
    logger.exception("%s fehlgeschlagen: %s", vorgang, fehler)
    return Response(
        {"error": "Da ist etwas schiefgelaufen. Der Vorgang wurde protokolliert."},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


class LoginView(APIView):
    """
    Token-based login endpoint for Flutter and other clients.

    Im Feld "username" wird auch eine E-Mail-Adresse angenommen - siehe
    django_grp_backend.auth_backends.UsernameOrEmailBackend.

    POST /api/v1/auth/login/
    {
        "username": "string (Benutzername oder E-Mail)",
        "password": "string"
    }

    Returns:
    {
        "success": true,
        "data": {
            "token": "abc123def456...",
            "user": {
                "id": int,
                "username": "string",
                "email": "string",
                "first_name": "string",
                "last_name": "string"
            }
        }
    }
    """

    permission_classes = [AllowAny]
    # Ohne Bremse laesst sich hier eine Passwortliste durchprobieren, und
    # niemand merkt es. Der Takt steht in settings.DEFAULT_THROTTLE_RATES.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        if not username or not password:
            return Response(
                {
                    "success": False,
                    "error": "Bitte Benutzername oder E-Mail und Passwort angeben.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=username, password=password)

        if user is not None:
            # Get or create authentication token
            token, created = Token.objects.get_or_create(user=user)
            return Response(
                {
                    "success": True,
                    "data": {
                        "token": token.key,
                        "user": {
                            "id": user.id,
                            "username": user.username,
                            "email": user.email,
                            "first_name": user.first_name,
                            "last_name": user.last_name,
                        },
                    },
                },
                status=status.HTTP_200_OK,
            )
        else:
            return Response(
                {
                    "success": False,
                    "error": "Benutzername, E-Mail oder Passwort stimmen nicht.",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )


class LogoutView(APIView):
    """
    Token-based logout endpoint. Invalidates the user's authentication token.

    POST /api/v1/auth/logout/

    Returns:
    {
        "success": true,
        "message": "Logged out successfully"
    }
    """

    # Ohne WriteNeedsRole: Abmelden ist kein Schreibzugriff auf Fachdaten.
    # Mit der Rechteklasse bekam eine Aushilfe beim Abmelden ein 403, das
    # Cookie im Browser verschwand trotzdem - und der Token blieb
    # serverseitig gueltig. Genau anders herum ist es richtig.
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Delete the user's authentication token
        try:
            request.user.auth_token.delete()
        except Token.DoesNotExist:
            pass

        return Response(
            {"success": True, "message": "Logged out successfully"},
            status=status.HTTP_200_OK,
        )


class ProtocolViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, WriteNeedsRole]

    def get_serializer_class(self):
        """Use different serializers for list vs detail."""
        if self.action == "list":
            return ProtocolSummarySerializer
        return ProtocolSerializer

    def get_queryset(self):
        """Filter protocols by user group membership or staff status."""
        user = self.request.user
        return Protocol.objects.for_user(user).select_related("group")

    def perform_update(self, serializer):
        protocol = self.get_object()
        # Ein exportiertes Protokoll ist ein abgeschlossenes Dokument.
        if protocol.status == "exported":
            raise ProtokollGesperrt()
        serializer.save()

    def perform_destroy(self, instance):
        if instance.status == "exported":
            raise ProtokollGesperrt()
        instance.delete()


class GroupViewSet(viewsets.ModelViewSet):
    """
    Gruppen anlegen, aendern, loeschen - Verwaltung vorbehalten.

    Vorher trug diese Klasse nur WriteNeedsRole, und damit durfte jede
    Fachkraft Gruppen anlegen UND loeschen. Loeschen kaskadiert auf alle
    Bewohner und alle Protokolle der Gruppe (on_delete=CASCADE) - ein
    Fehlgriff, der sich ueber die Oberflaeche nicht rueckgaengig machen
    laesst. Lesen bleibt fuer alle Mitglieder offen.
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    serializer_class = GroupSerializer

    def get_queryset(self):
        """Filter groups by user membership or staff status."""
        user = self.request.user
        # prefetch: GroupSerializer.get_members liest die Rueckbeziehung,
        # sonst eine Abfrage je Gruppe.
        return Group.objects.for_user(user).prefetch_related("resident_set")

    def _require_admin(self):
        if not is_admin(self.request.user):
            raise PermissionDenied(
                "Gruppen anlegen, ändern und löschen ist der Verwaltung "
                "vorbehalten."
            )

    def perform_create(self, serializer):
        self._require_admin()
        serializer.save()

    def perform_update(self, serializer: GroupSerializer) -> None:
        self._require_admin()
        serializer.save()

    def perform_destroy(self, instance):
        self._require_admin()
        instance.delete()


class ResidentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, WriteNeedsRole]
    serializer_class = ResidentSerializer

    def get_queryset(self):
        """Filter residents by user group membership or staff status."""
        user = self.request.user
        # prefetch, weil der Serializer je Bewohner die Allergien
        # ueberfliegt - ohne das eine Abfrage je Zeile.
        return (
            Resident.objects.for_user(user)
            .select_related("group")
            .prefetch_related("allergies")
        )


class ResidentScopedViewSet(viewsets.ModelViewSet):
    """
    Basis fuer alles, was unter /api/v1/resident/{resident_id}/ haengt.

    Erledigt einmal, was Kontakte, Allergien und Einwilligungen gleichermassen
    brauchen: Bewohner aus der URL holen und pruefen, ob der Benutzer ihn
    ueberhaupt sehen darf.
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    model = None

    def get_resident(self):
        """Bewohner aus der URL, sofern der Benutzer darauf zugreifen darf."""
        return (
            Resident.objects.for_user(self.request.user)
            .filter(id=self.kwargs.get("resident_pk"))
            .first()
        )

    def get_queryset(self):
        resident = self.get_resident()
        if resident is None:
            return self.model.objects.none()
        return self.model.objects.filter(resident=resident)

    def perform_create(self, serializer):
        resident = self.get_resident()
        if resident is None:
            raise ValidationError("Bewohner nicht gefunden oder kein Zugriff.")
        serializer.save(resident=resident)


class AllergyViewSet(ResidentScopedViewSet):
    """
    Allergien und Unvertraeglichkeiten.

    /api/v1/resident/{resident_id}/allergy/

    Wer die Bewohnerakte sehen darf, sieht auch die Allergien - und zwar
    ausdruecklich auch die Aushilfe im Wochenenddienst. Eine Allergie, die
    von der Zugriffsstufe abhaengt, ist im falschen Moment nicht da.
    """

    serializer_class = AllergySerializer
    model = Allergy


class ConsentViewSet(ResidentScopedViewSet):
    """
    Einwilligungen der Sorgeberechtigten.

    /api/v1/resident/{resident_id}/consent/

    Ein Widerruf ist eine Aenderung, keine Loeschung: `revoked_on` setzen,
    Zeile stehen lassen. Dass eine Einwilligung damals gegolten hat, kann
    spaeter die entscheidende Frage sein.
    """

    serializer_class = ConsentSerializer
    model = Consent


class ResidentContactViewSet(viewsets.ModelViewSet):
    """
    Kontaktdaten zu einer Bewohnerin oder einem Bewohner.

    /api/v1/resident/{resident_id}/contact/

    Wer die Bewohnerakte sehen darf, darf auch die Kontakte pflegen: eine
    neue Handynummer der Mutter erfaehrt die Gruppe, nicht die Verwaltung.
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    serializer_class = ResidentContactSerializer

    def get_resident(self):
        """Bewohner aus der URL, sofern der Benutzer darauf zugreifen darf."""
        return (
            Resident.objects.for_user(self.request.user)
            .filter(id=self.kwargs.get("resident_pk"))
            .first()
        )

    def get_queryset(self):
        resident = self.get_resident()
        if resident is None:
            return ResidentContact.objects.none()
        return ResidentContact.objects.filter(resident=resident)

    def perform_create(self, serializer):
        resident = self.get_resident()
        if resident is None:
            raise ValidationError("Bewohner nicht gefunden oder kein Zugriff.")
        serializer.save(resident=resident)


class ProtocolScopedViewSet(viewsets.ModelViewSet):
    """
    Basis fuer alles, was unter /api/v1/protocol/{protocol_id}/ haengt.

    Erledigt einmal, was Aufgaben, Teilnahmen und Verlaufseintraege
    gleichermassen brauchen: Protokoll aus der URL holen, Gruppenzugehoerigkeit
    pruefen und Schreibzugriff auf exportierte Protokolle unterbinden.
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    model = None

    def get_protocol(self):
        """Protokoll aus der URL, sofern der Benutzer darauf zugreifen darf."""
        try:
            return protokoll_fuer(self.request.user, self.kwargs.get("protocol_pk"))
        except (NotFound, PermissionDenied):
            return None

    def require_writable_protocol(self):
        """Wie get_protocol, wirft aber sprechende Fehler fuer Schreibzugriffe."""
        return schreibbares_protokoll(self.request.user, self.kwargs.get("protocol_pk"))

    def get_serializer_context(self):
        """
        Das Protokoll steht dem Serializer zur Verfuegung.

        Er braucht es, um Fremdschluessel aus dem Rumpf gegen die Gruppe des
        Protokolls zu pruefen - siehe _resident_der_protokollgruppe.
        """
        context = super().get_serializer_context()
        context["protocol"] = self.get_protocol()
        return context

    def get_queryset(self):
        protocol = self.get_protocol()
        if protocol is None:
            return self.model.objects.none()
        return self.model.objects.filter(protocol=protocol)

    def perform_create(self, serializer):
        protocol = self.require_writable_protocol()
        serializer.save(protocol=protocol)

    def perform_update(self, serializer):
        self.require_writable_protocol()
        serializer.save()

    def perform_destroy(self, instance):
        self.require_writable_protocol()
        instance.delete()


class ProtocolTodoViewSet(ProtocolScopedViewSet):
    """
    Aufgaben eines Protokolls.

    /api/v1/protocol/{protocol_id}/todo/
    """

    serializer_class = ProtocolTodoSerializer
    model = ProtocolTodo


class TodoCollectionView(APIView):
    """
    Alle Aufgaben in einem Zeitfenster - ueber alle zugaenglichen Protokolle.

    GET /api/v1/todo/?von=2026-06-01&bis=2026-12-31

    Warum es diesen Endpunkt gibt: die Uebersicht braucht die faelligen
    Aufgaben aller Gruppen. Ohne Sammelabfrage faechert das Frontend auf und
    stellt bis zu vierzig Einzelanfragen /protocol/{id}/todo/ - je eine
    Verbindung, je ein Rundlauf, und alle nur, um am Ende eine Liste zu
    bauen (Analyse 6.7).

    Der Zeitraum ist Pflicht in dem Sinne, dass es eine Vorgabe gibt: 90 Tage
    zurueck, 180 nach vorn. Ohne Fenster waere das ein "alles" ueber die
    gesamte Betriebsdauer.
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]

    VORGABE_ZURUECK = 90
    VORGABE_VORAUS = 180

    def get(self, request):
        heute = timezone.localdate()
        von = self._datum(request.query_params.get("von")) or (
            heute - timedelta(days=self.VORGABE_ZURUECK)
        )
        bis = self._datum(request.query_params.get("bis")) or (
            heute + timedelta(days=self.VORGABE_VORAUS)
        )

        protokolle = Protocol.objects.for_user(request.user).filter(
            protocol_date__gte=von, protocol_date__lte=bis
        )

        aufgaben = (
            ProtocolTodo.objects.filter(protocol__in=protokolle)
            .select_related("protocol", "protocol__group")
            .order_by("when", "position")
        )

        daten = [
            {
                "id": aufgabe.id,
                "protocol": aufgabe.protocol_id,
                "protocol_date": aufgabe.protocol.protocol_date,
                "group": aufgabe.protocol.group_id,
                "what": aufgabe.what,
                "who": aufgabe.who,
                "when": aufgabe.when,
                "position": aufgabe.position,
            }
            for aufgabe in aufgaben
        ]
        return Response(daten, status=status.HTTP_200_OK)

    @staticmethod
    def _datum(wert):
        if not wert:
            return None
        return parse_date(wert)


class ProtocolAttendanceViewSet(ProtocolScopedViewSet):
    """
    Teilnehmende Bewohner eines Gruppenangebots.

    /api/v1/protocol/{protocol_id}/attendance/
    """

    serializer_class = ProtocolAttendanceSerializer
    model = ProtocolAttendance


class ProtocolObservationViewSet(ProtocolScopedViewSet):
    """
    Verlaufseintraege und Beobachtungen zum Protokoll.

    /api/v1/protocol/{protocol_id}/observation/
    """

    serializer_class = ProtocolObservationSerializer
    model = ProtocolObservation


class ProtocolTemplateViewSet(viewsets.ModelViewSet):
    """
    Protokollvorlagen (Protokolltypen).

    Sichtbar sind traegerweite Vorlagen (ohne Gruppe) und Vorlagen der eigenen
    Gruppen. Anlegen und Aendern bleibt dem Personal vorbehalten.
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]
    serializer_class = ProtocolTemplateSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = ProtocolTemplate.objects.prefetch_related("items")
        if is_admin(user):
            return queryset
        return queryset.filter(
            Q(group__isnull=True) | Q(group__group_members=user)
        ).distinct()

    def _require_staff(self):
        # PermissionDenied statt ValidationError: fehlende Rechte sind 403,
        # nicht 400.
        if not is_admin(self.request.user):
            raise PermissionDenied(
                "Nur Mitarbeitende duerfen Vorlagen anlegen oder aendern."
            )

    def perform_create(self, serializer):
        self._require_staff()
        serializer.save()

    def perform_update(self, serializer):
        self._require_staff()
        serializer.save()

    def perform_destroy(self, instance):
        self._require_staff()
        instance.delete()


class ProtocolPresenceUpdateView(APIView):
    """
    Anwesenheit einer Fachkraft im Protokoll setzen.

    POST /api/v1/presence/  {protocol, user, was_present}
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]

    def post(self, request):
        protocol = schreibbares_protokoll(request.user, request.data.get("protocol"))

        user_id = request.data.get("user")
        # Nur wer zur Gruppe gehoert, kann in ihrer Anwesenheitsliste stehen.
        # Ohne diese Pruefung liesse sich eine beliebige Kontonummer
        # eintragen - und stuende danach im PDF als anwesend.
        if not protocol.group.group_members.filter(id=user_id).exists():
            raise ValidationError(
                "Diese Person gehört nicht zum Team dieser Gruppe."
            )

        obj, created = ProtocolPresence.objects.update_or_create(
            protocol=protocol,
            user_id=user_id,
            defaults={"was_present": bool(request.data.get("was_present"))},
        )

        return Response(
            {
                "message": "Presence updated" if not created else "Presence created",
                "created": created,
            },
            status=status.HTTP_200_OK,
        )


class ItemValuesUpdateView(APIView):
    """
    Tagesordnungspunkt anlegen, aendern oder loeschen.

    Die Sicherheitsluecke, die hier lag (S3 der Analyse): geprueft wurde der
    Zugriff auf `protocol` aus dem Rumpf - geschrieben wurde danach mit
    `ProtocolItem.objects.filter(id=item_id).update(...)`, also ohne jeden
    Bezug zu diesem Protokoll. Wer Zugriff auf irgendein Protokoll hatte,
    konnte damit Eintraege JEDES Protokolls ueberschreiben und loeschen.

    Jetzt entscheidet nicht mehr die Nummer im Rumpf, sondern das Paar: der
    Eintrag muss zu dem Protokoll gehoeren, auf das der Zugriff geprueft
    wurde.
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]

    def post(self, request):
        serializer = ItemSerializer(data=request.data)
        if not serializer.is_valid():
            # Vorher stand hier data="message: serializer.errors" - der
            # String, nicht sein Inhalt. Im Frontend kam damit nie ein
            # brauchbarer Feldfehler an.
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        item_id = request.data.get("id") or request.data.get("item_id")
        if item_id == "":
            item_id = None

        protocol = schreibbares_protokoll(
            request.user, serializer.validated_data.get("protocol")
        )

        felder = {
            "protocol_id": protocol.id,
            "name": serializer.validated_data.get("name"),
            "value": serializer.validated_data.get("value"),
            "position": serializer.validated_data.get("position"),
        }

        # kind und data nur uebernehmen, wenn sie mitgeschickt wurden.
        #
        # Sie fehlten hier ganz - und damit ging jede Tabelle verloren. Wer
        # aus dem Menue "Eintrag hinzufuegen" eine Aufgabenliste oder einen
        # Massnahmenplan waehlte und speicherte, bekam einen leeren Freitext
        # zurueck: kind fiel auf die Vorgabe "text", data blieb null.
        #
        # Die Pruefung auf validated_data statt auf einen Vorgabewert ist der
        # Unterschied zwischen "nicht geschickt" und "auf leer gesetzt". Ein
        # aelterer Client, der beide Felder gar nicht kennt, darf eine
        # vorhandene Tabelle nicht loeschen; ein neuer, der ausdruecklich
        # data=null schickt, soll es koennen.
        geschickt = serializer.validated_data
        if "kind" in geschickt:
            felder["kind"] = geschickt.get("kind")
        if "data" in geschickt:
            felder["data"] = geschickt.get("data")

        if item_id:
            # Das Paar aus Eintrag UND Protokoll - hier lag die Luecke.
            geaendert = ProtocolItem.objects.filter(
                id=item_id, protocol_id=protocol.id
            ).update(**felder)
            if not geaendert:
                raise NotFound("Eintrag gehört nicht zu diesem Protokoll.")
            message = "Item updated"
        else:
            ProtocolItem.objects.create(**felder)
            message = "Item created"

        return Response({"message": message}, status=status.HTTP_200_OK)

    def delete(self, request):
        item = (
            ProtocolItem.objects.select_related("protocol__group")
            .filter(id=request.data.get("item_id"))
            .first()
        )
        if item is None:
            raise NotFound("Eintrag nicht gefunden.")

        # Ueber das Protokoll des Eintrags - nicht ueber eine Nummer aus dem
        # Rumpf. Damit kann auch das Loeschen keine Protokollgrenze ueberspringen.
        schreibbares_protokoll(request.user, item.protocol_id)

        item.delete()
        return Response({"message": "Item deleted"}, status=status.HTTP_200_OK)


class MentionAutocompleteView(APIView):
    """Bewohner der Protokollgruppe fuer die @-Erwaehnung."""

    permission_classes = [IsAuthenticated, WriteNeedsRole]

    def get(self, request):
        protocol_id = request.query_params.get("protocol_id")
        if not protocol_id:
            return Response(
                {"error": "protocol_id is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        protocol = protokoll_fuer(request.user, protocol_id)

        residents = Resident.objects.filter(
            group=protocol.group, moved_out_since__isnull=True
        )

        data = [
            {
                "id": resident.id,
                "name": resident.get_full_name(),
                "mention": resident.get_full_name().replace(" ", "_"),
            }
            for resident in residents
        ]

        return Response(data, status=status.HTTP_200_OK)


class RotateImageView(APIView):
    """
    Bewohnerfoto drehen.

    Frueher nahm dieser Endpunkt eine `image_url` aus dem Rumpf, setzte sie
    per os.path.join an MEDIA_ROOT und schrieb die Datei zurueck - ohne zu
    fragen, wessen Foto das ist und ob der Pfad ueberhaupt in MEDIA_ROOT
    liegt (S5). Ein "../" an der richtigen Stelle reichte.

    Jetzt kommt nur noch eine Bewohnernummer herein. Welche Datei dazu
    gehoert, weiss die Datenbank - und ob das Konto sie sehen darf, weiss
    Resident.objects.for_user.
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]

    def post(self, request, resident_id: int | None = None):
        richtung = request.data.get("direction")
        if richtung not in ("left", "right"):
            return Response(
                {"success": False, "error": "direction muss 'left' oder 'right' sein."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if resident_id is None:
            resident_id = request.data.get("resident_id") or request.data.get("resident")
        if not resident_id:
            return Response(
                {"success": False, "error": "resident_id ist erforderlich."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        resident = (
            Resident.objects.for_user(request.user).filter(id=resident_id).first()
        )
        if resident is None:
            return Response(
                {"success": False, "error": "Bewohner nicht gefunden."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not resident.picture:
            return Response(
                {"success": False, "error": "Zu dieser Person ist kein Foto hinterlegt."},
                status=status.HTTP_404_NOT_FOUND,
            )

        pfad = os.path.realpath(resident.picture.path)
        wurzel = os.path.realpath(settings.MEDIA_ROOT)
        # Guertel und Hosentraeger: der Pfad stammt zwar aus der Datenbank,
        # aber ein Datensatz mit "../" im Dateinamen bleibt denkbar.
        try:
            innerhalb = os.path.commonpath([pfad, wurzel]) == wurzel
        except ValueError:
            # Verschiedene Laufwerke - commonpath wirft dann, statt False zu
            # sagen. Der Fall gehoert in denselben Zweig.
            innerhalb = False

        if not innerhalb or not os.path.exists(pfad):
            logger.warning("Bilddatei ausserhalb von MEDIA_ROOT: %s", pfad)
            return Response(
                {"success": False, "error": "Bilddatei nicht gefunden."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            with Image.open(pfad) as img:
                gedreht = img.rotate(90 if richtung == "left" else -90, expand=True)
                gedreht.save(pfad)
        except OSError as fehler:
            return serverfehler("Foto drehen", fehler)

        return Response(
            {
                "success": True,
                "new_image_url": (
                    request.build_absolute_uri(resident.picture.url)
                    if request
                    else resident.picture.url
                ),
            },
            status=status.HTTP_200_OK,
        )


class UserProfileView(APIView):
    """
    Get authenticated user's profile information.

    GET /api/v1/user/profile/

    Returns:
    {
        "id": int,
        "username": "string",
        "email": "string",
        "first_name": "string",
        "last_name": "string",
        "is_staff": boolean,
        "is_superuser": boolean,
        "date_joined": "ISO 8601 datetime",
        "groups": ["group_name1", "group_name2"]
    }
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]

    def get(self, request):
        serializer = UserProfileSerializer(request.user, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request):
        """Update user profile (email, first_name, last_name)."""
        serializer = UserProfileSerializer(
            request.user, data=request.data, partial=True, context={"request": request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserMeView(APIView):
    """
    Get detailed authenticated user profile with group permissions.

    GET /api/v1/user/me/

    Returns:
    {
        "id": int,
        "username": "string",
        "email": "string",
        "first_name": "string",
        "last_name": "string",
        "is_staff": boolean,
        "is_superuser": boolean,
        "date_joined": "ISO 8601 datetime",
        "groups_with_permissions": [
            {
                "id": int,
                "name": "string",
                "address": "string",
                "postalcode": "string",
                "city": "string",
                "resident_count": int,
                "permissions": {
                    "is_member": boolean,
                    "is_staff": boolean,
                    "can_view": boolean,
                    "can_edit": boolean,
                    "can_delete": boolean
                }
            }
        ]
    }
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]

    def get(self, request):
        """Get detailed user profile with group permissions and resident counts."""
        serializer = UserDetailedProfileSerializer(
            request.user, context={"request": request}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


class ResidentPictureView(APIView):
    """
    Get resident picture by resident ID.

    GET /api/v1/resident/{id}/picture/

    Returns: Image file or 404 if not found/no picture
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]

    def get(self, request, resident_id: int):
        try:
            resident = Resident.objects.for_user(request.user).get(id=resident_id)

            if not resident.picture:
                return Response(
                    {"error": "Resident has no picture"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            return Response(
                {
                    "id": resident.id,
                    "name": resident.get_full_name(),
                    "picture_url": request.build_absolute_uri(resident.picture.url),
                },
                status=status.HTTP_200_OK,
            )
        except Resident.DoesNotExist:
            return Response(
                {"error": "Resident not found"}, status=status.HTTP_404_NOT_FOUND
            )

    def delete(self, request, resident_id: int):
        """
        Foto entfernen.

        Loescht auch die Datei, nicht nur den Verweis darauf - ein Bild eines
        Kindes, das niemand mehr sehen soll, hat auf der Platte nichts mehr
        verloren.
        """
        try:
            resident = Resident.objects.for_user(request.user).get(id=resident_id)
        except Resident.DoesNotExist:
            return Response(
                {"error": "Resident not found"}, status=status.HTTP_404_NOT_FOUND
            )

        if not resident.picture:
            return Response(status=status.HTTP_204_NO_CONTENT)

        resident.picture.delete(save=False)
        resident.picture = None
        resident.save(update_fields=["picture"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ResidentPictureUploadView(APIView):
    """
    Upload or update resident picture.

    POST /api/v1/resident/{id}/upload-picture/

    Request (multipart/form-data):
    - picture: Image file

    Returns:
    {
        "success": true,
        "message": "Picture uploaded successfully",
        "resident_id": int,
        "picture_url": "https://..."
    }

    Access Control:
    - User must be staff OR member of resident's group.group_members
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]

    def post(self, request, resident_id: int):
        try:
            # Get resident
            try:
                resident = Resident.objects.for_user(request.user).get(id=resident_id)
            except Resident.DoesNotExist:
                return Response(
                    {"error": "Resident not found"}, status=status.HTTP_404_NOT_FOUND
                )

            # Check access: user must be staff or member of resident's group
            is_member = resident.group.group_members.filter(id=request.user.id).exists()
            if not is_member and not is_admin(request.user):
                return Response(
                    {
                        "error": "You do not have permission to update this resident's picture"
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Check if picture file is provided
            if "picture" not in request.FILES:
                return Response(
                    {"error": "picture file is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Validate and upload picture
            serializer = ResidentPictureUploadSerializer(
                resident,
                data={"picture": request.FILES["picture"]},
                partial=True,
                context={"request": request},
            )

            if serializer.is_valid():
                serializer.save()
                return Response(
                    {
                        "success": True,
                        "message": "Picture uploaded successfully",
                        "resident_id": resident.id,
                        "picture_url": (
                            request.build_absolute_uri(resident.picture.url)
                            if resident.picture
                            else None
                        ),
                    },
                    status=status.HTTP_200_OK,
                )
            else:
                return Response(
                    {
                        "success": False,
                        "error": "Invalid picture file",
                        "details": serializer.errors,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as fehler:  # noqa: BLE001
            return serverfehler(self.__class__.__name__, fehler)


class GroupPDFTemplateView(APIView):
    """
    Upload or update PDF template for a group.

    POST /api/v1/group/{id}/pdf_template/

    Request (multipart/form-data):
    - pdf_template: PDF file

    Returns:
    {
        "success": true,
        "message": "PDF template updated",
        "group_id": int,
        "template_url": "https://..."
    }

    Access Control:
    - User must be staff OR member of group.group_members
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]

    def post(self, request, group_id: int):
        try:
            # Get group
            try:
                group = Group.objects.get(id=group_id)
            except Group.DoesNotExist:
                return Response(
                    {"error": "Group not found"}, status=status.HTTP_404_NOT_FOUND
                )

            # Check access: user must be staff or member of group
            is_member = group.group_members.filter(id=request.user.id).exists()
            if not is_member and not is_admin(request.user):
                return Response(
                    {
                        "error": "You do not have permission to update this group's PDF template"
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Check if PDF file is provided
            if "pdf_template" not in request.FILES:
                return Response(
                    {"error": "PDF file is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            pdf_file = request.FILES["pdf_template"]

            # Validate file type
            if not pdf_file.name.lower().endswith(".pdf"):
                return Response(
                    {"error": "Only PDF files are allowed"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            oversized = upload_too_large(pdf_file)
            if oversized:
                return Response(
                    {"error": oversized}, status=status.HTTP_400_BAD_REQUEST
                )

            # Update group with new template
            group.pdf_template = pdf_file
            group.save()

            return Response(
                {
                    "success": True,
                    "message": "PDF template updated",
                    "group_id": group.id,
                    "template_url": (
                        request.build_absolute_uri(group.pdf_template.url)
                        if group.pdf_template
                        else None
                    ),
                },
                status=status.HTTP_200_OK,
            )

        except Exception as fehler:  # noqa: BLE001
            return serverfehler(self.__class__.__name__, fehler)

    def delete(self, request, group_id: int):
        """
        Briefbogen entfernen - danach exportiert die Gruppe wieder schmucklos.

        Dieselbe Rechtepruefung wie beim Hochladen: wer den Briefbogen setzen
        darf, darf ihn auch wieder wegnehmen.
        """
        try:
            group = Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            return Response(
                {"error": "Group not found"}, status=status.HTTP_404_NOT_FOUND
            )

        is_member = group.group_members.filter(id=request.user.id).exists()
        if not is_member and not is_admin(request.user):
            return Response(
                {"error": "You do not have permission to update this group"},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not group.pdf_template:
            return Response(status=status.HTTP_204_NO_CONTENT)

        group.pdf_template.delete(save=False)
        group.pdf_template = None
        group.save(update_fields=["pdf_template"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProtocolExportedFileView(APIView):
    """
    Die exportierte Datei eines Protokolls.

    GET  /api/v1/protocol/{id}/exported_file/   Datei abrufen
    POST /api/v1/protocol/{id}/exported_file/   Datei ablegen und abschliessen

    Der POST ist der Vorgang, der ein Protokoll sperrt. Er verlangt deshalb
    zweierlei mehr als frueher: eine PDF-Datei (kein beliebiger Anhang) und
    die ausdrueckliche Bestaetigung `confirm=true`. Vorher genuegte ein
    versehentlicher Aufruf, um die Dokumentation eines Abends festzuschreiben.
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]

    def get(self, request, protocol_id: int):
        protocol = protokoll_fuer(request.user, protocol_id)

        if not protocol.exported_file:
            return Response(
                {"error": "Zu diesem Protokoll liegt keine Exportdatei vor."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "id": protocol.id,
                "protocol_date": protocol.protocol_date,
                "exported": protocol.exported,
                "file_url": request.build_absolute_uri(protocol.exported_file.url),
                "file_name": protocol.exported_file.name.split("/")[-1],
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, protocol_id: int):
        protocol = protokoll_fuer(request.user, protocol_id)

        if protocol.status == "exported":
            raise ProtokollGesperrt()

        if "exported_file" not in request.FILES:
            return Response(
                {"error": "exported_file ist erforderlich."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Die Bestaetigung kommt als Formularfeld, also als Text.
        bestaetigt = str(request.data.get("confirm", "")).lower() in (
            "1",
            "true",
            "ja",
            "on",
        )
        if not bestaetigt:
            return Response(
                {
                    "error": (
                        "Der Export schließt das Protokoll ab. "
                        "Bitte mit confirm=true bestätigen."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        datei = request.FILES["exported_file"]
        if not datei.name.lower().endswith(".pdf"):
            return Response(
                {"error": "Es lassen sich nur PDF-Dateien ablegen."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        zu_gross = upload_too_large(datei)
        if zu_gross:
            return Response({"error": zu_gross}, status=status.HTTP_400_BAD_REQUEST)

        protocol.exported_file = datei
        protocol.exported = True
        protocol.status = "exported"
        protocol.save()

        return Response(
            {
                "success": True,
                "message": "Exported file uploaded successfully",
                "protocol_id": protocol.id,
                "exported": protocol.exported,
                "status": protocol.status,
                "file_url": request.build_absolute_uri(protocol.exported_file.url),
                "file_name": protocol.exported_file.name.split("/")[-1],
            },
            status=status.HTTP_200_OK,
        )


class ProtocolPresenceListView(APIView):
    """
    Anwesenheitszeilen eines Protokolls.

    GET /api/v1/protocol/{id}/presence/
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]

    def get(self, request, protocol_id: int):
        protocol = protokoll_fuer(request.user, protocol_id)
        eintraege = ProtocolPresence.objects.filter(protocol=protocol).select_related(
            "user"
        )
        serializer = ProtocolPresenceSerializer(eintraege, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AdminUserListView(APIView):
    """
    Admin: List all users in the system with their group memberships and permissions.

    GET /api/v1/admin/users/

    Returns:
    [
        {
            "id": int,
            "username": "string",
            "email": "string",
            "first_name": "string",
            "last_name": "string",
            "is_staff": boolean,
            "is_superuser": boolean,
            "is_active": boolean,
            "date_joined": "ISO 8601 datetime",
            "groups": [{"id": int, "name": "string"}],
            "permissions": [...]
        }
    ]

    Access Control:
    - Staff only (is_staff == true)
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]

    def get(self, request):
        """List all users (staff only)."""
        if not is_admin(request.user):
            return Response(
                {"error": "Sie haben keine Berechtigung, um diese Seite zu sehen."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            users = User.objects.all().order_by("first_name", "last_name")
            serializer = UserDetailSerializer(
                users, many=True, context={"request": request}
            )
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as fehler:  # noqa: BLE001
            return serverfehler(self.__class__.__name__, fehler)

    def post(self, request):
        """Create a new user (staff only)."""
        if not is_admin(request.user):
            return Response(
                {
                    "error": "Sie haben keine Berechtigung, um diese Aktion durchzuführen."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            username = request.data.get("username")
            email = request.data.get("email")
            first_name = request.data.get("first_name", "")
            last_name = request.data.get("last_name", "")
            password = request.data.get("password")
            is_staff = request.data.get("is_staff", False)

            # Validation
            if not username or not password:
                return Response(
                    {"error": "Username und Passwort sind erforderlich."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if User.objects.filter(username=username).exists():
                return Response(
                    {"error": f"Benutzer '{username}' existiert bereits."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Create user
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                is_staff=is_staff,
            )

            serializer = UserDetailSerializer(user, context={"request": request})
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as fehler:  # noqa: BLE001
            return serverfehler(self.__class__.__name__, fehler)


class AdminUserDetailView(APIView):
    """
    Admin: Get, update, or delete a specific user.

    GET/PUT/DELETE /api/v1/admin/users/{user_id}/

    Access Control:
    - Staff only (is_staff == true)
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]

    def _get_user_or_404(self, user_id: int):
        """Helper to get user or return 404."""
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None

    def get(self, request, user_id: int):
        """Get user details (staff only)."""
        if not is_admin(request.user):
            return Response(
                {"error": "Sie haben keine Berechtigung."},
                status=status.HTTP_403_FORBIDDEN,
            )

        user = self._get_user_or_404(user_id)
        if not user:
            return Response(
                {"error": "Benutzer nicht gefunden."}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = UserDetailSerializer(user, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @staticmethod
    def _letzter_zugang(user, *, deaktivieren: bool) -> str | None:
        """
        Sperrt dieser Vorgang die Verwaltung aus?

        Zwei Faelle, die frueher beide durchgingen und in derselben Sackgasse
        endeten - kein Konto mehr, das die Anwendung verwalten kann, und kein
        Weg zurueck ausser ueber die Kommandozeile (S10):

          - das eigene Konto loeschen oder stilllegen
          - den letzten aktiven Superuser loeschen oder stilllegen
        """
        if not user.is_superuser:
            return None
        verbleibend = (
            User.objects.filter(is_superuser=True, is_active=True)
            .exclude(pk=user.pk)
            .exists()
        )
        if verbleibend:
            return None
        return (
            "Das ist das letzte aktive Verwaltungskonto. Ohne es lässt sich "
            "die Anwendung nicht mehr verwalten - zuerst ein zweites anlegen."
        )

    def put(self, request, user_id: int):
        """Update user details (staff only)."""
        if not is_admin(request.user):
            return Response(
                {"error": "Sie haben keine Berechtigung."},
                status=status.HTTP_403_FORBIDDEN,
            )

        user = self._get_user_or_404(user_id)
        if not user:
            return Response(
                {"error": "Benutzer nicht gefunden."}, status=status.HTTP_404_NOT_FOUND
            )

        stilllegen = "is_active" in request.data and not request.data["is_active"]
        if stilllegen:
            if user.pk == request.user.pk:
                return Response(
                    {"error": "Das eigene Konto lässt sich nicht stilllegen."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            hindernis = self._letzter_zugang(user, deaktivieren=True)
            if hindernis:
                return Response(
                    {"error": hindernis}, status=status.HTTP_400_BAD_REQUEST
                )

        if "email" in request.data:
            adresse = (request.data["email"] or "").strip()
            if (
                adresse
                and User.objects.filter(email__iexact=adresse)
                .exclude(pk=user.pk)
                .exists()
            ):
                return Response(
                    {
                        "error": (
                            "Diese E-Mail-Adresse gehört bereits zu einem "
                            "anderen Konto."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            # Update allowed fields
            if "email" in request.data:
                user.email = request.data["email"]
            if "first_name" in request.data:
                user.first_name = request.data["first_name"]
            if "last_name" in request.data:
                user.last_name = request.data["last_name"]
            if "is_active" in request.data:
                user.is_active = request.data["is_active"]
            if "password" in request.data and request.data["password"]:
                user.set_password(request.data["password"])

            user.save()
            serializer = UserDetailSerializer(user, context={"request": request})
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as fehler:  # noqa: BLE001
            return serverfehler(self.__class__.__name__, fehler)

    def delete(self, request, user_id: int):
        """Delete user (staff only)."""
        if not is_admin(request.user):
            return Response(
                {"error": "Sie haben keine Berechtigung."},
                status=status.HTTP_403_FORBIDDEN,
            )

        user = self._get_user_or_404(user_id)
        if not user:
            return Response(
                {"error": "Benutzer nicht gefunden."}, status=status.HTTP_404_NOT_FOUND
            )

        if user.pk == request.user.pk:
            return Response(
                {"error": "Das eigene Konto lässt sich nicht löschen."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        hindernis = self._letzter_zugang(user, deaktivieren=False)
        if hindernis:
            return Response({"error": hindernis}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user.delete()
            return Response(
                {"message": "Benutzer erfolgreich gelöscht."},
                status=status.HTTP_204_NO_CONTENT,
            )
        except Exception as fehler:  # noqa: BLE001
            return serverfehler("Konto löschen", fehler)


class AdminUserGroupView(APIView):
    """
    Admin: Manage user group memberships.

    POST /api/v1/admin/users/{user_id}/groups/
    - Add user to group

    DELETE /api/v1/admin/users/{user_id}/groups/{group_id}/
    - Remove user from group

    Access Control:
    - Staff only (is_staff == true)
    """

    permission_classes = [IsAuthenticated, WriteNeedsRole]

    def post(self, request, user_id: int):
        """Add user to group (staff only)."""
        if not is_admin(request.user):
            return Response(
                {"error": "Sie haben keine Berechtigung."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"error": "Benutzer nicht gefunden."}, status=status.HTTP_404_NOT_FOUND
            )

        group_id = request.data.get("group_id")
        if not group_id:
            return Response(
                {"error": "group_id ist erforderlich."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            group = Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            return Response(
                {"error": "Gruppe nicht gefunden."}, status=status.HTTP_404_NOT_FOUND
            )

        try:
            group.group_members.add(user)
            serializer = UserDetailSerializer(user, context={"request": request})
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as fehler:  # noqa: BLE001
            return serverfehler(self.__class__.__name__, fehler)

    def delete(self, request, user_id: int, group_id: int):
        """Remove user from group (staff only)."""
        if not is_admin(request.user):
            return Response(
                {"error": "Sie haben keine Berechtigung."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"error": "Benutzer nicht gefunden."}, status=status.HTTP_404_NOT_FOUND
            )

        try:
            group = Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            return Response(
                {"error": "Gruppe nicht gefunden."}, status=status.HTTP_404_NOT_FOUND
            )

        try:
            group.group_members.remove(user)
            serializer = UserDetailSerializer(user, context={"request": request})
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as fehler:  # noqa: BLE001
            return serverfehler(self.__class__.__name__, fehler)
