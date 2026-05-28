"""YAML file IO helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from xctx.errors import XctxError


class UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(loader: UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found unhashable YAML key: {key!r}",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate YAML key: {key}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML mapping from *path* or raise a protocol-guidance error."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.load(handle, Loader=UniqueKeySafeLoader)
    except FileNotFoundError as exc:
        raise XctxError(f"missing YAML file: {path}") from exc
    except yaml.YAMLError as exc:
        raise XctxError(f"invalid YAML file {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise XctxError(f"YAML file must contain a mapping: {path}")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Write a YAML mapping while preserving human-editable order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=False, width=88)
