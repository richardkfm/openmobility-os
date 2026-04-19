from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from django.contrib import admin

        admin.site.site_header = _("OpenMobility OS · Administration")
        admin.site.site_title = _("OpenMobility OS admin")
        admin.site.index_title = _("Workspace administration")
