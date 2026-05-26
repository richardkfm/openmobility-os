"""Add is_enabled and source_file fields to DataSource."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("datasets", "0007_combined_source_types"),
    ]

    operations = [
        migrations.AddField(
            model_name="datasource",
            name="is_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Disabled sources are not shown on the map.",
                verbose_name="Enabled",
            ),
        ),
        migrations.AddField(
            model_name="datasource",
            name="source_file",
            field=models.FileField(
                blank=True,
                null=True,
                upload_to="datasource_files/%Y/%m/",
                verbose_name="Source file",
                help_text="Upload a CSV or GeoJSON file directly instead of providing a URL.",
            ),
        ),
    ]
