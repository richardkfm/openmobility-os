from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("datasets", "0008_data_source_enabled_and_file"),
    ]

    operations = [
        migrations.AddField(
            model_name="datasource",
            name="last_sync_warnings",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
