import os
from datetime import timedelta
from pathlib import Path

from decouple import Csv
from celery.schedules import crontab
from decouple import config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_NAME = os.path.basename(PROJECT_ROOT)

MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config("DEBUG", default=False, cast=bool)

# ============================================================================
# Schluessel
# ============================================================================
#
# SECRET_KEY hat frueher eine eingebaute Vorgabe gehabt, und die stand als
# "django-insecure-..." in jedem Aufbau, den niemand angefasst hat. Weil aus
# demselben Schluessel auch die Verschluesselung der SMTP-Zugangsdaten und des
# VAPID-Privatkeys abgeleitet wird, war das kein Schoenheitsfehler: wer die
# Vorgabe kannte, konnte beides entschluesseln.
#
# Deshalb gibt es die Vorgabe nur noch im Entwicklungsbetrieb. Steht DEBUG auf
# False und fehlt ein eigener Schluessel, startet die Anwendung nicht - lauter
# Abbruch statt stiller Unsicherheit.

INSECURE_KEY_PREFIX = "django-insecure"

SECRET_KEY = config("SECRET_KEY", default="", cast=str).strip()

# Alte Schluessel, damit ein Wechsel bestehende Sitzungen und verschluesselte
# Felder nicht auf einen Schlag entwertet. Reihenfolge: neuester zuerst.
SECRET_KEY_FALLBACKS = config("SECRET_KEY_FALLBACKS", default="", cast=Csv())


def _schluessel_unsicher(schluessel: str) -> bool:
    return (
        not schluessel
        or schluessel.startswith(INSECURE_KEY_PREFIX)
        or len(schluessel) < 50
    )


if _schluessel_unsicher(SECRET_KEY):
    if DEBUG:
        SECRET_KEY = (
            "django-insecure-nur-fuer-die-entwicklung-"
            "niemals-mit-DEBUG=False-verwenden"
        )
    else:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(
            "SECRET_KEY fehlt oder ist unsicher. Einen neuen erzeugen "
            "mit: python manage.py schluessel_erzeugen - und als "
            "SECRET_KEY in die .env eintragen. Der bisherige Wert "
            "gehoert dann in SECRET_KEY_FALLBACKS, damit gespeicherte "
            "Zugangsdaten weiter lesbar bleiben."
        )

# Schluessel fuer verschluesselte Datenbankfelder (SMTP-Passwort, VAPID-Key).
#
# Eigener Wert, damit sich SECRET_KEY drehen laesst, ohne dass die
# Mailkonfiguration neu eingegeben werden muss. Fehlt er, wird wie bisher aus
# SECRET_KEY abgeleitet - bestehende Aufbauten bleiben lesbar.
FIELD_ENCRYPTION_KEY = config("FIELD_ENCRYPTION_KEY", default="", cast=str).strip()

# Liefert Django die Dateien aus MEDIA_ROOT selbst aus?
#
# Im Betrieb gehoert das vor die Anwendung: ein Reverse Proxy liest
# MEDIA_ROOT schneller und beherrscht Range-Requests. Wo keiner steht - etwa
# im Docker-Compose dieses Projekts - muessen Bewohnerfotos trotzdem
# ankommen. Vorgabe ist DEBUG, damit sich an bestehenden Aufbauten nichts
# aendert.
SERVE_MEDIA = config("SERVE_MEDIA", default=DEBUG, cast=bool)

CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", default="", cast=Csv())
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

# Vorgabe ist der oertliche Betrieb. "[*]" stand hier frueher und war schon
# als Platzhalter falsch: Csv() macht daraus ['[*]'], also einen Hostnamen,
# den es nicht gibt - im Betrieb faellt das erst beim ersten Zugriff auf.
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# CORS_ORIGIN_ALLOW_ALL = True stand hier fest verdrahtet und hat die
# sorgfaeltig aus der .env gefuellte Liste darunter komplett ausgehebelt -
# jede fremde Seite durfte die API im Browser ansprechen. Es gilt jetzt nur
# noch CORS_ALLOWED_ORIGINS.
CORS_ALLOW_CREDENTIALS = False

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "whitenoise.runserver_nostatic",
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
]

# Apps dieses Projekts einsammeln.
#
# Die Pruefung lief frueher ueber os.path.isdir(name) - also relativ zum
# Arbeitsverzeichnis des Prozesses. Wurde manage.py von woanders aufgerufen,
# war INSTALLED_APPS still leer und die Anwendung ohne erkennbaren Grund
# funktionslos. Jetzt zaehlt der Ort der Datei, nicht der des Aufrufers.
for name in sorted(os.listdir(BASE_DIR)):
    if name.startswith("django_grp_") and (BASE_DIR / name).is_dir():
        INSTALLED_APPS.append(name)

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "x_forwarded_for.middleware.XForwardedForMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django_auto_logout.middleware.auto_logout",
    # Hinterlegt den angemeldeten Benutzer für das Änderungsprotokoll.
    "django_grp_org.audit.AuditUserMiddleware",
]

AUTO_LOGOUT = {
    "IDLE_TIME": timedelta(hours=1),
    "MESSAGE": "Your session has expired. Please log in again",
    "REDIRECT_TO_LOGIN_IMMEDIATELY": True,
}

ROOT_URLCONF = "django_group_protocol.urls"

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
WHITENOISE_USE_FINDERS = True
WHITENOISE_MANIFEST_STRICT = False

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "django_group_protocol.wsgi.application"

# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases

MAIN_DATABASE_NAME = config("MAIN_DATABASE_NAME", default="maindb", cast=str)
MAIN_DATABASE_USER = config("MAIN_DATABASE_USER", default="maindb", cast=str)
MAIN_DATABASE_PASSWD = config("MAIN_DATABASE_PASSWD", default="secret", cast=str)
MAIN_DATABASE_HOST = config("MAIN_DATABASE_HOST", default="127.0.0.1", cast=str)
MAIN_DATABASE_PORT = config("MAIN_DATABASE_PORT", default="3306", cast=str)
MAIN_DATABASE_ENGINE = config(
    "MAIN_DATABASE_ENGINE", default="django.db.backends.sqlite3", cast=str
)
DATABASES = {
    "default": {
        "ENGINE": MAIN_DATABASE_ENGINE,
        "NAME": MAIN_DATABASE_NAME,
        "USER": MAIN_DATABASE_USER,
        "PASSWORD": MAIN_DATABASE_PASSWD,
        "HOST": MAIN_DATABASE_HOST,
        "PORT": MAIN_DATABASE_PORT,
        # Verbindungen eine Minute offen halten. Ohne das baut jede Anfrage
        # eine neue TCP- und Anmelde-Runde zur Datenbank auf; bei einer
        # Uebersichtsseite mit einem Dutzend Abfragen ist das messbar.
        "CONN_MAX_AGE": config("DB_CONN_MAX_AGE", default=60, cast=int),
        "CONN_HEALTH_CHECKS": True,
    },
}

# Das init_command ist MySQL-Sprache. Stand es unbesehen da, liess sich das
# Projekt mit SQLite nicht einmal starten ("near SET: syntax error") - und
# genau darauf faellt MAIN_DATABASE_ENGINE ohne .env zurueck.
if "mysql" in MAIN_DATABASE_ENGINE:
    DATABASES["default"]["OPTIONS"] = {
        "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        "charset": "utf8mb4",
    }
    DATABASES["default"]["TEST"] = {
        "CHARSET": "utf8mb4",
        "COLLATION": "utf8mb4_unicode_ci",
    }

# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

# Angemeldet wird sich mit Benutzername ODER E-Mail. Als Backend, damit das
# ueberall gilt - API, Django-Admin, Einrichtungsassistent - und nicht nur
# an der Tuer, an der jemand daran gedacht hat.
AUTHENTICATION_BACKENDS = [
    "django_grp_backend.auth_backends.UsernameOrEmailBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# ============================================================================
# Protokollierung im Betrieb (Roadmap Phase 9)
# ============================================================================

LOG_LEVEL = config("LOG_LEVEL", default="INFO", cast=str)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        # Ein Format, das sich sowohl lesen als auch maschinell auswerten
        # laesst: Zeitpunkt, Stufe, Herkunft, Meldung.
        "standard": {
            "format": "{asctime} {levelname:<8} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        # Eigene Meldungen (Anmeldung, Aenderungsprotokoll) getrennt steuerbar.
        "django_grp": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

# ============================================================================
# Rechte: Zugriffsstufe oder Rollen
# ============================================================================
#
# Der Umschalter aus rollenkonzept.md, Schritt 3. Drei Werte:
#
#   stufe      Employee.access_level entscheidet, wie bisher. Voreinstellung.
#   vergleich  Die Stufe entscheidet, die Rollen rechnen mit. Weicht das
#              Ergebnis ab, steht es als Warnung im Protokoll.
#   rollen     Die Rollenzuweisungen entscheiden.
#
# Der Weg fuehrt ueber "vergleich": erst wenn eine Woche lang keine
# Abweichung mehr auffaellt, wird scharf geschaltet. Wer sofort umschaltet,
# erfaehrt von der ersten Luecke durch einen Anruf aus der Nachtschicht.
RECHTE_QUELLE = config("RECHTE_QUELLE", default="stufe")

if RECHTE_QUELLE not in ("stufe", "vergleich", "rollen"):
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        f"RECHTE_QUELLE ist '{RECHTE_QUELLE}' - erlaubt sind stufe, "
        "vergleich und rollen."
    )

# ============================================================================
# REST-Schnittstelle
# ============================================================================
#
# BasicAuthentication war bis hierher aktiv, und damit nahm JEDER Endpunkt
# "Authorization: Basic benutzer:passwort" an. Zusammen mit dem fehlenden
# Bremsklotz am Login war das eine offene Einladung zum Durchprobieren von
# Passwoertern. Der Web-Client meldet sich per Token an und braucht es nicht;
# fuer die Fehlersuche laesst es sich ueber die .env wieder einschalten.
API_ALLOW_BASIC_AUTH = config("API_ALLOW_BASIC_AUTH", default=False, cast=bool)

# Nicht DRFs TokenAuthentication, sondern die Variante mit Ablaufdatum -
# siehe django_grp_api/auth.py und TOKEN_MAX_AGE_HOURS.
_AUTHENTICATION_CLASSES = ["django_grp_api.auth.AblaufendeTokenAuthentication"]
if API_ALLOW_BASIC_AUTH:
    _AUTHENTICATION_CLASSES.append("rest_framework.authentication.BasicAuthentication")

# Seitenweise ausliefern.
#
# Bis hierhin gab es keine Pagination: `GET /api/v1/resident/` lieferte jeden
# Bewohner, `GET /api/v1/protocol/` jedes Protokoll seit Inbetriebnahme -
# in einer Antwort, komplett im Speicher. Bei einem Traeger mit ein paar
# hundert Bewohnern und einigen tausend Protokollen wird daraus eine
# Uebersichtsseite, die Sekunden braucht.
#
# Die Seite ist bewusst gross: der Web-Client holt Listen ueber apiList()
# und folgt dabei "next", der Rundlauf faellt also kaum ins Gewicht. Die
# Grenze schuetzt vor der einen Anfrage, die alles auf einmal will.
API_PAGE_SIZE = config("API_PAGE_SIZE", default=200, cast=int)
API_PAGE_SIZE_MAX = config("API_PAGE_SIZE_MAX", default=1000, cast=int)

REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "django_grp_api.pagination.Seitenweise",
    "PAGE_SIZE": API_PAGE_SIZE,
    "DEFAULT_AUTHENTICATION_CLASSES": _AUTHENTICATION_CLASSES,
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Drosselung. Der Login hat einen eigenen, engen Takt (ScopedRateThrottle
    # am View), alles Uebrige einen weiten - er soll nicht die Fachkraft
    # bremsen, die zuegig arbeitet, sondern das Skript, das die Liste
    # durchprobiert.
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": config("THROTTLE_ANON", default="60/min", cast=str),
        "user": config("THROTTLE_USER", default="1200/min", cast=str),
        "login": config("THROTTLE_LOGIN", default="10/min", cast=str),
        "passwort": config("THROTTLE_PASSWORT", default="5/min", cast=str),
    },
}

# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/
LANGUAGE_CODE = config("LANGUAGE_CODE", default="de-de", cast=str)

TIME_ZONE = config("TIME_ZONE", default="Europe/Berlin", cast=str)
USE_I18N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ============================================================================
# Sicherheitskoepfe und Cookies
# ============================================================================
#
# Ein Schalter statt fuenf: wer die Anwendung hinter HTTPS stellt, setzt
# HTTPS=True in der .env und bekommt alles, was `manage.py check --deploy`
# verlangt. Einzeln bleibt jeder Wert ueberschreibbar - hinter einem
# Reverse Proxy, der TLS selbst abloest, will man SECURE_SSL_REDIRECT
# manchmal aus.
HTTPS = config("HTTPS", default=not DEBUG, cast=bool)

SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=HTTPS, cast=bool)
SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", default=HTTPS, cast=bool)
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", default=HTTPS, cast=bool)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Ein Jahr, sobald HTTPS steht. Vorher 0 - ein HSTS-Kopf auf einer Adresse,
# die noch kein Zertifikat hat, sperrt Browser dauerhaft aus.
SECURE_HSTS_SECONDS = config(
    "SECURE_HSTS_SECONDS", default=31536000 if HTTPS else 0, cast=int
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=HTTPS, cast=bool
)
SECURE_HSTS_PRELOAD = config("SECURE_HSTS_PRELOAD", default=False, cast=bool)

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Hinter einem Reverse Proxy erkennt Django HTTPS nur an diesem Kopf.
# Voraussetzung: der Proxy setzt ihn selbst und laesst ihn nicht durch.
if config("BEHIND_TLS_PROXY", default=HTTPS, cast=bool):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Bis wohin ein Token gilt. 0 heisst: unbegrenzt, wie bisher.
TOKEN_MAX_AGE_HOURS = config("TOKEN_MAX_AGE_HOURS", default=12, cast=int)

# Wie lange ein Link zum Zuruecksetzen des Passworts gilt (Sekunden).
PASSWORD_RESET_TIMEOUT = config("PASSWORD_RESET_TIMEOUT", default=3600, cast=int)

# Adresse der Weboberflaeche - fuer Links in Mails, die ausserhalb eines
# Requests entstehen (Celery kennt keinen Host).
PUBLIC_WEB_URL = config("PUBLIC_WEB_URL", default="http://localhost:3000", cast=str)

# API-only backend configuration
# No login URLs needed


# ============================================================ Celery
#
# Hintergrundaufgaben: Mailversand und der taegliche Blick auf faellige
# Aufgaben. Der Broker ist Redis (Container "redis" aus docker-compose.yml).
#
# Wichtig fuer den Betrieb: faellt Redis aus, faellt nicht die Anwendung aus.
# Der Mailversand merkt es und verschickt direkt weiter - siehe
# django_grp_mail/service.py. Was dann fehlt, ist die Wiederholung bei
# Fehlern, nicht die Mail selbst.

CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://redis:6379/0")
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default="redis://redis:6379/1")
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True

# Wartet nicht ewig, wenn der Broker weg ist - sonst haengt der Aufruf, der
# die Mail einstellen wollte, und die Fachkraft sieht eine drehende Scheibe.
CELERY_BROKER_TRANSPORT_OPTIONS = {"max_retries": 1}
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_TIMEOUT = 3

# Wie lange das Aenderungsprotokoll aufbewahrt wird (Tage). 0 schaltet das
# Aufraeumen ab.
#
# Die Frist ist die Bedingung dafuer, dass die Protokolldomaene ueberhaupt
# mitgeschrieben werden kann: ein Protokollabend erzeugt ein Dutzend
# Eintraege, und ohne Grenze waere die Tabelle in zwei Jahren groesser als
# die Fachdaten.
AUDIT_RETENTION_DAYS = config("AUDIT_RETENTION_DAYS", default=1095, cast=int)

# Traegertrennung scharf stellen.
#
# Ohne diesen Schalter sehen Konten OHNE Personaldatensatz weiterhin alles -
# bewusst, damit bestehende Verwaltungskonten nach einem Update nicht vor
# einer leeren Anwendung stehen. Sobald jedem Konto ein Employee mit Traeger
# zugeordnet ist, gehoert der Schalter auf True: dann sieht ein Konto ohne
# Zuordnung nichts mehr (Superuser ausgenommen).
STRICT_TENANCY = config("STRICT_TENANCY", default=False, cast=bool)

CELERY_BEAT_SCHEDULE = {
    "aenderungsprotokoll-aufraeumen": {
        "task": "django_grp_org.aufraeumen_aenderungsprotokoll",
        # Sonntagnacht: da stoert das Loeschen niemanden.
        "schedule": crontab(hour=3, minute=30, day_of_week=0),
    },
    "faellige-aufgaben-erinnern": {
        "task": "django_grp_mail.erinnere_an_faellige_aufgaben",
        # Jeden Morgen um sieben - vor dem Fruehdienst, nicht mitten in der
        # Nacht: wer die Mail um drei Uhr bekommt, liest sie trotzdem erst
        # morgens, und im Postfach steht dann ein sinnloser Zeitstempel.
        "schedule": crontab(hour=7, minute=0),
    },
}
