"""
Anmeldung über LDAP/Active Directory und OpenID Connect (Roadmap Phase 0).

Beide Wege sind über Umgebungsvariablen konfigurierbar und bleiben ohne
Konfiguration wirkungslos - die bestehende Anmeldung mit Benutzername und
Passwort funktioniert unverändert weiter.

LDAP
    LDAP_SERVER=ldap://dc.traeger.local
    LDAP_USER_DN_TEMPLATE={username}@traeger.local     (oder ein voller DN)
    LDAP_SEARCH_BASE=OU=Mitarbeitende,DC=traeger,DC=local
    LDAP_BIND_DN / LDAP_BIND_PASSWORD                  (optional, für die Suche)
    LDAP_STAFF_GROUP=CN=Leitung,OU=Gruppen,DC=traeger,DC=local

OpenID Connect
    OIDC_ISSUER=https://sso.traeger.de/realms/intern
    OIDC_CLIENT_ID / OIDC_CLIENT_SECRET
    OIDC_REDIRECT_URI=https://app.traeger.de/api/v1/auth/oidc/callback/
    OIDC_STAFF_CLAIM=groups        OIDC_STAFF_VALUE=leitung

Bei beiden Wegen wird ein Django-Konto angelegt, falls es noch keines gibt,
und - sofern ein Personaldatensatz mit passender E-Mail existiert - mit
diesem verknüpft. So greifen Rollen, Mandantenfilter und Dienstplan sofort.
"""

import logging

from django.conf import settings
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import User

logger = logging.getLogger("django_grp.auth")


def _setting(name, default=""):
    return getattr(settings, name, default)


def link_employee(user):
    """
    Verknüpft ein Konto mit einem vorhandenen Personaldatensatz.

    Gesucht wird über die E-Mail-Adresse, weil die im Verzeichnisdienst und
    in der Personalakte dieselbe ist. Bestehende Verknüpfungen bleiben.
    """
    from .models import Employee

    if not user.email:
        return None
    if Employee.objects.filter(user=user).exists():
        return None

    employee = Employee.objects.filter(
        user__isnull=True, email__iexact=user.email
    ).first()
    if employee:
        employee.user = user
        employee.save(update_fields=["user"])
    return employee


def upsert_user(username, *, email="", first_name="", last_name="", is_staff=None):
    """Konto anlegen oder aktualisieren, ohne ein lokales Passwort zu setzen."""
    user, created = User.objects.get_or_create(
        username=username,
        defaults={"email": email, "first_name": first_name, "last_name": last_name},
    )
    if created:
        # Kein lokales Passwort: die Anmeldung läuft ausschließlich über das
        # Verzeichnis bzw. den SSO-Anbieter.
        user.set_unusable_password()

    changed = []
    for field, value in (
        ("email", email),
        ("first_name", first_name),
        ("last_name", last_name),
    ):
        if value and getattr(user, field) != value:
            setattr(user, field, value)
            changed.append(field)

    if is_staff is not None and user.is_staff != is_staff:
        user.is_staff = is_staff
        changed.append("is_staff")

    if created or changed:
        user.save()

    link_employee(user)
    return user


class LDAPBackend(BaseBackend):
    """
    Anmeldung gegen LDAP oder Active Directory.

    Nutzt ldap3 (reines Python, keine C-Abhängigkeiten). Ohne LDAP_SERVER
    gibt der Backend sofort None zurück und stört die übrigen Backends nicht.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        server_uri = _setting("LDAP_SERVER")
        if not server_uri or not username or not password:
            return None

        try:
            from ldap3 import ALL, Connection, Server
            from ldap3.core.exceptions import LDAPException
        except ImportError:
            logger.warning("ldap3 ist nicht installiert, LDAP-Anmeldung übersprungen")
            return None

        template = _setting("LDAP_USER_DN_TEMPLATE", "{username}")
        user_dn = template.format(username=username)

        try:
            server = Server(server_uri, get_info=ALL)
            connection = Connection(server, user=user_dn, password=password)
            if not connection.bind():
                logger.info("LDAP-Anmeldung abgelehnt für %s", username)
                return None

            attributes = self._read_attributes(connection, username)
            connection.unbind()
        except LDAPException:
            logger.exception("LDAP nicht erreichbar (%s)", server_uri)
            return None

        return upsert_user(
            username,
            email=attributes.get("mail", ""),
            first_name=attributes.get("givenName", ""),
            last_name=attributes.get("sn", ""),
            is_staff=attributes.get("is_staff"),
        )

    def _read_attributes(self, connection, username) -> dict:
        """Name, E-Mail und Gruppenzugehörigkeit aus dem Verzeichnis lesen."""
        base = _setting("LDAP_SEARCH_BASE")
        if not base:
            return {}

        filter_template = _setting(
            "LDAP_USER_FILTER", "(|(sAMAccountName={username})(uid={username}))"
        )
        try:
            connection.search(
                base,
                filter_template.format(username=username),
                attributes=["mail", "givenName", "sn", "memberOf"],
            )
        except Exception:  # noqa: BLE001
            logger.exception("LDAP-Suche fehlgeschlagen")
            return {}

        if not connection.entries:
            return {}

        entry = connection.entries[0]
        result = {}
        for field in ("mail", "givenName", "sn"):
            value = getattr(entry, field, None)
            if value:
                result[field] = str(value)

        staff_group = _setting("LDAP_STAFF_GROUP")
        if staff_group:
            groups = [str(item) for item in (getattr(entry, "memberOf", None) or [])]
            result["is_staff"] = any(
                staff_group.lower() == group.lower() for group in groups
            )
        return result

    def get_user(self, user_id):
        return User.objects.filter(pk=user_id).first()


class OIDCClient:
    """
    Minimaler OpenID-Connect-Client für den Authorization-Code-Flow.

    Bewusst ohne zusätzliche Bibliothek: es sind zwei HTTP-Aufrufe, und eine
    Abhängigkeit weniger heißt eine Abhängigkeit weniger im Betrieb.
    """

    def __init__(self):
        self.issuer = _setting("OIDC_ISSUER").rstrip("/")
        self.client_id = _setting("OIDC_CLIENT_ID")
        self.client_secret = _setting("OIDC_CLIENT_SECRET")
        self.redirect_uri = _setting("OIDC_REDIRECT_URI")
        self._config = None

    @property
    def configured(self) -> bool:
        return bool(self.issuer and self.client_id and self.redirect_uri)

    def discover(self) -> dict:
        """Endpunkte aus dem Well-Known-Dokument des Anbieters holen."""
        if self._config is not None:
            return self._config

        import requests

        response = requests.get(
            f"{self.issuer}/.well-known/openid-configuration", timeout=10
        )
        response.raise_for_status()
        self._config = response.json()
        return self._config

    def authorization_url(self, state: str) -> str:
        from urllib.parse import urlencode

        config = self.discover()
        query = urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "scope": _setting("OIDC_SCOPE", "openid profile email"),
                "redirect_uri": self.redirect_uri,
                "state": state,
            }
        )
        return f"{config['authorization_endpoint']}?{query}"

    def exchange(self, code: str) -> dict:
        """Code gegen Token tauschen und die Nutzerdaten abrufen."""
        import requests

        config = self.discover()
        token_response = requests.post(
            config["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=10,
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]

        info_response = requests.get(
            config["userinfo_endpoint"],
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        info_response.raise_for_status()
        return info_response.json()

    def user_from_claims(self, claims: dict) -> User:
        username = (
            claims.get("preferred_username") or claims.get("email") or claims.get("sub")
        )

        staff_claim = _setting("OIDC_STAFF_CLAIM")
        staff_value = _setting("OIDC_STAFF_VALUE")
        is_staff = None
        if staff_claim and staff_value:
            raw = claims.get(staff_claim)
            values = raw if isinstance(raw, list) else [raw]
            is_staff = staff_value in [str(item) for item in values if item is not None]

        return upsert_user(
            username,
            email=claims.get("email", ""),
            first_name=claims.get("given_name", ""),
            last_name=claims.get("family_name", ""),
            is_staff=is_staff,
        )
