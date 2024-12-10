from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from rest_framework import viewsets
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated

from django_grp_backend.models import Protocol
from .serializers import ProtocolSerializer


class ProtocolViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Protocol.objects.all()
    serializer_class = ProtocolSerializer

    def perform_create(self, serializer):
        serializer.save()

    def perform_update(self, serializer):
        serializer.save()
