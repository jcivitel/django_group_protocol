from rest_framework import serializers

from django_grp_backend.models import Protocol, ProtocolItem, Group, Resident


class ProtocolItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProtocolItem
        fields = ["id", "name", "position", "value"]


class ProtocolSerializer(serializers.ModelSerializer):
    items = ProtocolItemSerializer(many=True, required=False)

    class Meta:
        model = Protocol
        fields = ["id", "protocol_date", "group", "items"]

    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        protocol = Protocol.objects.create(**validated_data)

        for item_data in items_data:
            ProtocolItem.objects.create(protocol=protocol, **item_data)

        return protocol

    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", [])

        # Update protocol fields
        instance.protocol_date = validated_data.get(
            "protocol_date", instance.protocol_date
        )
        instance.save()

        # Handle protocol items
        existing_items = {item.id: item for item in instance.items.all()}

        for item_data in items_data:
            item_id = item_data.get("id")
            if item_id and item_id in existing_items:
                # Update existing item
                item = existing_items[item_id]
                item.name = item_data.get("name", item.name)
                item.position = item_data.get("position", item.position)
                item.value = item_data.get("value", item.value)
                item.save()
            else:
                # Create new item
                ProtocolItem.objects.create(protocol=instance, **item_data)

        # Remove items not in the update
        current_item_ids = [item.get("id") for item in items_data if item.get("id")]
        for item in existing_items.values():
            if item.id not in current_item_ids:
                item.delete()

        return instance


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
