"""Add the zensus_grid source type."""

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
                    ("zensus_grid", "Zensus 2022 population grid"),
                ],
                max_length=30,
            ),
        ),
    ]
