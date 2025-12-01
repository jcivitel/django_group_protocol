import json
import os

from PIL import Image
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError

from django_grp_backend.models import (
    Protocol,
    Group,
    Resident,
    ProtocolPresence,
    ProtocolItem,
)
from .serializers import (
    ProtocolSerializer,
    GroupSerializer,
    ResidentSerializer,
    ItemSerializer,
)
from django_grp_exporter.func import gen_export


class ProtocolViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ProtocolSerializer

    def get_queryset(self):
        user = self.request.user
        return Protocol.objects.filter(group__group_members=user)

    def perform_create(self, serializer):
        serializer.save()

    def perform_update(self, serializer):
        protocol = self.get_object()
        # Prevent updates if protocol is exported (read-only)
        if protocol.status == "exported":
            raise ValidationError("Exportierte Protokolle können nicht bearbeitet werden.")
        serializer.save()
    
    @action(detail=True, methods=['post'])
    def export(self, request, pk=None):
        """Export protocol to PDF and set status to exported."""
        protocol = self.get_object()
        
        try:
            # Get template if available
            template = protocol.group.pdf_template if protocol.group.pdf_template else None
            
            if template:
                pdf = gen_export(protocol, template)
            else:
                pdf = gen_export(protocol)
            
            # Set protocol status to exported (read-only)
            protocol.status = "exported"
            protocol.exported = True
            protocol.save()
            
            response = HttpResponse(pdf.read(), content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="protokoll_{protocol.protocol_date}.pdf"'
            return response
        except Exception as e:
            return Response(
                {"error": f"PDF generation failed: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )


class GroupViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Group.objects.all()
    serializer_class = GroupSerializer


class ResidentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Resident.objects.all()
    serializer_class = ResidentSerializer


class ProtocolPresenceUpdateView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        protocol_id = request.data.get("protocol")
        user_id = request.data.get("user")
        was_present = request.data.get("was_present")

        # Check if protocol is exported
        try:
            protocol = Protocol.objects.get(id=protocol_id)
            if protocol.status == "exported":
                return Response(
                    {"error": "Exportierte Protokolle können nicht bearbeitet werden."},
                    status=status.HTTP_403_FORBIDDEN,
                )
        except Protocol.DoesNotExist:
            return Response(
                {"error": "Protocol not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        obj, created = ProtocolPresence.objects.update_or_create(
            protocol_id=protocol_id,
            user_id=user_id,
            defaults={"was_present": was_present},
        )

        return Response(
            {
                "message": "Presence updated" if not created else "Presence created",
                "created": created,
            },
            status=status.HTTP_200_OK,
        )


class ItemValuesUpdateView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        serializer = ItemSerializer(data=request.data)
        if serializer.is_valid():
            item_id = request.data.get("item_id")
            name = serializer.data.get("name")
            protocol_id = serializer.data.get("protocol")
            value = serializer.data.get("value")
            position = serializer.data.get("position")
            
            # Check if protocol is exported
            try:
                protocol = Protocol.objects.get(id=protocol_id)
                if protocol.status == "exported":
                    return Response(
                        {"error": "Exportierte Protokolle können nicht bearbeitet werden."},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            except Protocol.DoesNotExist:
                return Response(
                    {"error": "Protocol not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            
            if item_id == "":
                item_id = None

            ProtocolItem.objects.update_or_create(
                id=item_id,
                defaults={
                    "protocol_id": protocol_id,
                    "name": name,
                    "value": value,
                    "position": position,
                },
            )
            return Response(
                {"message": "Item updated"},
                status=status.HTTP_200_OK,
            )
        return Response(
            data="message: serializer.errors", status=status.HTTP_400_BAD_REQUEST
        )

    def delete(self, request):
        try:
            item = ProtocolItem.objects.get(id=request.data.get("item_id"))
            
            # Check if protocol is exported
            if item.protocol.status == "exported":
                return Response(
                    {"error": "Exportierte Protokolle können nicht bearbeitet werden."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            
            item.delete()
            return Response(
                {"message": "Item deleted"},
                status=status.HTTP_200_OK,
            )
        except ProtocolItem.DoesNotExist:
            return Response(
                data={"message": "Item not found"}, status=status.HTTP_404_NOT_FOUND
            )


class MentionAutocompleteView(APIView):
    """Get list of residents for @mention autocomplete."""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        protocol_id = request.query_params.get('protocol_id')
        if not protocol_id:
            return Response(
                {"error": "protocol_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            protocol = Protocol.objects.get(id=protocol_id)
            residents = Resident.objects.filter(group=protocol.group, moved_out_since__isnull=True)
            
            data = [
                {
                    "id": resident.id,
                    "name": resident.get_full_name(),
                    "mention": resident.get_full_name().replace(" ", "_"),
                }
                for resident in residents
            ]
            
            return Response(data, status=status.HTTP_200_OK)
        except Protocol.DoesNotExist:
            return Response(
                {"error": "Protocol not found"},
                status=status.HTTP_404_NOT_FOUND
            )


@csrf_exempt
def rotate_image(request):
    if request.method == "POST":
        data = json.loads(request.body)
        direction = data.get("direction")
        image_url = data.get("image_url")

        image_path = os.path.join(
            settings.MEDIA_ROOT, os.path.relpath(image_url, settings.MEDIA_URL)
        )
        if not os.path.exists(image_path):
            return JsonResponse(
                {"success": False, "error": "Image not found"}, status=404
            )

        try:
            with Image.open(image_path) as img:
                if direction == "left":
                    img = img.rotate(90, expand=True)
                elif direction == "right":
                    img = img.rotate(-90, expand=True)
                else:
                    return JsonResponse(
                        {"success": False, "error": "Invalid direction"}, status=400
                    )
                img.save(image_path)

            new_image_url = f"{settings.MEDIA_URL}{os.path.relpath(image_path, settings.MEDIA_ROOT)}"
            return JsonResponse({"success": True, "new_image_url": new_image_url})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=500)

    return JsonResponse(
        {"success": False, "error": "Invalid request method"}, status=405
    )
