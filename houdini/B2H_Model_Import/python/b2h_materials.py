"""Karma MaterialX construction for B2H manifests."""

import os

import hou

try:
    import voptoolutils
except Exception:
    voptoolutils = None

from b2h_manifest import resolve_texture_path, safe_name


COLOR_ROLES = {"basecolor", "emission"}
FLOAT_ROLES = {"roughness", "metallic", "opacity", "transmission", "ior", "displacement", "ao"}
INPUT_ALIASES = {
    "base_color": ("base_color", "base", "basecolor"),
    "specular_roughness": ("specular_roughness", "roughness"),
    "metalness": ("metalness", "metallic"),
    "opacity": ("opacity", "alpha"),
    "emission_color": ("emission_color", "emission"),
    "transmission": ("transmission", "transmission_weight"),
    "specular_IOR": ("specular_IOR", "specular_ior", "ior"),
    "normal": ("normal",),
}


def setparm(node, name, value):
    parm = node.parm(name) if node else None
    if parm is None:
        return False
    try:
        parm.set(value)
        return True
    except Exception:
        return False


def settuple(node, names, values):
    if not node:
        return False
    for name in names:
        parm = node.parmTuple(name)
        if parm:
            try:
                parm.set(tuple(values))
                return True
            except Exception:
                pass
    return False


def unique_child(parent, base):
    base = safe_name(base)
    if parent.node(base) is None:
        return base
    index = 1
    while parent.node("%s_%03d" % (base, index)) is not None:
        index += 1
    return "%s_%03d" % (base, index)


def make(parent, node_type, name):
    try:
        return parent.createNode(node_type, unique_child(parent, name))
    except Exception:
        return None


def _find_child(builder, type_name):
    for child in builder.children():
        try:
            if child.type().name() == type_name:
                return child
        except Exception:
            pass
    return None


def _builder(matlib, name):
    if voptoolutils:
        masks = []
        for attr in ("KARMAMTLX_TAB_MASK", "KARMA"):
            if hasattr(voptoolutils, attr):
                masks.append(getattr(voptoolutils, attr))
        for mask in masks:
            try:
                return voptoolutils._setupMtlXBuilderSubnet(
                    destination_node=matlib,
                    name=unique_child(matlib, name),
                    mask=mask,
                    folder_label="Karma Material Builder",
                )
            except TypeError:
                try:
                    return voptoolutils._setupMtlXBuilderSubnet(
                        destination_node=matlib, name=unique_child(matlib, name), mask=mask
                    )
                except Exception:
                    pass
            except Exception:
                pass
    builder = matlib.createNode("subnet", unique_child(matlib, name))
    try:
        builder.setMaterialFlag(True)
    except Exception:
        pass
    make(builder, "subinput", "inputs")
    make(builder, "mtlxstandard_surface", "mtlxstandard_surface")
    make(builder, "mtlxdisplacement", "mtlxdisplacement")
    make(builder, "kma_material_properties", "material_properties")
    make(builder, "suboutput", "Material_Outputs_and_AOVs")
    return builder


def _connect(node, input_name, source, output_index=0):
    if not node or not source:
        return False
    names = INPUT_ALIASES.get(input_name, (input_name,))
    for name in names:
        try:
            node.setNamedInput(name, source, output_index)
            return True
        except Exception:
            pass
    try:
        input_names = [str(name).lower() for name in node.inputNames()]
    except Exception:
        input_names = []
    for wanted in names:
        wanted = str(wanted).lower()
        for index, actual in enumerate(input_names):
            if actual == wanted:
                try:
                    node.setInput(index, source, output_index)
                    return True
                except Exception:
                    pass
    return False


def _wire_outputs(builder, surface, displacement=None):
    outputs = []
    for child in builder.children():
        try:
            name = child.name().lower()
            if child.type().name() in ("suboutput", "subnetconnector") or "output" in name or "aov" in name:
                outputs.append(child)
        except Exception:
            pass
    if not outputs:
        output = make(builder, "suboutput", "Material_Outputs_and_AOVs")
        if output:
            outputs.append(output)
    for output in outputs:
        surface_ok = False
        for method in (
            lambda: output.setNamedInput("surface", surface, 0),
            lambda: output.setInput(0, surface, 0),
        ):
            try:
                method()
                surface_ok = True
                break
            except Exception:
                pass
        if not surface_ok:
            continue
        if displacement:
            for method in (
                lambda: output.setNamedInput("displacement", displacement, 0),
                lambda: output.setInput(1, displacement, 0),
            ):
                try:
                    method()
                    break
                except Exception:
                    pass
        return True
    return False


def _apply_defaults(surface, data):
    defaults = data.get("defaults") or {}
    hints = data.get("hints") or {}
    color = defaults.get("base_color", (0.5, 0.5, 0.5, 1.0))
    if isinstance(color, (list, tuple)) and len(color) >= 3:
        settuple(surface, ("base_color", "basecolor"), color[:3])
    scalar_defaults = {
        "specular_roughness": defaults.get("roughness", 0.55),
        "metalness": defaults.get("metallic", 0.0),
        "specular_IOR": defaults.get("ior", 1.45),
        "transmission": defaults.get("transmission", 0.0),
        "emission": defaults.get("emission_strength", 0.0),
    }
    for name, value in scalar_defaults.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        for alias in INPUT_ALIASES.get(name, (name,)):
            if setparm(surface, alias, number):
                break
    alpha = defaults.get("alpha", 1.0)
    try:
        alpha = float(alpha)
        if not settuple(surface, ("opacity",), (alpha, alpha, alpha)):
            setparm(surface, "opacity", alpha)
    except (TypeError, ValueError):
        pass
    if hints.get("metal"):
        setparm(surface, "metalness", 1.0)
    if hints.get("glass"):
        setparm(surface, "thin_walled", 0)
        setparm(surface, "transmission", 1.0)
        setparm(surface, "transmission_weight", 1.0)
        setparm(surface, "specular_roughness", 0.02)
    if hints.get("foliage") or hints.get("alpha"):
        setparm(surface, "thin_walled", 1)
        setparm(surface, "metalness", 0.0)


def _image_node(builder, role, path):
    image = make(builder, "mtlxtiledimage", "image_" + role) or make(builder, "mtlximage", "image_" + role)
    if not image:
        raise RuntimeError("Could not create MaterialX image for %s" % role)
    if not setparm(image, "file", path):
        raise RuntimeError("Could not set %s texture path" % role)
    signature = "color3" if role in COLOR_ROLES else ("vector3" if role == "normal" else "float")
    setparm(image, "signature", signature)
    if role not in COLOR_ROLES:
        for parm_name in ("filecolorspace", "colorspace", "color_space"):
            setparm(image, parm_name, "raw")
    return image


def build_material(matlib, data, meta, diagnostics):
    """Build one complete MaterialX material or raise and remove partial nodes."""
    name = safe_name(data.get("name"), "Material")
    builder = _builder(matlib, name)
    if not builder:
        raise RuntimeError("Could not create MaterialX builder")
    try:
        surface = _find_child(builder, "mtlxstandard_surface") or make(builder, "mtlxstandard_surface", "mtlxstandard_surface")
        if not surface:
            raise RuntimeError("Could not create MaterialX standard_surface")
        displacement = _find_child(builder, "mtlxdisplacement")
        _apply_defaults(surface, data)

        images = {}
        y = 0.0
        try:
            y = surface.position()[1]
        except Exception:
            pass
        for role, source_path in (data.get("textures") or {}).items():
            path = resolve_texture_path(meta, source_path)
            if not path or not os.path.isfile(path):
                diagnostics["missing_textures"].append({"material": name, "role": role, "path": source_path})
                continue
            image = _image_node(builder, role, path)
            try:
                image.setPosition(hou.Vector2(surface.position()[0] - 8, y))
                y -= 2.3
            except Exception:
                pass
            images[role] = image

        base_source = images.get("basecolor")
        if base_source and images.get("ao"):
            multiply = make(builder, "mtlxmultiply", "basecolor_times_ao")
            if multiply:
                multiply.setInput(0, base_source, 0)
                multiply.setInput(1, images["ao"], 0)
                base_source = multiply
        elif not base_source and images.get("ao"):
            base_source = images["ao"]
        if base_source and not data.get("metal_basecolor_ignored", False):
            if not _connect(surface, "base_color", base_source):
                raise RuntimeError("Could not connect basecolor")

        direct = {
            "roughness": "specular_roughness",
            "metallic": "metalness",
            "opacity": "opacity",
            "emission": "emission_color",
            "transmission": "transmission",
            "ior": "specular_IOR",
        }
        for role, input_name in direct.items():
            if role in images and not _connect(surface, input_name, images[role]):
                raise RuntimeError("Could not connect %s" % role)
        if "opacity" in images:
            setparm(surface, "thin_walled", 1)
            setparm(surface, "opacity_threshold", 0.35)
        if "emission" in images:
            strength = max(float((data.get("defaults") or {}).get("emission_strength", 1.0) or 1.0), 0.001)
            setparm(surface, "emission", strength)
        if "normal" in images:
            normal = make(builder, "mtlxnormalmap", "normal_converter")
            if not normal:
                raise RuntimeError("Could not create normal-map converter")
            normal.setInput(0, images["normal"], 0)
            if not _connect(surface, "normal", normal):
                raise RuntimeError("Could not connect normal map")
        if "displacement" in images:
            displacement = displacement or make(builder, "mtlxdisplacement", "mtlxdisplacement")
            if not displacement:
                raise RuntimeError("Could not create displacement node")
            displacement.setInput(0, images["displacement"], 0)
            scale = float((data.get("defaults") or {}).get("displacement_scale", 0.01) or 0.01)
            setparm(displacement, "scale", scale)

        if not _wire_outputs(builder, surface, displacement if "displacement" in images else None):
            raise RuntimeError("Could not wire MaterialX outputs")
        try:
            builder.layoutChildren()
        except Exception:
            pass
        return builder
    except Exception:
        try:
            builder.destroy()
        except Exception:
            pass
        raise
