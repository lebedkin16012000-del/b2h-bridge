"""B2H bridge manifest loading, normalization and validation."""

import copy
import json
import os
import re


SUPPORTED_SCHEMA_VERSIONS = {1}
TEXTURE_ROLE_ALIASES = {
    "base_color": "basecolor",
    "basecolour": "basecolor",
    "albedo": "basecolor",
    "diffuse": "basecolor",
    "specular_roughness": "roughness",
    "metalness": "metallic",
    "alpha": "opacity",
    "emission_color": "emission",
    "height": "displacement",
    "bump": "displacement",
}
SUPPORTED_TEXTURE_ROLES = {
    "basecolor", "roughness", "metallic", "normal", "opacity",
    "emission", "transmission", "ior", "displacement", "ao",
}


def clean_path(path):
    if not path:
        return None
    return os.path.normpath(os.path.expandvars(os.path.expanduser(str(path)))).replace("\\", "/")


def safe_name(name, fallback="item"):
    value = str(name or fallback).strip().replace(" ", "_")
    value = re.sub(r"[^A-Za-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_") or fallback
    return "_" + value if value[0].isdigit() else value


def bridge_dir(meta):
    bridge_path = clean_path((meta or {}).get("__bridge_path"))
    if bridge_path:
        return clean_path(os.path.dirname(bridge_path))
    base_dir = clean_path((meta or {}).get("base_dir"))
    return base_dir if base_dir and os.path.isabs(base_dir) else None


def _candidate_paths(meta, path, extra_dirs=(), fallback_names=()):
    base = bridge_dir(meta)
    raw = clean_path(path)
    candidates = []
    if raw:
        if os.path.isabs(raw):
            candidates.append(raw)
        elif base:
            candidates.append(clean_path(os.path.join(base, raw)))
        if base:
            candidates.append(clean_path(os.path.join(base, os.path.basename(raw))))
            for directory in extra_dirs:
                candidates.append(clean_path(os.path.join(base, directory, os.path.basename(raw))))
    if base:
        for fallback in fallback_names:
            if fallback:
                candidates.append(clean_path(os.path.join(base, fallback)))
    result = []
    seen = set()
    for candidate in candidates:
        key = os.path.normcase(candidate) if candidate else ""
        if candidate and key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def resolve_asset_path(meta, path, *fallback_names):
    candidates = _candidate_paths(meta, path, fallback_names=fallback_names)
    return next((item for item in candidates if os.path.isfile(item)), candidates[0] if candidates else clean_path(path))


def resolve_texture_path(meta, path):
    texture_dir = clean_path((meta or {}).get("texture_dir"))
    extra = ["textures"]
    if texture_dir and not os.path.isabs(texture_dir):
        extra.insert(0, texture_dir)
    candidates = _candidate_paths(meta, path, extra_dirs=extra)
    return next((item for item in candidates if os.path.isfile(item)), candidates[0] if candidates else clean_path(path))


def load_manifest(path):
    manifest_path = clean_path(path)
    with open(manifest_path, "r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Manifest root must be a JSON object")
    data["__bridge_path"] = manifest_path
    return data


def _material_candidates(item):
    values = []
    if item.get("bth_material"):
        values.append(item["bth_material"])
    values.extend(item.get("materials") or [])
    return [str(value) for value in values if value]


def validate_manifest(source, check_files=True):
    """Return ``(normalized_manifest, report)`` without changing the input."""
    meta = copy.deepcopy(source or {})
    report = {"errors": [], "warnings": [], "missing_textures": [], "schema_version": None}
    if not isinstance(meta, dict):
        report["errors"].append("Manifest root must be a JSON object")
        return {}, report

    version = meta.get("schema_version")
    if version is None:
        report["warnings"].append("Legacy manifest has no schema_version; compatibility mode is active")
        version = 0
    try:
        version = int(version)
    except (TypeError, ValueError):
        report["errors"].append("schema_version must be an integer")
        version = -1
    report["schema_version"] = version
    if version > max(SUPPORTED_SCHEMA_VERSIONS):
        report["errors"].append("Manifest schema %s is newer than the supported schema %s" % (version, max(SUPPORTED_SCHEMA_VERSIONS)))
    elif version not in SUPPORTED_SCHEMA_VERSIONS and version != 0:
        report["errors"].append("Unsupported manifest schema: %s" % version)

    asset_name = str(meta.get("asset_name") or "").strip()
    if not asset_name:
        report["errors"].append("asset_name is missing")
        asset_name = "B2H_Asset"
    meta["asset_name"] = asset_name

    materials = meta.get("materials") or {}
    if not isinstance(materials, dict):
        report["errors"].append("materials must be an object")
        materials = {}
    normalized_materials = {}
    safe_names = {}
    for key, raw_data in materials.items():
        if not isinstance(raw_data, dict):
            report["errors"].append('Material "%s" must be an object' % key)
            continue
        data = copy.deepcopy(raw_data)
        name = str(data.get("name") or key)
        safe = safe_name(name, "Material")
        if safe in safe_names and safe_names[safe] != str(key):
            report["errors"].append('Materials "%s" and "%s" resolve to the same Houdini name "%s"' % (safe_names[safe], key, safe))
            continue
        safe_names[safe] = str(key)
        data["name"] = name
        textures = data.get("textures") or {}
        if not isinstance(textures, dict):
            report["errors"].append('Material "%s": textures must be an object' % name)
            textures = {}
        normalized_textures = {}
        for role, texture_path in textures.items():
            canonical = TEXTURE_ROLE_ALIASES.get(str(role).lower(), str(role).lower())
            if canonical not in SUPPORTED_TEXTURE_ROLES:
                report["warnings"].append('Material "%s": unsupported texture role "%s" was ignored' % (name, role))
                continue
            normalized_textures[canonical] = texture_path
            if check_files and texture_path:
                resolved = resolve_texture_path(meta, texture_path)
                if not resolved or not os.path.isfile(resolved):
                    report["missing_textures"].append({"material": name, "role": canonical, "path": clean_path(texture_path)})
        data["textures"] = normalized_textures
        data["defaults"] = data.get("defaults") if isinstance(data.get("defaults"), dict) else {}
        data["hints"] = data.get("hints") if isinstance(data.get("hints"), dict) else {}
        normalized_materials[str(key)] = data
    meta["materials"] = normalized_materials

    assignments = meta.get("assignments") or []
    if not isinstance(assignments, list):
        report["errors"].append("assignments must be an array")
        assignments = []
    normalized_assignments = []
    known_materials = set(safe_names)
    aliases = meta.get("material_aliases") if isinstance(meta.get("material_aliases"), dict) else {}
    for index, raw_item in enumerate(assignments):
        if not isinstance(raw_item, dict):
            report["errors"].append("Assignment %d must be an object" % index)
            continue
        item = copy.deepcopy(raw_item)
        object_name = item.get("object_name") or item.get("safe_object_name")
        if not object_name:
            report["errors"].append("Assignment %d has no object name" % index)
            continue
        item["object_name"] = str(object_name)
        item["safe_object_name"] = str(item.get("safe_object_name") or safe_name(object_name))
        candidates = _material_candidates(item)
        resolved_candidates = []
        for candidate in candidates:
            alias = aliases.get(candidate, candidate)
            if safe_name(alias, "Material") in known_materials:
                resolved_candidates.append(alias)
            elif safe_name(candidate, "Material") in known_materials:
                resolved_candidates.append(candidate)
        item["resolved_materials"] = list(dict.fromkeys(resolved_candidates))
        if not item["resolved_materials"]:
            report["errors"].append('Assignment for "%s" references no known material' % object_name)
        elif len(item["resolved_materials"]) > 1 and not item.get("bth_material"):
            report["errors"].append(
                'Object "%s" has multiple materials but no exact split binding; enable Split Meshes By Material in Blender and export again'
                % object_name
            )
        normalized_assignments.append(item)
    meta["assignments"] = normalized_assignments

    usd_path = resolve_asset_path(meta, meta.get("usd_path"), safe_name(asset_name) + ".usdc", safe_name(asset_name) + ".usd")
    meta["__resolved_usd_path"] = usd_path
    if check_files and (not usd_path or not os.path.isfile(usd_path)):
        report["errors"].append("USD file is missing: %s" % (usd_path or meta.get("usd_path") or "not specified"))
    if report["missing_textures"]:
        report["warnings"].append("Missing textures: %d" % len(report["missing_textures"]))
    report["valid"] = not report["errors"]
    return meta, report


def report_status(report):
    if report.get("errors"):
        return "Invalid: " + report["errors"][0]
    if report.get("warnings"):
        return "Ready with %d warning(s)" % len(report["warnings"])
    return "Ready"
