from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("datasets", "0011_alter_datasource_layer_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="datasource",
            name="provenance",
            field=models.CharField(
                choices=[
                    ("live", "Live source"),
                    ("official_snapshot", "Official snapshot"),
                    ("illustrative_demo", "Illustrative demo"),
                ],
                default="live",
                help_text=(
                    "Whether this source is a live feed, a stored snapshot of "
                    "official data, or illustrative demo data that is not a "
                    "real measurement."
                ),
                max_length=20,
                verbose_name="Data provenance",
            ),
        ),
    ]
