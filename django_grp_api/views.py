from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django_grp_backend.models import Protocol, Group, Resident, ProtocolPresence
from .serializers import ProtocolSerializer, GroupSerializer, ResidentSerializer


class ProtocolViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Protocol.objects.all()
    serializer_class = ProtocolSerializer

    def perform_create(self, serializer):
        serializer.save()

    def perform_update(self, serializer):
        serializer.save()


class GroupViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Group.objects.all()
    serializer_class = GroupSerializer


class ResidentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Resident.objects.all()
    serializer_class = ResidentSerializer


class ProtocolPresenceUpdateView(APIView):
    def post(self, request):

        protocol_id = request.data.get("protocol")
        user_id = request.data.get("user")
        was_present = request.data.get("was_present")

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
