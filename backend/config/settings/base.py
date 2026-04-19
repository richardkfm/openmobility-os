"""
Base Django settings for OpenMobility OS.

City-agnostic. Multi-tenant via path-based URLs. Self-hostable.
See CLAUDE.md in the repo root for project principles.
"""

from pathlib import Path

import environ

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BACKEND_DIR.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    DEPLOYMENT_MODE=(str, "public-demo"),
    DEFAULT_WORKSPACE_SLUG=(str, ""),
    DEFAULT_LOCALE=(str, "de"),
    MAP_TILE_URL=(str, "https://tile.openstreetmap.org/{z}/{x}/{y}.png"),
    MAP_TILE_ATTRIBUTION=(str, "© OpenStreetMap contributors"),
    OSM_OVERPASS_API=(str, "https://overpass-api.de/api/interpreter"),
    AUTO_SEED_DEMO=(bool, True),
)

env_file = REPO_ROOT / ".env"
if env_file.exists():
    env.read_env(str(env_file))

# --- Platform metadata ---
try:
    PLATFORM_VERSION = (REPO_ROOT / "VERSION").read_text().strip()
except OSError:
    PLATFORM_VERSION = "0.0.0"

# --- Security ---
SECRET_KEY = env("SECRET_KEY", default="dev-insecure-key-do-not-use-in-prod")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# --- Deployment / tenancy ---
DEPLOYMENT_MODE = env("DEPLOYMENT_MODE")
DEFAULT_WORKSPACE_SLUG = env("DEFAULT_WORKSPACE_SLUG")
ADMIN_TOKEN = env("ADMIN_TOKEN", default="")

# --- Map config ---
MAP_TILE_URL = env("MAP_TILE_URL")
MAP_TILE_ATTRIBUTION = env("MAP_TILE_ATTRIBUTION")
OSM_OVERPASS_API = env("OSM_OVERPASS_API")

AUTO_SEED_DEMO = env("AUTO_SEED_DEMO")

# --- Applications ---
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "rest_framework",
    "rest_framework_gis",
    "django_htmx",
    # OpenMobility OS apps
    "core",
    "workspaces",
    "goals",
    "datasets",
    "connectors",
    "measures",
    "maps",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "core.middleware.AdminTokenMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BACKEND_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                "core.context_processors.platform_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database (PostGIS) ---
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgis://openmobility:changeme@db:5432/openmobility",
    )
}
DATABASES["default"]["ENGINE"] = "django.contrib.gis.db.backends.postgis"

# --- Passwords ---
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Internationalization ---
LANGUAGE_CODE = env("DEFAULT_LOCALE")
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

LANGUAGES = [
    ("de", "Deutsch"),
    ("en", "English"),
]

LOCALE_PATHS = [BACKEND_DIR / "locale"]

# --- Static / media ---
STATIC_URL = "static/"
STATIC_ROOT = REPO_ROOT / "staticfiles"
STATICFILES_DIRS = [BACKEND_DIR / "static"]

MEDIA_URL = "media/"
MEDIA_ROOT = REPO_ROOT / "mediafiles"

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# --- DRF ---
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# GDAL — auto-detect path for common Linux library locations
import ctypes.util as _cu

GDAL_LIBRARY_PATH = env("GDAL_LIBRARY_PATH", default=None)
if not GDAL_LIBRARY_PATH:
    for _candidate in [
        "/usr/lib/x86_64-linux-gnu/libgdal.so",
        "/usr/lib/libgdal.so",
    ]:
        from pathlib import Path as _P
        if _P(_candidate).exists():
            GDAL_LIBRARY_PATH = _candidate
            break

# --- Logging ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[{levelname}] {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
    },
}
