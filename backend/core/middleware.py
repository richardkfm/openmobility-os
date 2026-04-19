"""
Admin-token middleware.

Write actions on OpenMobility OS are protected by a shared ADMIN_TOKEN defined
in the environment. See CLAUDE.md for rationale.

The token may be supplied via:
 - HTTP header: `Authorization: Bearer <token>`
 - Session cookie (after POST to /admin-login/)
"""

from django.conf import settings

SESSION_KEY = "omos_admin_authenticated"


def is_admin_authenticated(request) -> bool:
    if not settings.ADMIN_TOKEN:
        # No token configured means no admin features enabled.
        return False

    header = request.META.get("HTTP_AUTHORIZATION", "")
    if header.startswith("Bearer ") and header[7:] == settings.ADMIN_TOKEN:
        return True

    return bool(request.session.get(SESSION_KEY))


class AdminTokenMiddleware:
    """Attaches `request.is_admin` for use in views and templates."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.is_admin = is_admin_authenticated(request)
        return self.get_response(request)
