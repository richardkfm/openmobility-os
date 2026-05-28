from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspaces", "0002_connectorauditlog"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspace",
            name="settings",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Free-form per-workspace UI state "
                    "(catalog URLs, last filters, …)."
                ),
            ),
        ),
    ]
