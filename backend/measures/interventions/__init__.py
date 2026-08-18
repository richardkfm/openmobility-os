"""Intervention finders, registered in the order they should be considered.

Same static-list registration as ``measures/rules/__init__.py``: adding a finder
means adding an import and a list entry, with no discovery magic in between.
"""

from .cycling_safety import find_cycling_interventions, find_speed_interventions

INTERVENTION_FINDERS = [
    find_cycling_interventions,
    find_speed_interventions,
]
