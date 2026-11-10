"""Validation for IDs that end up inside a request path."""

import re

_NUMERIC = re.compile(r"^[0-9]{1,32}$")


def require_numeric_id(value, name: str) -> str:
    """TikTok Shop product/category IDs are decimal strings; reject anything else
    so a value like "123/../activate" can never change the request path."""
    text = str(value).strip() if value is not None else ""
    if not _NUMERIC.match(text):
        raise ValueError(f"{name} must be a numeric ID string, got {value!r}")
    return text
