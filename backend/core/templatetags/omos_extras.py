"""Custom template filters for OpenMobility OS."""

from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """dict|get_item:key — safe dict lookup in templates."""
    if isinstance(dictionary, dict):
        return dictionary.get(key, "")
    return ""


@register.filter
def replace(value, arg):
    """value|replace:'old:new' — simple string replacement."""
    if ":" not in arg:
        return value
    old, new = arg.split(":", 1)
    return str(value).replace(old, new)


@register.filter
def pprint(value):
    """Pretty-print JSON/dict values."""
    import json

    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, ensure_ascii=False)
    return str(value)
