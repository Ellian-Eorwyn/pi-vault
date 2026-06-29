"""Legacy metadata mapping helpers."""

from __future__ import annotations

from typing import Any

from .config import AgentConfig
from .schema import COMMON_PROPERTIES, load_schema, property_order_from_schema


def _approved_properties(
    config: AgentConfig, approved_properties: set[str] | None
) -> set[str]:
    if approved_properties is not None:
        return approved_properties
    return set(property_order_from_schema(load_schema(config.vault_root)))


def apply_legacy_mappings(
    frontmatter: dict[str, Any],
    config: AgentConfig,
    *,
    approved_properties: set[str] | None = None,
) -> dict[str, Any]:
    """Return frontmatter with safe legacy aliases copied into approved fields.

    An alias may target any approved property (built-in core or a user-declared
    custom property such as ``read_time``). Built-in controlled targets keep their
    value normalization; custom targets copy the value through as-is.
    """
    mapped = dict(frontmatter)
    approved = _approved_properties(config, approved_properties)
    for legacy_key, core_key in config.legacy_property_aliases.items():
        if legacy_key not in frontmatter:
            continue
        if core_key not in approved:
            continue
        if mapped.get(core_key) not in (None, "", []):
            continue
        if core_key in COMMON_PROPERTIES:
            value = _normalize_property_value(core_key, frontmatter[legacy_key], config)
        else:
            value = frontmatter[legacy_key]
        if value not in (None, ""):
            mapped[core_key] = value

    if isinstance(mapped.get("type"), str):
        mapped["type"] = config.legacy_type_aliases.get(mapped["type"], mapped["type"])
    if isinstance(mapped.get("status"), str):
        mapped["status"] = config.legacy_status_aliases.get(mapped["status"], mapped["status"])
    if isinstance(mapped.get("source_kind"), str):
        mapped["source_kind"] = config.legacy_source_kind_aliases.get(
            mapped["source_kind"], mapped["source_kind"]
        )
    return mapped


def mapped_property_for(
    key: str, config: AgentConfig, approved_properties: set[str] | None = None
) -> str | None:
    mapped = config.legacy_property_aliases.get(key)
    if mapped is None:
        return None
    return mapped if mapped in _approved_properties(config, approved_properties) else None


def mapped_controlled_value(key: str, value: Any, config: AgentConfig) -> str | None:
    if not isinstance(value, str):
        return None
    if key == "type":
        return config.legacy_type_aliases.get(value)
    if key == "status":
        return config.legacy_status_aliases.get(value)
    if key == "source_kind":
        return config.legacy_source_kind_aliases.get(value)
    return None


def _normalize_property_value(key: str, value: Any, config: AgentConfig) -> Any:
    if key == "domain":
        return _first_allowed_string(value, COMMON_PROPERTIES["domain"]["allowed"])
    if key == "source_kind":
        value = _first_string(value)
        mapped = config.legacy_source_kind_aliases.get(value, value)
        allowed = COMMON_PROPERTIES["source_kind"]["allowed"]
        return mapped if mapped in allowed else ""
    if key == "related":
        if isinstance(value, list):
            related = [_normalize_related_item(item) for item in value]
            return [item for item in related if item]
        if isinstance(value, str) and "," in value:
            related = [_normalize_related_item(item) for item in value.split(",")]
            return [item for item in related if item]
        first = _first_string(value)
        normalized = _normalize_related_item(first)
        return [normalized] if normalized else []
    return value


def _first_string(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            text = str(item).strip()
            if text:
                return text
        return ""
    return str(value).strip() if value not in (None, "") else ""


def _first_allowed_string(value: Any, allowed: list[str]) -> str:
    values = value if isinstance(value, list) else [value]
    for item in values:
        text = str(item).strip() if item not in (None, "") else ""
        if text in allowed:
            return text
    return ""


def _normalize_related_item(value: Any) -> str:
    text = str(value).strip() if value not in (None, "") else ""
    if not text:
        return ""
    return text.removeprefix("#").strip()
