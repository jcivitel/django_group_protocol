import os

from PIL import Image
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from rest_framework import viewsets, status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError

from django_grp_backend.models import (
    Protocol,
    Group,
    Resident,
    ProtocolPresence,
    ProtocolItem,
    ProtocolTodo,
    UserPermission,
)
from .serializers import (
    ProtocolSerializer,
    ProtocolSummarySerializer,
    GroupSerializer,
    ResidentSerializer,
    ItemSerializer,
    ProtocolTodoSerializer,
    UserProfileSerializer,
    UserDetailedProfileSerializer,
    ProtocolPresenceSerializer,
    GroupPDFTemplateSerializer,
    UserStaffSerializer,
    UserDetailSerializer,
    UserPermissionSerializer,
)



class LoginView(APIView):
    """
    Token-based login endpoint for Flutter and other clients.
    
    POST /api/v1/auth/login/
    {
        "username": "string",
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
    
    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        
        if not username or not password:
            return Response(
                {
                    "success": False,
                    "error": "Username and password are required"
                },
                status=status.HTTP_400_BAD_REQUEST
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
                        }
                    }
                },
                status=status.HTTP_200_OK
            )
        else:
            return Response(
                {
                    "success": False,
                    "error": "Invalid username or password"
                },
                status=status.HTTP_401_UNAUTHORIZED
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
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        # Delete the user's authentication token
        try:
            request.user.auth_token.delete()
        except Token.DoesNotExist:
            pass
        
        return Response(
            {
                "success": True,
                "message": "Logged out successfully"
            },
            status=status.HTTP_200_OK
        )


class ProtocolViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ProtocolSummarySerializer

    def get_queryset(self):
        """Filter protocols by user group membership or staff status."""
        user = self.request.user
        return Protocol.objects.for_user(user)

    def perform_create(self, serializer):
        serializer.save()

    def perform_update(self, serializer):
        protocol = self.get_object()
        # Prevent updates if protocol is exported (read-only)
        if protocol.status == "exported":
            raise ValidationError("Exportierte Protokolle können nicht bearbeitet werden.")
        serializer.save()


class GroupViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = GroupSerializer
    
    def get_queryset(self):
        """Filter groups by user membership or staff status."""
        user = self.request.user
        return Group.objects.for_user(user)
    
    def get_serializer(self, *args, **kwargs):
        """
        Enable partial updates for PUT requests.
        Only provide fields that are not None.
        """
        if self.request.method in ['PUT', 'PATCH']:
            kwargs['partial'] = True
        return super().get_serializer(*args, **kwargs)
    
    def perform_update(self, serializer: GroupSerializer) -> None:
        """
        Update group with partial data.
        Only non-null fields are updated; null fields remain unchanged.
        """
        serializer.save()


class ResidentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ResidentSerializer
    
    def get_queryset(self):
        """Filter residents by user group membership or staff status."""
        user = self.request.user
        return Resident.objects.for_user(user)




class ProtocolTodoViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing protocol todos.
    
    Nested under /api/v1/protocol/{protocol_id}/todo/
    
    Supports:
    - GET /api/v1/protocol/{protocol_id}/todo/ - List todos for protocol
    - POST /api/v1/protocol/{protocol_id}/todo/ - Create new todo
    - PUT /api/v1/protocol/{protocol_id}/todo/{id}/ - Update todo
    - DELETE /api/v1/protocol/{protocol_id}/todo/{id}/ - Delete todo
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ProtocolTodoSerializer
    
    def get_queryset(self):
        """Filter todos by protocol_id from URL parameter."""
        protocol_id = self.kwargs.get('protocol_id')
        user = self.request.user
        
        # Get the protocol and check access
        try:
            protocol = Protocol.objects.get(id=protocol_id)
            # Check if user has access to this protocol
            is_member = protocol.group.group_members.filter(id=user.id).exists()
            if not is_member and not user.is_staff:
                return ProtocolTodo.objects.none()
            
            return ProtocolTodo.objects.filter(protocol_id=protocol_id)
        except Protocol.DoesNotExist:
            return ProtocolTodo.objects.none()
    
    def perform_create(self, serializer):
        """Create todo and automatically set protocol from URL."""
        protocol_id = self.kwargs.get('protocol_id')
        
        # Verify protocol exists and user has access
        try:
            protocol = Protocol.objects.get(id=protocol_id)
            is_member = protocol.group.group_members.filter(id=self.request.user.id).exists()
            if not is_member and not self.request.user.is_staff:
                raise ValidationError("Sie haben keine Berechtigung fuer dieses Protokoll.")
            
            # Check if protocol is exported (read-only)
            if protocol.status == "exported":
                raise ValidationError("Exportierte Protokolle koennen nicht bearbeitet werden.")
            
            serializer.save(protocol_id=protocol_id)
        except Protocol.DoesNotExist:
            raise ValidationError("Protokoll nicht gefunden.")
    
    def perform_update(self, serializer):
        """Update todo with validation."""
        protocol_id = self.kwargs.get('protocol_id')
        
        # Verify protocol exists and user has access
        try:
            protocol = Protocol.objects.get(id=protocol_id)
            is_member = protocol.group.group_members.filter(id=self.request.user.id).exists()
            if not is_member and not self.request.user.is_staff:
                raise ValidationError("Sie haben keine Berechtigung fuer dieses Protokoll.")
            
            # Check if protocol is exported (read-only)
            if protocol.status == "exported":
                raise ValidationError("Exportierte Protokolle koennen nicht bearbeitet werden.")
            
            serializer.save()
        except Protocol.DoesNotExist:
            raise ValidationError("Protokoll nicht gefunden.")
    
    def perform_destroy(self, instance):
        """Delete todo with validation."""
        protocol = instance.protocol
        
        # Check if protocol is exported (read-only)
        if protocol.status == "exported":
            raise ValidationError("Exportierte Protokolle koennen nicht bearbeitet werden.")
        
        instance.delete()

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
            
            # Check access: user must be staff or member of protocol's group
            is_member = protocol.group.group_members.filter(id=request.user.id).exists()
            if not is_member and not request.user.is_staff:
                return Response(
                    {"error": "You do not have permission to access this protocol"},
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
                
                # Check access: user must be staff or member of protocol's group
                is_member = protocol.group.group_members.filter(id=request.user.id).exists()
                if not is_member and not request.user.is_staff:
                    return Response(
                        {"error": "You do not have permission to access this protocol"},
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
            
            # Check access: user must be staff or member of protocol's group
            is_member = item.protocol.group.group_members.filter(id=request.user.id).exists()
            if not is_member and not request.user.is_staff:
                return Response(
                    {"error": "You do not have permission to access this protocol"},
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
            
            # Check access: user must be staff or member of protocol's group
            is_member = protocol.group.group_members.filter(id=request.user.id).exists()
            if not is_member and not request.user.is_staff:
                return Response(
                    {"error": "You do not have permission to access this protocol"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            
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


class RotateImageView(APIView):
    """Rotate resident images (left/right)."""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            data = request.data
            direction = data.get("direction")
            image_url = data.get("image_url")

            if not direction or not image_url:
                return Response(
                    {"success": False, "error": "direction and image_url are required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            image_path = os.path.join(
                settings.MEDIA_ROOT, os.path.relpath(image_url, settings.MEDIA_URL)
            )
            if not os.path.exists(image_path):
                return Response(
                    {"success": False, "error": "Image not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

            with Image.open(image_path) as img:
                if direction == "left":
                    img = img.rotate(90, expand=True)
                elif direction == "right":
                    img = img.rotate(-90, expand=True)
                else:
                    return Response(
                        {"success": False, "error": "Invalid direction"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                img.save(image_path)

            new_image_url = f"{settings.MEDIA_URL}{os.path.relpath(image_path, settings.MEDIA_ROOT)}"
            return Response(
                {"success": True, "new_image_url": new_image_url},
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
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
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        serializer = UserProfileSerializer(request.user, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def put(self, request):
        """Update user profile (email, first_name, last_name)."""
        serializer = UserProfileSerializer(
            request.user,
            data=request.data,
            partial=True,
            context={"request": request}
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
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get detailed user profile with group permissions and resident counts."""
        serializer = UserDetailedProfileSerializer(request.user, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class ResidentPictureView(APIView):
    """
    Get resident picture by resident ID.
    
    GET /api/v1/resident/{id}/picture/
    
    Returns: Image file or 404 if not found/no picture
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, resident_id: int):
        try:
            resident = Resident.objects.for_user(request.user).get(id=resident_id)
            
            if not resident.picture:
                return Response(
                    {"error": "Resident has no picture"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            return Response(
                {
                    "id": resident.id,
                    "name": resident.get_full_name(),
                    "picture_url": request.build_absolute_uri(resident.picture.url),
                },
                status=status.HTTP_200_OK
            )
        except Resident.DoesNotExist:
            return Response(
                {"error": "Resident not found"},
                status=status.HTTP_404_NOT_FOUND
            )


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
    permission_classes = [IsAuthenticated]
    
    def post(self, request, group_id: int):
        try:
            # Get group
            try:
                group = Group.objects.get(id=group_id)
            except Group.DoesNotExist:
                return Response(
                    {"error": "Group not found"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Check access: user must be staff or member of group
            is_member = group.group_members.filter(id=request.user.id).exists()
            if not is_member and not request.user.is_staff:
                return Response(
                    {"error": "You do not have permission to update this group's PDF template"},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Check if PDF file is provided
            if "pdf_template" not in request.FILES:
                return Response(
                    {"error": "PDF file is required"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            pdf_file = request.FILES["pdf_template"]
            
            # Validate file type
            if not pdf_file.name.lower().endswith(".pdf"):
                return Response(
                    {"error": "Only PDF files are allowed"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Update group with new template
            group.pdf_template = pdf_file
            group.save()
            
            return Response(
                {
                    "success": True,
                    "message": "PDF template updated",
                    "group_id": group.id,
                    "template_url": request.build_absolute_uri(group.pdf_template.url) if group.pdf_template else None,
                },
                status=status.HTTP_200_OK
            )
        
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ProtocolExportedFileView(APIView):
    """
    Get or upload exported protocol file.
    
    GET /api/v1/protocol/{id}/exported_file/
    - Download the exported file (if available)
    
    POST /api/v1/protocol/{id}/exported_file/
    - Upload exported file (automatically sets exported=true and status='exported')
    
    Request (multipart/form-data):
    - exported_file: File
    
    Access Control:
    - User must be staff OR member of protocol's group.group_members
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, protocol_id: int):
        """Get exported file for a protocol."""
        try:
            protocol = Protocol.objects.get(id=protocol_id)
        except Protocol.DoesNotExist:
            return Response(
                {"error": "Protocol not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check access: user must be staff or member of protocol's group
        is_member = protocol.group.group_members.filter(id=request.user.id).exists()
        if not is_member and not request.user.is_staff:
            return Response(
                {"error": "You do not have permission to view this protocol's exported file"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if not protocol.exported_file:
            return Response(
                {"error": "No exported file available for this protocol"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response(
            {
                "id": protocol.id,
                "protocol_date": protocol.protocol_date,
                "exported": protocol.exported,
                "file_url": request.build_absolute_uri(protocol.exported_file.url),
                "file_name": protocol.exported_file.name.split('/')[-1],
            },
            status=status.HTTP_200_OK
        )
    
    def post(self, request, protocol_id: int):
        """Upload exported file. Automatically sets exported=true and status='exported'."""
        try:
            protocol = Protocol.objects.get(id=protocol_id)
        except Protocol.DoesNotExist:
            return Response(
                {"error": "Protocol not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check access: user must be staff or member of protocol's group
        is_member = protocol.group.group_members.filter(id=request.user.id).exists()
        if not is_member and not request.user.is_staff:
            return Response(
                {"error": "You do not have permission to upload files for this protocol"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if file is provided
        if "exported_file" not in request.FILES:
            return Response(
                {"error": "exported_file is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            exported_file = request.FILES["exported_file"]
            protocol.exported_file = exported_file
            # Automatically set exported=true and status='exported' when file is uploaded
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
                    "file_name": protocol.exported_file.name.split('/')[-1],
                },
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ProtocolPresenceListView(APIView):
    """
    List all presence entries for a protocol.
    
    GET /api/v1/protocol/{id}/presence/
    
    Returns:
    [
        {
            "id": int,
            "protocol": int,
            "user": int,
            "user_name": "string",
            "was_present": boolean
        }
    ]
    
    Access Control:
    - User must be staff OR member of protocol's group.group_members
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, protocol_id: int):
        try:
            # Get protocol for authenticated users
            try:
                protocol = Protocol.objects.get(id=protocol_id)
            except Protocol.DoesNotExist:
                return Response(
                    {"error": "Protocol not found"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Check access: user must be staff or member of protocol's group
            is_member = protocol.group.group_members.filter(id=request.user.id).exists()
            if not is_member and not request.user.is_staff:
                return Response(
                    {"error": "You do not have permission to view this protocol's presence entries"},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Get all presence entries for this protocol
            presence_entries = ProtocolPresence.objects.filter(protocol=protocol)
            serializer = ProtocolPresenceSerializer(presence_entries, many=True)
            
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


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
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """List all users (staff only)."""
        if not request.user.is_staff:
            return Response(
                {"error": "Sie haben keine Berechtigung, um diese Seite zu sehen."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            users = User.objects.all().order_by('first_name', 'last_name')
            serializer = UserDetailSerializer(users, many=True, context={"request": request})
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def post(self, request):
        """Create a new user (staff only)."""
        if not request.user.is_staff:
            return Response(
                {"error": "Sie haben keine Berechtigung, um diese Aktion durchzuführen."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            username = request.data.get('username')
            email = request.data.get('email')
            first_name = request.data.get('first_name', '')
            last_name = request.data.get('last_name', '')
            password = request.data.get('password')
            is_staff = request.data.get('is_staff', False)
            
            # Validation
            if not username or not password:
                return Response(
                    {"error": "Username und Passwort sind erforderlich."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if User.objects.filter(username=username).exists():
                return Response(
                    {"error": f"Benutzer '{username}' existiert bereits."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Create user
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                is_staff=is_staff
            )
            
            serializer = UserDetailSerializer(user, context={"request": request})
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminUserDetailView(APIView):
    """
    Admin: Get, update, or delete a specific user.
    
    GET/PUT/DELETE /api/v1/admin/users/{user_id}/
    
    Access Control:
    - Staff only (is_staff == true)
    """
    permission_classes = [IsAuthenticated]
    
    def _get_user_or_404(self, user_id: int):
        """Helper to get user or return 404."""
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None
    
    def get(self, request, user_id: int):
        """Get user details (staff only)."""
        if not request.user.is_staff:
            return Response(
                {"error": "Sie haben keine Berechtigung."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        user = self._get_user_or_404(user_id)
        if not user:
            return Response(
                {"error": "Benutzer nicht gefunden."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = UserDetailSerializer(user, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def put(self, request, user_id: int):
        """Update user details (staff only)."""
        if not request.user.is_staff:
            return Response(
                {"error": "Sie haben keine Berechtigung."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        user = self._get_user_or_404(user_id)
        if not user:
            return Response(
                {"error": "Benutzer nicht gefunden."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            # Update allowed fields
            if 'email' in request.data:
                user.email = request.data['email']
            if 'first_name' in request.data:
                user.first_name = request.data['first_name']
            if 'last_name' in request.data:
                user.last_name = request.data['last_name']
            if 'is_active' in request.data:
                user.is_active = request.data['is_active']
            if 'password' in request.data and request.data['password']:
                user.set_password(request.data['password'])
            
            user.save()
            serializer = UserDetailSerializer(user, context={"request": request})
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def delete(self, request, user_id: int):
        """Delete user (staff only)."""
        if not request.user.is_staff:
            return Response(
                {"error": "Sie haben keine Berechtigung."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        user = self._get_user_or_404(user_id)
        if not user:
            return Response(
                {"error": "Benutzer nicht gefunden."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            user.delete()
            return Response(
                {"message": "Benutzer erfolgreich gelöscht."},
                status=status.HTTP_204_NO_CONTENT
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


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
    permission_classes = [IsAuthenticated]
    
    def post(self, request, user_id: int):
        """Add user to group (staff only)."""
        if not request.user.is_staff:
            return Response(
                {"error": "Sie haben keine Berechtigung."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"error": "Benutzer nicht gefunden."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        group_id = request.data.get('group_id')
        if not group_id:
            return Response(
                {"error": "group_id ist erforderlich."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            group = Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            return Response(
                {"error": "Gruppe nicht gefunden."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            group.group_members.add(user)
            serializer = UserDetailSerializer(user, context={"request": request})
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def delete(self, request, user_id: int, group_id: int):
        """Remove user from group (staff only)."""
        if not request.user.is_staff:
            return Response(
                {"error": "Sie haben keine Berechtigung."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"error": "Benutzer nicht gefunden."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            group = Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            return Response(
                {"error": "Gruppe nicht gefunden."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            group.group_members.remove(user)
            serializer = UserDetailSerializer(user, context={"request": request})
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminUserPermissionView(APIView):
    """
    Admin: Manage user resource permissions (read, write, delete).
    
    GET /api/v1/admin/users/{user_id}/permissions/
    - List all permissions for user
    
    POST /api/v1/admin/users/{user_id}/permissions/
    - Add permission to user
    
    DELETE /api/v1/admin/users/{user_id}/permissions/{permission_id}/
    - Remove permission from user
    
    Permission Request Format:
    {
        "group_id": int,
        "resource": "resident|protocol|group",
        "permission": "read|write|delete"
    }
    
    Access Control:
    - Staff only (is_staff == true)
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, user_id: int):
        """List user permissions (staff only)."""
        if not request.user.is_staff:
            return Response(
                {"error": "Sie haben keine Berechtigung."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"error": "Benutzer nicht gefunden."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            permissions = UserPermission.objects.filter(user=user)
            serializer = UserPermissionSerializer(permissions, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def post(self, request, user_id: int):
        """Add permission to user (staff only)."""
        if not request.user.is_staff:
            return Response(
                {"error": "Sie haben keine Berechtigung."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"error": "Benutzer nicht gefunden."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        group_id = request.data.get('group_id')
        resource = request.data.get('resource')
        permission = request.data.get('permission')
        
        if not group_id or not resource or not permission:
            return Response(
                {"error": "group_id, resource und permission sind erforderlich."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate resource and permission
        valid_resources = ['resident', 'protocol', 'group']
        valid_permissions = ['read', 'write', 'delete']
        
        if resource not in valid_resources:
            return Response(
                {"error": f"Ungültige Ressource. Gültig: {', '.join(valid_resources)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if permission not in valid_permissions:
            return Response(
                {"error": f"Ungültige Berechtigung. Gültig: {', '.join(valid_permissions)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            group = Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            return Response(
                {"error": "Gruppe nicht gefunden."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            perm, created = UserPermission.objects.get_or_create(
                user=user,
                group=group,
                resource=resource,
                permission=permission
            )
            
            serializer = UserPermissionSerializer(perm)
            status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            return Response(serializer.data, status=status_code)
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def delete(self, request, user_id: int, permission_id: int):
        """Remove permission from user (staff only)."""
        if not request.user.is_staff:
            return Response(
                {"error": "Sie haben keine Berechtigung."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"error": "Benutzer nicht gefunden."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            permission_obj = UserPermission.objects.get(id=permission_id, user=user)
        except UserPermission.DoesNotExist:
            return Response(
                {"error": "Berechtigung nicht gefunden."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            permission_obj.delete()
            return Response(
                {"message": "Berechtigung erfolgreich gelöscht."},
                status=status.HTTP_204_NO_CONTENT
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
