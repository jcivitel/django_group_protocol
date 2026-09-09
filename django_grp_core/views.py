"""
Einrichtung und Betriebszustand.

Zwei Endpunkte, mehr nicht: den Zustand abfragen und das erste Konto anlegen.
Die HTML-Vorlagen (setup_wizard.html, info.html) und die Ansichten dazu sind
entfallen - durch die Einrichtung fuehrt der Assistent im Frontend.
"""

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework.authtoken.models import Token

from django_grp_org.personal import personaldatensatz_anlegen

import logging

logger = logging.getLogger("django_grp.core")


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
            any_user_exists = User.objects.exists()

            # Gibt es schon eine Organisation? Ohne Traeger laesst sich
            # weder Personal noch Dienstplan anlegen - dann fuehrt der
            # Assistent durch die Einrichtung.
            from django_grp_org.models import Provider
            from django_grp_backend.models import Group

            organisation_exists = Provider.objects.exists()
            group_exists = Group.objects.exists()
            
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
            elif not organisation_exists:
                status_value = "needs_organisation"
            else:
                status_value = "ready"

            return Response(
                {
                    "is_initialized": superuser_exists and not has_pending,
                    "superuser_exists": superuser_exists,
                    "any_user_exists": any_user_exists,
                    "organisation_exists": organisation_exists,
                    "group_exists": group_exists,
                    "migrations_pending": has_pending,
                    "pending_migrations": pending_migration_names,
                    "status": status_value,
                },
                status=status.HTTP_200_OK
            )
        except Exception as fehler:  # noqa: BLE001
            logger.exception("Zustand der Einrichtung: %s", fehler)
            return Response(
                {"error": "Der Zustand ließ sich nicht ermitteln.", "status": "error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "passwort"

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
            
            # Dieselben Regeln wie ueberall sonst in Django
            # (AUTH_PASSWORD_VALIDATORS) - vorher pruefte dieser Weg nur die
            # Laenge, und das erste Konto der Anwendung war damit das am
            # schwaechsten geschuetzte.
            try:
                validate_password(password)
            except DjangoValidationError as fehler:
                return Response(
                    {"error": " ".join(fehler.messages)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            executor = MigrationExecutor(connection)
            has_pending = bool(
                executor.migration_plan(executor.loader.graph.leaf_nodes())
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
            
            # Migrationen laufen beim Start des Containers (entry.sh), nicht
            # hier. Ein `migrate` aus einem Web-Request heraus haelt die
            # Anfrage minutenlang offen, laeuft ohne Sperre womoeglich
            # mehrfach parallel und braucht Rechte, die eine Web-Anwendung
            # nicht haben sollte (S12).
            if has_pending:
                return Response(
                    {
                        "error": (
                            "Die Datenbank ist nicht auf dem neuesten Stand. "
                            "Bitte zuerst die Migrationen ausführen "
                            "(python manage.py migrate)."
                        )
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            # Create superuser
            #
            # Vor- und Nachname sind optional, werden aber uebernommen: ohne
            # sie zeigt die Anwendung ueberall den Benutzernamen - in der
            # Anwesenheitsliste, im Protokoll, im PDF. Genau das war das
            # "Benutzer #1" aus dem Arbeitsablauf-Test.
            superuser = User.objects.create_superuser(
                username=username,
                email=email,
                password=password,
                first_name=(request.data.get("first_name") or "").strip()[:150],
                last_name=(request.data.get("last_name") or "").strip()[:150],
            )
            
            # Create auth token for the new superuser
            Token.objects.get_or_create(user=superuser)

            # Und den Personaldatensatz dazu. Ein Konto ohne ihn ist ein
            # halbes Konto: kein Foto, kein Dienstplan, keine Zeitbuchung -
            # und auf der Uebersicht nur der Hinweis, dass etwas fehlt.
            # Gibt es noch keinen Traeger, laeuft die Einrichtung weiter;
            # genau dafuer ist der Assistent da.
            personaldatensatz_anlegen(superuser)
            
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
        
        except Exception as fehler:  # noqa: BLE001
            logger.exception("Einrichtung fehlgeschlagen: %s", fehler)
            return Response(
                {"error": "Die Einrichtung ist fehlgeschlagen."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
