"""Catálogo de flujos: specs JSON independientes bajo specs/ y demo_specs/."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Optional

FLOW_TYPE_DEMO = "demo"
FLOW_TYPE_TEST = "test"


def get_flow_spec_directories() -> Dict[str, str]:
    root_dir = os.path.abspath(os.path.dirname(__file__))
    return {
        FLOW_TYPE_TEST: os.path.join(root_dir, "specs"),
        FLOW_TYPE_DEMO: os.path.join(root_dir, "demo_specs"),
    }


def infer_flow_type_from_path(path: str) -> str:
    normalized_path = os.path.abspath(path)
    directories = get_flow_spec_directories()
    if normalized_path.startswith(os.path.abspath(directories[FLOW_TYPE_DEMO])):
        return FLOW_TYPE_DEMO
    return FLOW_TYPE_TEST


def list_flow_spec_files(flow_types: Optional[Iterable[str]] = None) -> List[str]:
    directories = get_flow_spec_directories()
    selected_types = list(flow_types or directories.keys())
    files: List[str] = []

    for flow_type in selected_types:
        directory = directories.get(flow_type)
        if not directory or not os.path.isdir(directory):
            continue
        for dirpath, _dirnames, filenames in os.walk(directory):
            for name in sorted(filenames):
                if name.lower().endswith(".json"):
                    files.append(os.path.join(dirpath, name))
    return sorted(files)


def load_flow_wrapper(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        return data
    raise ValueError(f"Flow spec must be a JSON object: {path}")


def get_flow_key(path: str, wrapper: Optional[Dict[str, Any]] = None) -> str:
    wrapper = wrapper or load_flow_wrapper(path)
    catalog = wrapper.get("flow_catalog") or {}
    if isinstance(catalog, dict):
        for key_name in ("platform_flow_key", "flow_key"):
            value = catalog.get(key_name)
            if value is not None and str(value).strip():
                return str(value).strip()
    return os.path.splitext(os.path.basename(path))[0]


def get_flow_catalog_metadata(path: str) -> Dict[str, Any]:
    wrapper = load_flow_wrapper(path)
    catalog = wrapper.get("flow_catalog") or {}
    if not isinstance(catalog, dict):
        raise ValueError(f"flow_catalog must be an object in {path}")

    catalog_copy = dict(catalog)
    catalog_copy.setdefault("flow_type", infer_flow_type_from_path(path))
    catalog_copy.setdefault("flow_key", get_flow_key(path, wrapper))
    catalog_copy.setdefault("visible_name", os.path.splitext(os.path.basename(path))[0])
    return catalog_copy


def find_flow_graph_path(flow_key: str, flow_type: Optional[str] = None) -> Optional[str]:
    if flow_key is None or not str(flow_key).strip():
        return None

    requested_key = str(flow_key).strip()
    normalized_requested_key = requested_key.lower()
    flow_types = [flow_type] if flow_type else None

    exact: Optional[str] = None
    fuzzy: Optional[str] = None
    for path in list_flow_spec_files(flow_types=flow_types):
        wrapper = load_flow_wrapper(path)
        basename_key = os.path.splitext(os.path.basename(path))[0].lower()
        catalog_key = get_flow_key(path, wrapper).lower()
        if normalized_requested_key == catalog_key:
            exact = path
            break
        if fuzzy is None and normalized_requested_key in {basename_key, catalog_key}:
            fuzzy = path
        # Also allow "clinica_vida" → clinica_vida_flow_graph.json
        if fuzzy is None and (
            basename_key.startswith(normalized_requested_key)
            or normalized_requested_key.startswith(basename_key.replace("_flow_graph", ""))
        ):
            fuzzy = path
    return exact or fuzzy


def resolve_kb_path(wrapper: Dict[str, Any], *, app_dir: Optional[str] = None) -> Optional[str]:
    """Resuelve app/kb/<file> desde flow_catalog.knowledge_base.file."""
    catalog = wrapper.get("flow_catalog") or {}
    kb = catalog.get("knowledge_base") if isinstance(catalog, dict) else None
    if not isinstance(kb, dict):
        return None
    filename = str(kb.get("file") or "").strip()
    if not filename:
        return None
    root = app_dir or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(root, "kb", filename)
