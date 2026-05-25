"""Decorators for protecting write actions."""

from functools import wraps

from django.http import HttpResponseForbidden
from django.utils.translation import gettext as _


def admin_required(view_func):
    @wraps(view_func)
    def _wrapped(*args, **kwargs):
        # Support both function views (request as 1st arg) and CBV methods
        # (self as 1st arg, request as 2nd).
        if args and hasattr(args[0], "method"):
            request = args[0]
        elif len(args) >= 2 and hasattr(args[1], "method"):
            request = args[1]
        else:
            request = args[0]
        if not getattr(request, "is_admin", False):
            return HttpResponseForbidden(
                _("Admin token required. Set ADMIN_TOKEN in .env and sign in.")
            )
        return view_func(*args, **kwargs)

    return _wrapped
