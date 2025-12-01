from rest_framework import serializers

from django_grp_backend.models import (
    Protocol,
    ProtocolItem,
    Group,
    Resident,
)


class ProtocolItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProtocolItem
        fields = ["id", "name", "position", "value"]


class ProtocolSerializer(serializers.ModelSerializer):
    items = ProtocolItemSerializer(many=True, required=False)

    class Meta:
        model = Protocol
        fields = ["id", "protocol_date", "group", "items", "exported", "status"]


class GroupSerializer(serializers.ModelSerializer):
    members = serializers.SerializerMethodField(source="get_members", read_only=True)

    class Meta:
        model = Group
        fields = ["id", "name", "address", "postalcode", "city", "members"]

    def get_members(self, obj):
        residents = Resident.objects.filter(group=obj.id)

        return ResidentSerializer(residents, many=True).data


class ResidentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Resident
        fields = [
            "id",
            "first_name",
            "last_name",
            "moved_in_since",
            "moved_in_since",
            "group",
        ]


class ItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProtocolItem
        fields = ["id", "protocol", "name", "position", "value"]
