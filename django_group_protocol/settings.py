import os
from datetime import timedelta
from pathlib import Path

from decouple import Csv
from decouple import config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_NAME = os.path.basename(PROJECT_ROOT)

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


SECRET_KEY = config(
    "SECRET_KEY",
    default="django-insecure-(x$!=h4%mq4n4#&qjwpw(1@jwqfwh$@v4)!ax*-pi#fdozx6zm",
    cast=str,
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config("DEBUG", default=False, cast=bool)

CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", default="", cast=Csv())
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="[*]", cast=Csv())
CORS_ORIGIN_ALLOW_ALL = True


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
    "corsheaders",
]

# Dynamic loading of modules
for name in os.listdir(PROJECT_ROOT + "/.."):
    if os.path.isdir(name) and name.startswith("django_grp_"):
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
]

AUTO_LOGOUT = {
    "IDLE_TIME": timedelta(hours=1),
    "MESSAGE": "Your session has expired. Please log in again",
    "REDIRECT_TO_LOGIN_IMMEDIATELY": True,
}

ROOT_URLCONF = "django_group_protocol.urls"

STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

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
        "OPTIONS": {"init_command": "SET sql_mode='STRICT_TRANS_TABLES'"},
    },
}


# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

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

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
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

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
