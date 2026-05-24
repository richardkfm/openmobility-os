"""Add decision-support layer kinds (EV charging, traffic & cycling counts,
noise, public buildings, population grid, demographics)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("datasets", "0003_add_mobilithek_source_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="datasource",
            name="layer_kind",
            field=models.CharField(
                choices=[
                    ("streets", "Streets"),
                    ("streets_with_speed", "Streets with speed limits"),
                    ("bike_network", "Bike network"),
                    ("transit_stops", "Transit stops"),
                    ("transit_routes", "Transit routes"),
                    ("transit_coverage", "Transit coverage (buffer)"),
                    ("accidents", "Accidents"),
                    ("parking", "Parking"),
                    ("districts", "Districts / neighborhoods"),
                    ("schools", "Schools"),
                    ("air_quality", "Air quality stations"),
                    ("land_use", "Land use"),
                    ("trees", "Tree cadastre"),
                    ("green_areas", "Green areas / parks"),
                    ("sealed_surfaces", "Sealed surfaces"),
                    ("heat_corridors", "Heat / fresh-air corridors"),
                    ("water_bodies", "Water bodies / retention areas"),
                    ("ev_charging", "EV charging stations"),
                    ("traffic_counts", "Traffic counts"),
                    ("cycling_counts", "Cycling counts"),
                    ("noise", "Noise contours"),
                    ("public_buildings", "Public buildings / amenities"),
                    ("population_grid", "Population density grid"),
                    ("demographics", "Demographic indicators"),
                    ("custom", "Custom / other"),
                ],
                default="custom",
                max_length=30,
            ),
        ),
    ]
