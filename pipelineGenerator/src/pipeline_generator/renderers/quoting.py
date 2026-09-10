from __future__ import annotations

import json
import shlex

from pipeline_generator.text_utils import slugify


def yaml_dquote(value: str) -> str:
    """Render value as a YAML double-quoted scalar.

    JSON string syntax is a valid subset of YAML double-quoted scalar
    syntax, so json.dumps gives correct escaping (quotes, backslashes,
    newlines, control characters) without depending on PyYAML's dumper.
    """
    return json.dumps(value)


def shell_quote(value: str) -> str:
    """Safely quote a value for embedding as one argument in a POSIX shell command."""
    return shlex.quote(value)


def groovy_squote(value: str) -> str:
    """Render value as a single-quoted Groovy string literal, backslash/quote-escaped.

    Groovy single-quoted strings do not interpolate (`$var`/`${...}` are
    left literal), so escaping just backslashes and single quotes is
    sufficient to make this safe to embed in a Jenkinsfile.
    """
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def safe_filename_component(value: str) -> str:
    """Sanitize a value for use as a single filesystem path segment.

    Prevents path separators/traversal (e.g. a job named "../../etc") and
    other filesystem-unsafe characters from reaching the generated path.
    """
    return slugify(value)


def blazemeter_timeout_flag(tool_type: str, timeout_minutes: int, separator: str = " ") -> str:
    """Render the --timeout-minutes flag appended to a manual/automated pipeline's
    generated script invocation. BlazeMeter-only -- JMeter's and LoadRunner
    Professional's generated scripts don't take this flag.
    """
    if tool_type != "blazemeter":
        return ""
    return f"{separator}--timeout-minutes {timeout_minutes}"
