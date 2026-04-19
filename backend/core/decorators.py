"""Decorators for protecting write actions."""

from functools import wraps

from django.http import HttpResponseForbidden
from django.utils.translation import gettext as _


def admin_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not getattr(request, "is_admin", False):
            return HttpResponseForbidden(
                _("Admin token required. Set ADMIN_TOKEN in .env and sign in.")
            )
        return view_func(request, *args, **kwargs)

    return _wrapped
