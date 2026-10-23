"""Transactional, idempotent B2H asset importer for Houdini Solaris."""

import os
import traceback
import uuid

import hou

from b2h_manifest import load_manifest, safe_name, validate_manifest
from b2h_materials import build_material, setparm, settuple


IMPORTER_VERSION = "0.5.1"


def _progress(callback, fraction, message):
    if callback:
        try:
            callback(max(0.0, min(1.0, float(fraction))), str(message))
        except Exception:
            pass


def _diagnostics(meta, report):
    return {
        "status": "RUNNING",
        "asset_name": meta.get("asset_name", "Asset"),
        "geometry_ok": False,
        "expected_materials": len(meta.get("materials") or {}),
        "created_materials": 0,
        "failed_materials": [],
        "expected_assignments": len(meta.get("assignments") or []),
        "created_assignments": 0,
        "missing_textures": list(report.get("missing_textures") or []),
        "warnings": list(report.get("warnings") or []),
        "errors": [],
        "replaced_nodes": 0,
    }


def _status(diagnostics):
    complete_failure = (
        not diagnostics["geometry_ok"]
        or (diagnostics["expected_materials"] and not diagnostics["created_materials"])
        or (diagnostics["expected_assignments"] and not diagnostics["created_assignments"])
    )
    incomplete = (
        diagnostics["created_materials"] != diagnostics["expected_materials"]
        or diagnostics["created_assignments"] != diagnostics["expected_assignments"]
        or diagnostics["missing_textures"]
        or diagnostics["warnings"]
        or diagnostics["errors"]
    )
    return "FAILED" if complete_failure else ("SUCCESS WITH WARNINGS" if incomplete else "SUCCESS")


def _stage_root():
    return hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")


def _tag(node, asset_id, asset_name, role):
    node.setUserData("b2h_owner", "B2H Model Import")
    node.setUserData("b2h_asset_id", str(asset_id))
    node.setUserData("b2h_asset_name", str(asset_name))
    node.setUserData("b2h_role", str(role))
    node.setUserData("b2h_importer_version", IMPORTER_VERSION)
    return node


def _owned_nodes(stage, asset_id, asset_name, exclude=()):
    excluded = set(exclude)
    result = []
    legacy_bases = {
        safe_name(asset_name) + "_SOP_CREATE",
        safe_name(asset_name) + "_SOP_CREATE_EDITABLE",
        safe_name(asset_name) + "_MATERIAL_LIBRARY",
        safe_name(asset_name) + "_ASSIGN_MATERIALS",
    }
    for node in stage.children():
        if node in excluded:
            continue
        try:
            owned = node.userData("b2h_owner") == "B2H Model Import"
            same_id = node.userData("b2h_asset_id") == str(asset_id)
            old_tag = node.userData("b2h_asset") == str(asset_name)
            legacy_name = node.name() in legacy_bases
            if (owned and same_id) or old_tag or legacy_name:
                result.append(node)
        except Exception:
            pass
    return result


def _configure_usd_import(node, usd_path):
    path_ok = False
    for name in ("filepath1", "filepath", "file", "usdfile"):
        path_ok = setparm(node, name, usd_path) or path_ok
    if not path_ok:
        raise RuntimeError("Houdini USD Import has no supported file parameter")
    for name in ("unpack", "unpackusd", "unpackgeometry", "importasgeometry", "input_unpack"):
        setparm(node, name, 1)
    for name, value in (("geotype", "polygons"), ("geometrytype", "polygons"), ("primtype", "polygon"), ("unpack_geomtype", "polygons")):
        setparm(node, name, value)


def _create_geometry(stage, meta, asset_id, token):
    asset_name = meta["asset_name"]
    node = stage.createNode("sopcreate", safe_name(asset_name) + "_B2H_STAGING_GEO_" + token)
    _tag(node, asset_id, asset_name, "geometry")
    sopnet = node.node("sopnet") or node.createNode("sopnet", "sopnet")
    create = sopnet.node("create") or sopnet.createNode("geo", "create")
    for child in list(create.children()):
        try:
            child.destroy()
        except Exception:
            pass
    usd = create.createNode("usdimport", "usdimport1")
    _configure_usd_import(usd, meta["__resolved_usd_path"])
    last = usd
    if bool(meta.get("axis_fix_enabled", True)):
        transform = create.createNode("xform", "AXIS_FIX_X")
        transform.setInput(0, usd)
        angle = float(meta.get("axis_rotate_x", -90.0))
        if not settuple(transform, ("r", "rot", "rotate"), (angle, 0.0, 0.0)):
            setparm(transform, "rx", angle)
        last = transform
    # USD Import maps the primary st into Houdini uv. A residual st from
    # another mesh can shadow uv when SOP Create exports the merged geometry.
    uv_fix = create.createNode("python", "RESTORE_PRIMARY_UV")
    uv_fix.setInput(0, last)
    uv_fix.parm("python").set('''import hou
geo = hou.pwd().geometry()
uv = geo.findVertexAttrib("uv") or geo.findPointAttrib("uv")
if uv is not None:
    for attrib in (geo.findVertexAttrib("st"), geo.findPointAttrib("st")):
        if attrib is not None:
            attrib.destroy()
''')
    last = uv_fix
    output = create.createNode("null", "OUT_B2H_EDITABLE_USD")
    output.setInput(0, last)
    output.setDisplayFlag(True)
    output.setRenderFlag(True)
    try:
        create.layoutChildren()
    except Exception:
        pass
    return node


def _usd_prim_records(path):
    records = []
    try:
        from pxr import Usd
        stage = Usd.Stage.Open(path)
        if not stage:
            return records
        for prim in stage.Traverse():
            prim_path = str(prim.GetPath())
            leaf = str(prim.GetName())
            records.append({"path": prim_path, "leaf": leaf, "safe_leaf": safe_name(leaf)})
    except Exception as error:
        print("[B2H] USD prim inspection failed: %s" % error)
    return records


def _material_lookup(meta, created):
    lookup = {}
    materials = meta.get("materials") or {}
    for key, data in materials.items():
        canonical = safe_name(data.get("name") or key, "Material")
        if canonical not in created:
            continue
        target = created[canonical]
        for alias in [key, data.get("name")] + list(data.get("source_materials") or []):
            if alias:
                lookup[safe_name(alias, "Material")] = target
    for alias, canonical in (meta.get("material_aliases") or {}).items():
        target = created.get(safe_name(canonical, "Material"))
        if target:
            lookup[safe_name(alias, "Material")] = target
    return lookup


def _explicit_prim_paths(item):
    values = []
    for key in ("prim_path", "usd_prim_path"):
        if item.get(key):
            values.append(item[key])
    values.extend(item.get("prim_paths") or [])
    return [str(value) for value in values if str(value).startswith("/")]


def _matching_prim_paths(item, records):
    explicit = _explicit_prim_paths(item)
    if explicit:
        known = {record["path"] for record in records}
        return [path for path in explicit if not known or path in known]
    wanted = {
        safe_name(item.get("object_name")),
        safe_name(item.get("safe_object_name")),
    }
    exact = [record["path"] for record in records if record["safe_leaf"] in wanted]
    if exact:
        # Prefer the shallow object prim; USD material bindings inherit to meshes.
        shallowest = min(path.count("/") for path in exact)
        return [path for path in exact if path.count("/") == shallowest]
    return []


def _assignment_entries(meta, created, diagnostics):
    records = _usd_prim_records(meta["__resolved_usd_path"])
    lookup = _material_lookup(meta, created)
    resolved = []
    for item in meta.get("assignments") or []:
        candidates = item.get("resolved_materials") or []
        target = next((lookup.get(safe_name(name, "Material")) for name in candidates if lookup.get(safe_name(name, "Material"))), None)
        if not target:
            diagnostics["errors"].append('No created material for object "%s"' % item.get("object_name"))
            continue
        paths = _matching_prim_paths(item, records)
        if not paths:
            diagnostics["errors"].append('No exact USD prim found for object "%s"' % item.get("object_name"))
            continue
        resolved.append({"object": item.get("object_name"), "paths": paths, "material": "/materials/" + target})
    if not meta.get("assignments") and len(created) == 1:
        diagnostics["warnings"].append("Legacy single-material manifest: material assigned to all prims")
        diagnostics["expected_assignments"] = 1
        resolved.append({"object": "<legacy>", "paths": ["/**"], "material": "/materials/" + next(iter(created.values()))})
    elif not meta.get("assignments") and len(created) > 1:
        diagnostics["errors"].append("Multi-material manifest has no assignments")
        diagnostics["expected_assignments"] = len(created)
    entries = []
    for assignment_index, assignment in enumerate(resolved):
        for path in assignment["paths"]:
            entries.append((assignment_index, path, assignment["material"]))
    return resolved, entries


def _print_summary(diagnostics):
    print("====================================")
    print("B2H IMPORT STATUS:", diagnostics["status"])
    print("Geometry:", "OK" if diagnostics["geometry_ok"] else "FAILED")
    print("Materials: %d/%d" % (diagnostics["created_materials"], diagnostics["expected_materials"]))
    print("Assignments: %d/%d" % (diagnostics["created_assignments"], diagnostics["expected_assignments"]))
    print("Missing textures:", len(diagnostics["missing_textures"]))
    for message in diagnostics["warnings"]:
        print("[B2H] WARNING:", message)
    for message in diagnostics["errors"]:
        print("[B2H] ERROR:", message)
    print("====================================")


def import_asset(meta_or_path, progress=None):
    raw = load_manifest(meta_or_path) if isinstance(meta_or_path, str) else meta_or_path
    meta, report = validate_manifest(raw, check_files=True)
    if report["errors"]:
        raise RuntimeError("Invalid B2H manifest: " + "; ".join(report["errors"]))
    diagnostics = _diagnostics(meta, report)
    asset_name = meta["asset_name"]
    asset_id = meta.get("asset_id") or ("legacy:" + os.path.normcase(meta.get("__bridge_path") or asset_name))
    token = uuid.uuid4().hex[:8]
    created_nodes = []
    _progress(progress, 0.02, "Validated manifest")

    with hou.undos.group("Import or Update B2H Asset: %s" % asset_name):
        stage = _stage_root()
        try:
            geometry = _create_geometry(stage, meta, asset_id, token)
            created_nodes.append(geometry)
            diagnostics["geometry_ok"] = True
            _progress(progress, 0.18, "Imported USD geometry")

            matlib = stage.createNode("materiallibrary", safe_name(asset_name) + "_B2H_STAGING_MAT_" + token)
            _tag(matlib, asset_id, asset_name, "materials")
            created_nodes.append(matlib)
            matlib.setInput(0, geometry)
            setparm(matlib, "matpathprefix", "/materials/")

            created = {}
            materials = list((meta.get("materials") or {}).items())
            for index, (material_key, data) in enumerate(materials):
                _progress(progress, 0.20 + 0.55 * index / max(1, len(materials)), "Building material: %s" % data.get("name", material_key))
                try:
                    builder = build_material(matlib, data, meta, diagnostics)
                    canonical = safe_name(data.get("name") or material_key, "Material")
                    created[canonical] = builder.name()
                    diagnostics["created_materials"] += 1
                except Exception as error:
                    diagnostics["failed_materials"].append(str(material_key))
                    diagnostics["errors"].append('Material "%s" failed: %s' % (material_key, error))
                    traceback.print_exc()
            try:
                matlib.layoutChildren()
            except Exception:
                pass

            assign = stage.createNode("assignmaterial", safe_name(asset_name) + "_B2H_STAGING_ASSIGN_" + token)
            _tag(assign, asset_id, asset_name, "assign")
            created_nodes.append(assign)
            assign.setInput(0, matlib)
            resolved, entries = _assignment_entries(meta, created, diagnostics)
            if not setparm(assign, "nummaterials", len(entries)):
                raise RuntimeError("Could not configure Assign Material entry count")
            assignment_ok = [True] * len(resolved)
            for entry_index, (assignment_index, pattern, material_path) in enumerate(entries, start=1):
                ok = setparm(assign, "primpattern%d" % entry_index, pattern)
                ok = setparm(assign, "matspecpath%d" % entry_index, material_path) and ok
                assignment_ok[assignment_index] = assignment_ok[assignment_index] and ok
            diagnostics["created_assignments"] = sum(1 for value in assignment_ok if value)
            assign.setDisplayFlag(True)
            _progress(progress, 0.82, "Configured exact material assignments")

            diagnostics["status"] = _status(diagnostics)
            if diagnostics["status"] == "FAILED":
                raise RuntimeError("Replacement import is incomplete; the previous asset was preserved")

            # Commit only after the complete replacement network exists.
            previous = _owned_nodes(stage, asset_id, asset_name, exclude=created_nodes)
            for node in previous:
                node.destroy()
            diagnostics["replaced_nodes"] = len(previous)
            final_names = (
                (geometry, safe_name(asset_name) + "_SOP_CREATE_EDITABLE"),
                (matlib, safe_name(asset_name) + "_MATERIAL_LIBRARY"),
                (assign, safe_name(asset_name) + "_ASSIGN_MATERIALS"),
            )
            for node, name in final_names:
                try:
                    node.setName(name, unique_name=True)
                except Exception as error:
                    diagnostics["warnings"].append('Imported node kept its staging name: %s' % error)
            try:
                stage.layoutChildren(items=created_nodes)
            except Exception:
                pass
            _progress(progress, 1.0, diagnostics["status"])
            _print_summary(diagnostics)
            return {
                "sopcreate": geometry,
                "matlib": matlib,
                "assign": assign,
                "materials": created,
                "diagnostics": diagnostics,
                "meta": meta,
            }
        except Exception:
            # If commit did not happen, remove only this attempt's staging nodes.
            for node in reversed(created_nodes):
                try:
                    if node and node.parent():
                        node.destroy()
                except Exception:
                    pass
            diagnostics["status"] = "FAILED"
            _print_summary(diagnostics)
            raise
