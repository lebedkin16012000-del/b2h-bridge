"""Public facade used by the B2H Houdini panel and generated import scripts."""

import os

from b2h_manifest import (
    bridge_dir,
    clean_path,
    load_manifest,
    report_status,
    resolve_asset_path,
    resolve_texture_path,
    safe_name,
    validate_manifest,
)


BRIDGE_SUFFIX = "_bridge.json"
DEFAULT_SCAN_DEPTH = 6
DEFAULT_SCAN_LIMIT = 2000


def is_cloud_placeholder(path):
    """Return True for cloud-only Windows placeholders without opening them."""
    try:
        attrs = getattr(os.stat(path), "st_file_attributes", 0)
        offline = getattr(os, "FILE_ATTRIBUTE_OFFLINE", 0x1000)
        recall_on_open = 0x00040000
        recall_on_data_access = 0x00400000
        return bool(attrs & (offline | recall_on_open | recall_on_data_access))
    except OSError:
        return False


def find_bridge_files(root, max_depth=DEFAULT_SCAN_DEPTH, limit=DEFAULT_SCAN_LIMIT):
    """Scan iteratively with bounded depth/count so broad roots remain responsive."""
    root = os.path.abspath(root) if root else ""
    if not os.path.isdir(root):
        return []
    found = []
    stack = [(root, 0)]
    while stack and len(found) < limit:
        directory, depth = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(BRIDGE_SUFFIX):
                    found.append(entry.path)
                    if len(found) >= limit:
                        break
                elif depth < max_depth and entry.is_dir(follow_symlinks=False):
                    stack.append((entry.path, depth + 1))
            except OSError:
                continue
    return sorted(found, key=lambda value: value.lower())


def summarize_asset(meta):
    normalized, report = validate_manifest(meta, check_files=True)
    materials = normalized.get("materials") or {}
    assignments = normalized.get("assignments") or []
    return {
        "asset_name": normalized.get("asset_name", "Asset"),
        "asset_id": normalized.get("asset_id", ""),
        "revision": normalized.get("asset_revision", ""),
        "base_dir": bridge_dir(normalized) or "",
        "usd_path": normalized.get("__resolved_usd_path") or "",
        "bridge_path": normalized.get("__bridge_path") or "",
        "material_count": len(materials),
        "assignment_count": len(assignments),
        "status": report_status(report),
        "report": report,
        "meta": normalized if report.get("valid") else None,
    }


def scan_b2h_assets(root, max_depth=DEFAULT_SCAN_DEPTH, limit=DEFAULT_SCAN_LIMIT):
    assets = []
    for bridge_path in find_bridge_files(root, max_depth=max_depth, limit=limit):
        if is_cloud_placeholder(bridge_path):
            assets.append({
                "asset_name": os.path.basename(bridge_path), "asset_id": "", "revision": "",
                "base_dir": clean_path(os.path.dirname(bridge_path)), "usd_path": "",
                "bridge_path": clean_path(bridge_path), "material_count": 0, "assignment_count": 0,
                "status": "Skipped cloud-only file",
                "report": {"errors": ["Cloud-only file"], "warnings": []}, "meta": None,
            })
            continue
        try:
            assets.append(summarize_asset(load_manifest(bridge_path)))
        except Exception as error:
            assets.append({
                "asset_name": os.path.basename(bridge_path), "asset_id": "", "revision": "",
                "base_dir": clean_path(os.path.dirname(bridge_path)), "usd_path": "",
                "bridge_path": clean_path(bridge_path), "material_count": 0, "assignment_count": 0,
                "status": "Invalid JSON: %s" % error,
                "report": {"errors": [str(error)], "warnings": []}, "meta": None,
            })
    return assets


def import_b2h_asset(meta_or_path, progress=None):
    # Houdini-specific modules are loaded only when importing, keeping scans cheap.
    from b2h_importer import import_asset
    return import_asset(meta_or_path, progress=progress)
