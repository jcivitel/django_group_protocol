from rest_framework import serializers
from django.contrib.auth.models import User

from django_grp_backend.models import (
    Protocol,
    ProtocolItem,
    ProtocolTodo,
    Group,
    Resident,
    ProtocolPresence,
    UserPermission,
)


class ProtocolItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProtocolItem
        fields = ["id", "name", "position", "value"]


class ProtocolTodoSerializer(serializers.ModelSerializer):
    """Serializer for ProtocolTodo model."""
    
    class Meta:
        model = ProtocolTodo
        fields = ["id", "protocol", "was", "wer", "wann", "position", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at", "protocol"]


class ProtocolSerializer(serializers.ModelSerializer):
    items = ProtocolItemSerializer(many=True, required=False)
    exported_file = serializers.SerializerMethodField()

    class Meta:
        model = Protocol
        fields = ["id", "protocol_date", "group", "items", "exported", "status", "exported_file"]
    
    def to_representation(self, instance):
        """Override to handle both real and demo objects."""
        # Ensure pk is set for serialization
        if not hasattr(instance, '_state'):
            # Demo object - add minimal _state to make it compatible
            instance._state = type('State', (), {'db': None})()
        
        return super().to_representation(instance)
    
    def get_exported_file(self, obj):
        """Return full URL for exported file if available."""
        try:
            if obj.exported_file:
                request = self.context.get("request")
                if request:
                    return request.build_absolute_uri(obj.exported_file.url)
                return obj.exported_file.url
        except (AttributeError, TypeError):
            pass
        return None


class ProtocolSummarySerializer(serializers.ModelSerializer):
    """Serializer for protocol summary without items (list view)."""

    class Meta:
        model = Protocol
        fields = ["id", "protocol_date", "group", "exported", "status"]
    
    def get_group_name(self, obj):
        """Get group name from the related group object."""
        try:
            return obj.group.name if obj.group else None
        except (AttributeError, TypeError):
            return None


class GroupSerializer(serializers.ModelSerializer):
    members = serializers.SerializerMethodField(source="get_members", read_only=True)

    class Meta:
        model = Group
        fields = ["id", "name", "address", "postalcode", "city", "members", "pdf_template", "color"]
    
    def to_representation(self, instance):
        """Override to handle both real and demo objects."""
        # Ensure pk is set for serialization
        if not hasattr(instance, '_state'):
            # Demo object - add minimal _state to make it compatible
            instance._state = type('State', (), {'db': None})()
        
        return super().to_representation(instance)

    def get_members(self, obj):
        """Get residents in this group."""
        try:
            residents = Resident.objects.filter(group=obj.id)
            return ResidentSerializer(residents, many=True, context=self.context).data
        except (AttributeError, TypeError):
            # If it fails, return empty list
            return []
    
    def update(self, instance, validated_data):
        """
        Update group with only non-null fields.
        Null fields remain unchanged.
        """
        # Only update fields that are present in the request
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


class ResidentSerializer(serializers.ModelSerializer):
    picture = serializers.SerializerMethodField()

    class Meta:
        model = Resident
        fields = [
            "id",
            "first_name",
            "last_name",
            "moved_in_since",
            "moved_out_since",
            "group",
            "picture",
        ]
    
    def to_representation(self, instance):
        """Override to handle both real and demo objects."""
        # Ensure pk is set for serialization
        if not hasattr(instance, '_state'):
            # Demo object - add minimal _state to make it compatible
            instance._state = type('State', (), {'db': None})()
        
        return super().to_representation(instance)

    def get_picture(self, obj):
        """Return full URL for resident picture if available."""
        try:
            if obj.picture:
                request = self.context.get("request")
                if request:
                    return request.build_absolute_uri(obj.picture.url)
                return obj.picture.url
        except (AttributeError, TypeError):
            pass
        return None


class ItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProtocolItem
        fields = ["id", "protocol", "name", "position", "value"]


class UserProfileSerializer(serializers.ModelSerializer):
    """Serializer for authenticated user's profile information."""
    groups = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_superuser",
            "date_joined",
            "groups",
        ]
        read_only_fields = [
            "id",
            "username",
            "date_joined",
            "is_staff",
            "is_superuser",
        ]

    def get_groups(self, obj):
        """Get groups the user is member of."""
        return [group.name for group in Group.objects.filter(group_members=obj)]


class UserGroupPermissionSerializer(serializers.ModelSerializer):
    """Serializer for group with user permissions."""
    permissions = serializers.SerializerMethodField()
    resident_count = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = ["id", "name", "address", "postalcode", "city", "permissions", "resident_count"]

    def get_permissions(self, obj):
        """Get user permissions for this group."""
        request = self.context.get("request")
        if not request:
            return {}
        
        user = request.user
        is_member = obj.group_members.filter(id=user.id).exists()
        is_staff = user.is_staff
        
        return {
            "is_member": is_member,
            "is_staff": is_staff,
            "can_view": is_member or is_staff,
            "can_edit": is_member or is_staff,
            "can_delete": is_staff,
        }
    
    def get_resident_count(self, obj):
        """Get number of residents in this group."""
        return obj.resident_set.count()


class UserDetailedProfileSerializer(serializers.ModelSerializer):
    """Serializer for detailed authenticated user profile with group permissions."""
    groups_with_permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_superuser",
            "date_joined",
            "groups_with_permissions",
        ]
        read_only_fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "date_joined",
            "is_staff",
            "is_superuser",
        ]

    def get_groups_with_permissions(self, obj):
        """Get all accessible groups with permissions."""
        groups = Group.objects.for_user(obj)
        serializer = UserGroupPermissionSerializer(
            groups,
            many=True,
            context={"request": self.context.get("request")}
        )
        return serializer.data


class ProtocolPresenceSerializer(serializers.ModelSerializer):
    """Serializer for ProtocolPresence model."""
    user_name = serializers.SerializerMethodField()
    
    class Meta:
        model = ProtocolPresence
        fields = ["id", "protocol", "user", "user_name", "was_present"]
    
    def get_user_name(self, obj):
        """Get full name of the user."""
        return f"{obj.user.first_name} {obj.user.last_name}"


class GroupPDFTemplateSerializer(serializers.ModelSerializer):
    """Serializer for updating Group PDF template."""
    
    class Meta:
        model = Group
        fields = ["id", "name", "pdf_template"]
        read_only_fields = ["id", "name"]


class UserPermissionSerializer(serializers.ModelSerializer):
    """Serializer for user permissions on specific resources."""
    resource_display = serializers.CharField(source="get_resource_display", read_only=True)
    permission_display = serializers.CharField(source="get_permission_display", read_only=True)
    
    class Meta:
        model = UserPermission
        fields = ["id", "user", "group", "resource", "resource_display", "permission", "permission_display", "created_at"]
        read_only_fields = ["id", "created_at"]


class UserDetailSerializer(serializers.ModelSerializer):
    """Serializer for detailed user information with permissions."""
    groups = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_superuser",
            "is_active",
            "date_joined",
            "groups",
            "permissions",
        ]
        read_only_fields = [
            "id",
            "is_staff",
            "is_superuser",
            "date_joined",
        ]
    
    def get_groups(self, obj):
        """Get groups the user is member of."""
        return [{"id": group.id, "name": group.name} for group in Group.objects.filter(group_members=obj)]
    
    def get_permissions(self, obj):
        """Get all permissions for this user."""
        perms = UserPermission.objects.filter(user=obj)
        return UserPermissionSerializer(perms, many=True).data


class UserStaffSerializer(serializers.ModelSerializer):
    """Serializer for staff users listing."""
    groups = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_superuser",
            "date_joined",
            "groups",
        ]
        read_only_fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_superuser",
            "date_joined",
        ]
    
    def get_groups(self, obj):
        """Get groups the user is member of."""
        return [group.name for group in Group.objects.filter(group_members=obj)]
