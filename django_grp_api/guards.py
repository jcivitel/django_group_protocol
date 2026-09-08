"""
Wer darf an welches Protokoll - an einer Stelle beantwortet.

Vorher stand dieselbe Pruefung in acht Views, jedes Mal etwas anders
formuliert: mal 400, mal 403, mal "koennen", mal "können". Wer die Sperre
umgehen wollte, musste nur die Stelle finden, an der sie vergessen worden
war - und bei ItemValuesUpdateView war sie das (S3).

Deshalb hier, und nur hier:

    protokoll_fuer(user, id)      Zugriff pruefen, sonst 404/403
    schreibbares_protokoll(...)   dasselbe, plus Schreibschutz nach Export
    ProtokollGesperrt             immer 403, immer derselbe Satz
"""

from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied

from django_grp_backend.access import is_admin
from django_grp_backend.models import Protocol

GESPERRT = "Exportierte Protokolle können nicht bearbeitet werden."
KEIN_ZUGRIFF = "Kein Zugriff auf dieses Protokoll."


class ProtokollGesperrt(APIException):
    """
    Ein exportiertes Protokoll ist ein abgeschlossenes Dokument.

    403 und nicht 400: die Anfrage ist in Ordnung, sie ist nur nicht erlaubt.
    Vorher kam je nach Endpunkt das eine oder das andere zurueck, und das
    Frontend musste beides abfangen (W8).
    """

    status_code = status.HTTP_403_FORBIDDEN
    default_detail = GESPERRT
    default_code = "protokoll_gesperrt"


def darf_sehen(user, protocol: Protocol) -> bool:
    if is_admin(user):
        return True
    return protocol.group.group_members.filter(id=user.id).exists()


def protokoll_fuer(user, protocol_id) -> Protocol:
    """
    Protokoll aus der Datenbank, sofern das Konto es sehen darf.

    Nimmt eine Nummer oder ein bereits geladenes Protokoll an - ein
    Serializer liefert im validated_data das Objekt, eine URL die Nummer.
    """
    if isinstance(protocol_id, Protocol):
        protocol_id = protocol_id.pk

    try:
        protocol = Protocol.objects.select_related("group").get(id=protocol_id)
    except (Protocol.DoesNotExist, TypeError, ValueError):
        raise NotFound("Protokoll nicht gefunden.")

    if not darf_sehen(user, protocol):
        # Bewusst 403 und nicht 404: dass es die Nummer gibt, verraet nichts,
        # was nicht ohnehin aus der fortlaufenden Zaehlung folgt.
        raise PermissionDenied(KEIN_ZUGRIFF)
    return protocol


def schreibbares_protokoll(user, protocol_id) -> Protocol:
    """Wie protokoll_fuer, weist aber Aenderungen an Exportiertem ab."""
    protocol = protokoll_fuer(user, protocol_id)
    if protocol.status == "exported":
        raise ProtokollGesperrt()
    return protocol
