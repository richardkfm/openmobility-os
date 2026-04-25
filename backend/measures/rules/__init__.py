from .bike_infrastructure import rule_missing_protected_bike_lane
from .safety import rule_accident_cluster
from .school_routes import rule_unsafe_school_route
from .transit import (
    rule_transit_accessibility,
    rule_transit_coverage_gap,
    rule_transit_frequency,
)

RULES = [
    rule_missing_protected_bike_lane,
    rule_transit_coverage_gap,
    rule_transit_frequency,
    rule_transit_accessibility,
    rule_accident_cluster,
    rule_unsafe_school_route,
]
