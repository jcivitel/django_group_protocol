from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpResponse
from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core.management import call_command
from rest_framework.authtoken.models import Token


class SetupStatusView(APIView):
    """
    Check system initialization status.
    
    GET /setup/status/
    
    Returns:
    {
        "is_initialized": boolean,
        "superuser_exists": boolean,
        "migrations_pending": boolean,
        "pending_migrations": ["app.migration_name", ...],
        "status": "not_initialized|needs_migration|ready"
    }
    
    Access Control:
    - Public (no authentication required)
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        """Check setup status."""
        try:
            # Check if superuser exists
            superuser_exists = User.objects.filter(is_superuser=True).exists()
            
            # Check for pending migrations
            executor = MigrationExecutor(connection)
            pending_migrations = executor.migration_plan(executor.loader.graph.leaf_nodes())
            has_pending = len(pending_migrations) > 0
            
            pending_migration_names = [
                f"{migration[0].app_label}.{migration[0].name}"
                for migration in pending_migrations
            ]
            
            # Determine status
            if not superuser_exists:
                status_value = "not_initialized"
            elif has_pending:
                status_value = "needs_migration"
            else:
                status_value = "ready"
            
            return Response(
                {
                    "is_initialized": superuser_exists and not has_pending,
                    "superuser_exists": superuser_exists,
                    "migrations_pending": has_pending,
                    "pending_migrations": pending_migration_names,
                    "status": status_value,
                },
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"error": str(e), "status": "error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SetupWizardView(APIView):
    """
    Initialize system: create superuser and run pending migrations.
    
    POST /setup/init/
    {
        "username": "string",
        "email": "string",
        "password": "string",
        "password_confirm": "string"
    }
    
    Returns:
    {
        "success": true,
        "message": "System initialized successfully",
        "user": {
            "id": int,
            "username": "string",
            "email": "string",
            "is_staff": boolean,
            "is_superuser": boolean
        }
    }
    
    Access Control:
    - Public (no authentication required), but only works if no superuser exists
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        """Create superuser and run migrations."""
        try:
            # Check if superuser already exists
            if User.objects.filter(is_superuser=True).exists():
                return Response(
                    {"error": "System already initialized. Superuser already exists."},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Get request data
            username = request.data.get('username', '').strip()
            email = request.data.get('email', '').strip()
            password = request.data.get('password', '')
            password_confirm = request.data.get('password_confirm', '')
            
            # Validation
            if not username or not email or not password:
                return Response(
                    {"error": "Username, email, and password are required."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if password != password_confirm:
                return Response(
                    {"error": "Passwords do not match."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if len(password) < 8:
                return Response(
                    {"error": "Password must be at least 8 characters long."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if User.objects.filter(username=username).exists():
                return Response(
                    {"error": f"Username '{username}' already exists."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if User.objects.filter(email=email).exists():
                return Response(
                    {"error": f"Email '{email}' already exists."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Run pending migrations first
            try:
                call_command('migrate', verbosity=0)
            except Exception as e:
                return Response(
                    {"error": f"Migration failed: {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # Create superuser
            superuser = User.objects.create_superuser(
                username=username,
                email=email,
                password=password
            )
            
            # Create auth token for the new superuser
            Token.objects.get_or_create(user=superuser)
            
            return Response(
                {
                    "success": True,
                    "message": "System initialized successfully. Superuser created and migrations applied.",
                    "user": {
                        "id": superuser.id,
                        "username": superuser.username,
                        "email": superuser.email,
                        "is_staff": superuser.is_staff,
                        "is_superuser": superuser.is_superuser,
                    }
                },
                status=status.HTTP_201_CREATED
            )
        
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SetupRedirectView(TemplateView):
    """
    Redirect or display setup page based on initialization status.
    
    GET /
    
    - If system not initialized: Display setup wizard form
    - If system initialized: Display info page
    
    Access Control:
    - Public (no authentication required)
    """
    permission_classes = [AllowAny]
    template_name = 'setup.html'
    
    def get(self, request, *args, **kwargs):
        """Determine which template to show based on status."""
        try:
            # Check if superuser exists
            superuser_exists = User.objects.filter(is_superuser=True).exists()
            
            # Check for pending migrations
            executor = MigrationExecutor(connection)
            pending_migrations = executor.migration_plan(executor.loader.graph.leaf_nodes())
            has_pending = len(pending_migrations) > 0
            
            # Determine which template to render
            if not superuser_exists or has_pending:
                self.template_name = 'setup_wizard.html'
            else:
                self.template_name = 'info.html'
            
            # Pass context data
            context = self.get_context_data(**kwargs)
            context['superuser_exists'] = superuser_exists
            context['migrations_pending'] = has_pending
            context['api_url'] = request.build_absolute_uri('/api/')
            
            return super().render_to_response(context)
        
        except Exception as e:
            return HttpResponse(f"<h1>Error</h1><p>{str(e)}</p>", status=500)


class InfoView(TemplateView):
    """
    Display system information and API documentation.
    
    GET /info/
    
    Shows system status, available endpoints, and links to documentation.
    
    Access Control:
    - Public (no authentication required)
    """
    permission_classes = [AllowAny]
    template_name = 'info.html'
    
    def get_context_data(self, **kwargs):
        """Add context data for the template."""
        context = super().get_context_data(**kwargs)
        context['api_url'] = self.request.build_absolute_uri('/api/')
        context['admin_url'] = self.request.build_absolute_uri('/admin/')
        try:
            context['superuser_exists'] = User.objects.filter(is_superuser=True).exists()
            executor = MigrationExecutor(connection)
            pending_migrations = executor.migration_plan(executor.loader.graph.leaf_nodes())
            context['migrations_pending'] = len(pending_migrations) > 0
        except Exception:
            context['superuser_exists'] = True
            context['migrations_pending'] = False
        return context
