import string
from typing import Dict, Set


def required_fields(template: str) -> Set[str]:
    """
    Field names referenced by a template's {placeholders}. Only plain
    {name} placeholders are supported -- no attribute/index access
    ({a.b}, {a[0]}), no positional ({0}), no conversion/format specs
    ({a!s}, {a:>10}).
    """
    fields: Set[str] = set()
    for _literal_text, field_name, format_spec, conversion in string.Formatter().parse(template):
        if field_name is None:
            continue
        if not field_name.isidentifier() or format_spec or conversion:
            raise ValueError(f"unsupported placeholder in template: {{{field_name}}}")
        fields.add(field_name)
    return fields


def validate_vars(template: str, provided: Dict[str, str], reserved: Set[str]) -> None:
    """
    Raises ValueError if `provided` sets a reserved key, or if `template`
    references a field that is neither in `provided` nor in `reserved`.
    """
    reserved_conflicts = sorted(set(provided) & reserved)
    if reserved_conflicts:
        raise ValueError(f"--var cannot set reserved name(s): {', '.join(reserved_conflicts)}")

    missing = sorted(required_fields(template) - set(provided) - reserved)
    if missing:
        raise ValueError(
            f"template {template!r} is missing value(s) for: {', '.join(missing)}. "
            "Supply them with --var key=value."
        )


def render(template: str, **fields: str) -> str:
    return template.format(**fields)
