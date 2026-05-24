"""Drop the '(planned)' labels on CKAN/WFS/REST and add the Mobilithek source type."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("datasets", "0002_phase9_transit_layers"),
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
                ],
                max_length=30,
            ),
        ),
    ]
