import bpy, os, json
from typing import Dict, Any
from ..utils import norm, BakeLogger
RELEASE_NAME = "B2H Bridge v4.8.3 Beta"

def asset_relpath(path: str, base_dir: str):
    if not path:
        return path
    try:
        return os.path.relpath(path, base_dir).replace("\\", "/")
    except Exception:
        return norm(path)


def resolve_export_dir(path: str) -> str:
    if path and (not str(path).startswith("//")):
        return bpy.path.abspath(path)
    if getattr(bpy.data, "filepath", ""):
        return bpy.path.abspath(path)
    return os.path.join(os.path.expanduser("~"), "Documents", "B2H_Exports")


def materials_with_relative_paths(materials: Dict[str, Any], base_dir: str) -> Dict[str, Any]:
    portable = json.loads(json.dumps(materials, ensure_ascii=False))
    for material in portable.values():
        textures = material.get("textures", {}) or {}
        for role, path in list(textures.items()):
            if path:
                textures[role] = asset_relpath(path, base_dir)
    return portable


def write_export_report(report_path: str, asset_name: str, materials: Dict[str, Any],
                        usd_path: str, texture_dir: str, materialx_dir: str,
                        script_path: str) -> None:
    """Write a human-readable export summary without changing export data."""
    expected_channels = ("basecolor", "roughness", "metallic", "normal", "opacity", "emission",
                         "ior", "transmission")
    lines = [
        RELEASE_NAME,
        "=" * len(RELEASE_NAME),
        f"Asset: {asset_name}",
        f"USD: {norm(usd_path)}",
        f"Textures: {norm(texture_dir)}",
        f"MaterialX: {norm(materialx_dir)}",
        f"Generated Houdini import script: {norm(script_path)}",
        "",
        f"Materials found ({len(materials)}):",
    ]
    lines.extend(f"- {name}" for name in materials) or lines.append("- None")
    lines.append("")
    lines.append("Exported texture paths:")
    texture_lines = []
    empty_paths = []
    baked_materials = []
    for material_name, material_data in materials.items():
        textures = material_data.get("textures", {}) or {}
        if material_data.get("baked"):
            baked_materials.append(material_name)
        for channel, path in textures.items():
            if path:
                texture_lines.append(f"- {material_name} | {channel}: {norm(path)}")
            else:
                empty_paths.append(f"- {material_name} | {channel}: empty")
        for channel in expected_channels:
            if channel not in textures:
                empty_paths.append(f"- {material_name} | {channel}: empty")
    lines.extend(texture_lines or ["- No texture paths exported."])
    lines.append("")
    lines.append("Empty texture paths:")
    lines.extend(empty_paths or ["- None"])
    lines.append("")
    lines.append("Materials baked:")
    lines.extend(f"- {name}" for name in baked_materials) or lines.append("- None")
    lines.append("")
    lines.append("Bake log:")
    lines.extend(BakeLogger.get_log() or ["- No bake log entries."])
    with open(report_path, "w", encoding="utf-8") as report_file:
        report_file.write("\n".join(lines) + "\n")


