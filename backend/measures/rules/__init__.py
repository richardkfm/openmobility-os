from .bike_infrastructure import rule_missing_protected_bike_lane
from .electrification import rule_ev_charging_gap
from .equity import rule_population_equity_gap
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
    rule_ev_charging_gap,
    rule_population_equity_gap,
]
