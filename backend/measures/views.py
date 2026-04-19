"""Measures app views — currently just the engine trigger."""

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core.decorators import admin_required
from core.utils import get_active_workspace

from .engine import run_engine


@admin_required
@require_POST
def generate_measures_view(request, workspace_slug):
    ws = get_active_workspace(workspace_slug)
    report = run_engine(ws)
    messages.success(
        request,
        _("Generated %(g)d new, updated %(u)d.") % {"g": report.generated, "u": report.updated},
    )
    return redirect(reverse("measures_list", kwargs={"workspace_slug": ws.slug}))
