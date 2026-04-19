"""Platform-level workspace URLs (e.g. new-workspace wizard)."""

from django.urls import path

from . import views_wizard

urlpatterns = [
    path("new/", views_wizard.wizard_start, name="workspace_new"),
    path("new/create/", views_wizard.wizard_create, name="workspace_new_create"),
    path("admin-login/", views_wizard.admin_login, name="admin_login"),
    path("admin-logout/", views_wizard.admin_logout, name="admin_logout"),
]
