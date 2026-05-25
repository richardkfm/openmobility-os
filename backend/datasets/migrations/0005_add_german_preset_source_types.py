"""Add German federal preset source types (BNetzA, UBA, DWD, BASt)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("datasets", "0004_add_decision_support_layer_kinds"),
    ]

    operations = [
        migrations.AlterField(
            model_name="datasource",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("csv", "CSV (upload or URL)"),
                    ("geojson_url", "GeoJSON URL"),
                    ("osm_overpass", "OpenStreetMap (Overpass API)"),
                    ("manual", "Manual KPI entry"),
                    ("gtfs", "GTFS static (transit schedule)"),
                    ("ckan", "CKAN open-data portal"),
                    ("wfs", "WFS geo-service"),
                    ("rest", "Generic REST JSON"),
                    ("mobilithek", "Mobilithek (German NAP)"),
                    ("bnetza_charging", "BNetzA EV charging register"),
                    ("uba_air", "UBA air quality stations"),
                    ("dwd_climate", "DWD climate stations"),
                    ("bast_counts", "BASt traffic count stations"),
                ],
                max_length=30,
            ),
        ),
    ]
