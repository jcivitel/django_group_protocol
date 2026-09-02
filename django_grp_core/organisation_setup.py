"""
Einrichtungsassistent: die Organisation in einem Schritt anlegen.

Bis hierhin brauchte es dafuer die Kommandozeile - seed_organisation oder
den Django-Admin. Beides setzt voraus, dass jemand Python installiert hat
und weiss, was ein Manage-Command ist. Eine Wohngruppenleitung hat weder
das eine noch das andere, und soll es auch nicht brauchen.

Der Endpunkt legt zusammen an, was ohne einander sinnlos waere: Traeger,
Einrichtung und Bereich. Alles in einer Transaktion - eine halb angelegte
Organisation waere schlimmer als gar keine, weil die Statusabfrage sie
danach fuer fertig hielte.
"""

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django_grp_backend.access import is_admin


class OrganisationSetupView(APIView):
    """
    POST /setup/organisation/

    {
      "provider": {"name", "short_name", "address", "postalcode", "city"},
      "facility": {"name"},          optional, sonst wie der Traeger
      "department": {"name"},        optional, Vorgabe "Wohngruppe"
      "group": {"name", "address", "postalcode", "city", "color"}   optional
    }

    Nur fuer Konten mit Verwaltungszugriff, und nur solange es noch keinen
    Traeger gibt. Die zweite Bedingung ist die wichtigere: ohne sie waere
    das hier ein Weg, fremden Mandanten in eine laufende Installation zu
    setzen.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django_grp_backend.models import Group
        from django_grp_duty.models import ShiftType
        from django_grp_org.defaults import (
            ensure_shift_types,
            ensure_worktime_models,
        )
        from django_grp_org.models import (
            Department,
            Employee,
            Facility,
            Provider,
            Site,
            WorkTimeModel,
        )

        if not is_admin(request.user):
            return Response(
                {"error": "Nur die Verwaltung kann die Organisation anlegen."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if Provider.objects.exists():
            return Response(
                {"error": "Es gibt bereits einen Träger."},
                status=status.HTTP_409_CONFLICT,
            )

        provider_data = request.data.get("provider") or {}
        name = (provider_data.get("name") or "").strip()
        if not name:
            return Response(
                {"error": "Der Name des Trägers fehlt."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        facility_name = (
            (request.data.get("facility") or {}).get("name") or ""
        ).strip() or name
        department_name = (
            (request.data.get("department") or {}).get("name") or ""
        ).strip() or "Wohngruppe"

        group_data = request.data.get("group") or {}
        group_name = (group_data.get("name") or "").strip()

        try:
            with transaction.atomic():
                provider = Provider.objects.create(
                    name=name,
                    short_name=(provider_data.get("short_name") or "").strip(),
                    address=(provider_data.get("address") or "").strip(),
                    postalcode=(provider_data.get("postalcode") or "").strip(),
                    city=(provider_data.get("city") or "").strip(),
                )
                site = Site.objects.create(
                    provider=provider,
                    name=facility_name,
                    address=provider.address,
                    postalcode=provider.postalcode,
                    city=provider.city,
                )
                facility = Facility.objects.create(
                    site=site,
                    name=facility_name,
                )

                group = None
                if group_name:
                    group = Group.objects.create(
                        name=group_name,
                        address=(group_data.get("address") or provider.address),
                        postalcode=(
                            group_data.get("postalcode") or provider.postalcode
                        ),
                        city=(group_data.get("city") or provider.city),
                        color=(group_data.get("color") or "#abc270"),
                    )
                    # Wer einrichtet, gehoert in die erste Gruppe - sonst
                    # steht die Person danach vor einer leeren Uebersicht.
                    group.group_members.add(request.user)

                department = Department.objects.create(
                    facility=facility,
                    name=department_name,
                    group=group,
                )

                # Arbeitszeitmodelle haengen am Traeger und koennen deshalb
                # erst hier entstehen. Die Migration, die dieselben Vorgaben
                # anlegt, findet bei einer frischen Installation noch keinen
                # Traeger vor - ohne diese Zeile begaenne der Betrieb mit
                # einer leeren Auswahlliste.
                ensure_worktime_models(WorkTimeModel, provider)
                # Ohne Dienstart erzeugt spaeter kein Dienstplan Dienste.
                ensure_shift_types(ShiftType, provider)

                # Der einrichtenden Person einen Personaldatensatz geben,
                # falls sie noch keinen hat. Ohne ihn taucht das eigene
                # Konto in der zusammengelegten Personalliste nicht auf.
                employee = getattr(request.user, "employee", None)
                if employee is None:
                    employee = Employee.objects.create(
                        provider=provider,
                        user=request.user,
                        access_level="admin",
                        first_name=request.user.first_name or request.user.username,
                        last_name=request.user.last_name or "",
                        email=request.user.email or "",
                        hired_on=request.user.date_joined.date(),
                    )
                elif employee.provider_id is None:
                    employee.provider = provider
                    employee.save(update_fields=["provider"])
        except Exception as error:  # noqa: BLE001
            return Response(
                {"error": f"Die Organisation konnte nicht angelegt werden: {error}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "success": True,
                "provider": {"id": provider.id, "name": provider.name},
                "facility": {"id": facility.id, "name": facility.name},
                "department": {"id": department.id, "name": department.name},
                "group": {"id": group.id, "name": group.name} if group else None,
                "employee": {"id": employee.id},
            },
            status=status.HTTP_201_CREATED,
        )
