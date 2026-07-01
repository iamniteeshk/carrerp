"""YAML loading helpers.

``load_yaml_with_lines`` returns parsed data where every mapping carries the
source line numbers of its keys, so configuration validation can report errors
like "candidate.phone missing (candidate.yaml line 18)" instead of an opaque
stack trace.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class LineLoader(yaml.SafeLoader):
    """SafeLoader that records the source line of each mapping key."""


def _construct_mapping(loader: LineLoader, node: yaml.MappingNode) -> dict:
    mapping = loader.construct_mapping(node, deep=True)
    # Attach a hidden map of key -> 1-based line number.
    line_map: dict[str, int] = {}
    for key_node, _value_node in node.value:
        try:
            line_map[str(key_node.value)] = key_node.start_mark.line + 1
        except AttributeError:
            pass
    mapping["__lines__"] = line_map
    return mapping


LineLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Plain parse (no line info)."""
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_yaml_with_lines(path: str | Path) -> dict[str, Any]:
    """Parse and annotate each mapping with a '__lines__' key -> line number."""
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.load(fh, Loader=LineLoader)  # noqa: S506 - LineLoader is safe
    return data or {}


def line_of(mapping: dict[str, Any], key: str) -> int | None:
    """Return the source line of ``key`` within an annotated mapping, if known."""
    lines = mapping.get("__lines__") if isinstance(mapping, dict) else None
    return lines.get(key) if isinstance(lines, dict) else None


def strip_line_meta(value: Any) -> Any:
    """Recursively remove '__lines__' annotations for clean runtime use."""
    if isinstance(value, dict):
        return {k: strip_line_meta(v) for k, v in value.items() if k != "__lines__"}
    if isinstance(value, list):
        return [strip_line_meta(v) for v in value]
    return value
