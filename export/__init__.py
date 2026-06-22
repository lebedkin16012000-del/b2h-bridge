"""
Модуль экспорта для аддона Blender To Houdini Bridge
"""

import bpy
import os
import json
import shutil
import traceback
from typing import Any, Dict, List, Optional, Tuple
from .. import config
from ..utils import BakeLogger, safe_name, clean_material_name, get_principled, norm, ensure_dir, socket_value
from ..core import analyzer
from ..baking import bake_manager


class ExportManager:
    """Менеджер экспорта ассетов"""

    def __init__(self):
        self.temp_collections: List[bpy.types.Collection] = []

    def collect_assignments(self, objects: List[bpy.types.Object]) -> List[Dict[str, Any]]:
        """
        Собирает назначения материалов для объектов.

        Args:
            objects: Список объектов

        Returns:
            Список назначений
        """
        result = []
        for obj in objects:
            mats = []
            for slot in obj.material_slots:
                if slot.material:
                    mats.append(clean_material_name(slot.material.name))

            bth_mat = None
            try:
                bth_mat = obj.get("bth_material", None)
            except Exception:
                bth_mat = None

            if bth_mat or mats:
                result.append({
                    "object_name": obj.name,
                    "safe_object_name": safe_name(obj.name),
                    "bth_material": bth_mat,
                    "materials": [bth_mat] if bth_mat else mats,
                })
        return result

    def detect_instance_sources(self, objects):  # Упростили аннотации типов
        """
        Обнаруживает источники инстансов.

        Args:
            objects: Список объектов

        Returns:
            Словарь {имя объекта: имя источника}
        """
        mesh_map = {}
        for obj in objects:
            if obj.type != "MESH":
                continue
            key = obj.data.name
            mesh_map.setdefault(key, []).append(obj)

        result = {}
        for key, group in mesh_map.items():
            if len(group) > 1:
                for obj in group:
                    result[obj.name] = group[0].name
        return result

    def prepare_split_by_material_objects(self, objects: List[bpy.types.Object]) -> Tuple[List[bpy.types.Object], Optional[bpy.types.Collection]]:
        """
        Подготавливает разделение объектов по материалам.

        Args:
            objects: Исходные объекты

        Returns:
            Кортеж (разделенные объекты, временная коллекция)
        """
        bake_manager.ensure_object_mode()
        temp_collection = bpy.data.collections.new("BTH_TEMP_SPLIT_BY_MATERIAL")
        bpy.context.scene.collection.children.link(temp_collection)
        export_objects = []

        try:
            for obj in objects:
                if obj.type != "MESH":
                    continue

                # Создаем копию объекта
                dup = obj.copy()
                dup.data = obj.data.copy()
                dup.animation_data_clear()
                dup.name = safe_name(obj.name) + "__BTH_SPLIT_SRC"
                dup.matrix_world = obj.matrix_world.copy()
                temp_collection.objects.link(dup)

                # Разделяем по материалам
                bpy.ops.object.select_all(action="DESELECT")
                dup.select_set(True)
                bpy.context.view_layer.objects.active = dup

                try:
                    bpy.ops.object.mode_set(mode="EDIT")
                    bpy.ops.mesh.select_all(action="SELECT")
                    bpy.ops.mesh.separate(type="MATERIAL")
                    bpy.ops.object.mode_set(mode="OBJECT")
                except Exception:
                    try:
                        bpy.ops.object.mode_set(mode="OBJECT")
                    except Exception:
                        pass

                separated = [o for o in bpy.context.selected_objects if o.type == "MESH"]
                if not separated:
                    separated = [dup]

                # Обрабатываем разделенные части
                for part in separated:
                    used_indices = set()
                    try:
                        for poly in part.data.polygons:
                            used_indices.add(poly.material_index)
                    except Exception:
                        pass

                    mat_name = None
                    if used_indices:
                        idx = sorted(list(used_indices))[0]
                        if idx < len(part.material_slots) and part.material_slots[idx].material:
                            mat_name = clean_material_name(part.material_slots[idx].material.name)

                    if not mat_name:
                        for slot in part.material_slots:
                            if slot.material:
                                mat_name = clean_material_name(slot.material.name)
                                break

                    if mat_name:
                        part.name = safe_name(obj.name) + "__" + mat_name
                        part.data.name = part.name + "_mesh"
                        part["bth_material"] = mat_name

                    try:
                        if len(part.data.polygons) > 0:
                            export_objects.append(part)
                    except Exception:
                        export_objects.append(part)

            # Выделяем экспортируемые объекты
            bpy.ops.object.select_all(action="DESELECT")
            for o in export_objects:
                try:
                    o.select_set(True)
                except Exception:
                    pass

            if export_objects:
                bpy.context.view_layer.objects.active = export_objects[0]

            return export_objects, temp_collection

        except Exception as e:
            BakeLogger.log("SPLIT BY MATERIAL FAILED:", e)
            traceback.print_exc()
            return objects, temp_collection

    def cleanup_temp_collection(self, collection: Optional[bpy.types.Collection]):
        """
        Очищает временную коллекцию.

        Args:
            collection: Временная коллекция
        """
        if not collection:
            return

        try:
            for obj in list(collection.objects):
                try:
                    mesh = obj.data
                    bpy.data.objects.remove(obj, do_unlink=True)
                    if mesh and getattr(mesh, "users", 0) == 0:
                        bpy.data.meshes.remove(mesh, do_unlink=True)
                except Exception:
                    pass
            bpy.data.collections.remove(collection)
        except Exception:
            pass

    def export_usd(self, filepath: str, objects: List[bpy.types.Object]):
        """
        Экспортирует объекты в USD формате.

        Args:
            filepath: Путь для сохранения USD
            objects: Список объектов для экспорта

        Raises:
            RuntimeError: Если экспорт не удался
        """
        old_sel = [o for o in bpy.context.scene.objects if o.select_get()]
        old_active = bpy.context.view_layer.objects.active

        try:
            bpy.ops.object.select_all(action="DESELECT")
            for obj in objects:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = objects[0]

            kwargs = {
                "filepath": filepath,
                "selected_objects_only": True,
                # Materials are rebuilt from the bridge manifest by the
                # generated Houdini script.  Letting the USD exporter include
                # Blender materials makes it write a second, unused copy of
                # every source texture beside our PBR texture set.
                "export_materials": False,
                "export_uvmaps": True,
                "export_normals": True,
            }

            # Пытаемся использовать root_prim_path для новых версий Blender
            try:
                kwargs["root_prim_path"] = "/Asset"
                bpy.ops.wm.usd_export(**kwargs)
            except TypeError:
                kwargs.pop("root_prim_path", None)
                bpy.ops.wm.usd_export(**kwargs)

        finally:
            bpy.ops.object.select_all(action="DESELECT")
            for o in old_sel:
                try:
                    o.select_set(True)
                except Exception:
                    pass
            bpy.context.view_layer.objects.active = old_active

        # Проверка результата
        if not os.path.exists(filepath) or os.path.getsize(filepath) < 1024:
            raise RuntimeError(f"USD экспорт не удался или файл слишком мал: {filepath}")

    def collect_material(self, mat: bpy.types.Material, objects, texture_dir: str, settings):  # Упростили аннотации типов
        """
        Собирает информацию о материале.

        Args:
            mat: Материал
            objects: Список объектов
            texture_dir: Директория текстур
            settings: Настройки экспорта

        Returns:
            Словарь с информацией о материале
        """
        from ..utils import texture_role_score, copy_or_save_image
        from ..utils.image_utils import image_is_dark_or_bad_for_metal

        bsdf = get_principled(mat)
        name = clean_material_name(mat.name)

        # Собираем текстуры
        textures = {}
        if bsdf:
            texture_sources = [
                ("basecolor", "Base Color", "basecolor"),
                ("roughness", "Roughness", "roughness"),
                ("metallic", "Metallic", "metallic"),
                ("normal", "Normal", "normal"),
                ("opacity", "Alpha", "opacity"),
                ("emission", "Emission Color", "emission"),
            ]

            for key, socket_name, role in texture_sources:
                if socket_name in bsdf.inputs:
                    texture = analyzer.trace_image(bsdf.inputs.get(socket_name), texture_dir, role)
                    textures[key] = texture

        # Значения по умолчанию
        diffuse = list(getattr(mat, "diffuse_color", [0.5, 0.5, 0.5, 1.0]))
        color = socket_value(bsdf, "Base Color", diffuse) if bsdf else diffuse

        if isinstance(color, (float, int)):
            color = [float(color), float(color), float(color), 1.0]

        # Собираем данные материала
        data = {
            "name": name,
            "original_name": mat.name,
            "textures": textures,
            "defaults": {
                "base_color": list(color) if isinstance(color, (list, tuple)) else diffuse,
                "roughness": float(socket_value(bsdf, "Roughness", 0.55) or 0.55) if bsdf else 0.55,
                "metallic": float(socket_value(bsdf, "Metallic", 0.0) or 0.0) if bsdf else 0.0,
                "alpha": float(socket_value(bsdf, "Alpha", diffuse[3] if len(diffuse) > 3 else 1.0) or 1.0) if bsdf else (diffuse[3] if len(diffuse) > 3 else 1.0),
                "ior": float(socket_value(bsdf, "IOR", 1.45) or 1.45) if bsdf else 1.45,
                "emission_strength": float(socket_value(bsdf, "Emission Strength", 0.0) or 0.0) if bsdf else 0.0,
            },
            "hints": analyzer.classify_material(mat, bsdf) if bsdf else {},
            "intent": analyzer.material_intent_analysis(mat),
            "baked": False,
        }

        BakeLogger.log("TEXTURE PICK:", mat.name,
                      "base=", os.path.basename(textures.get("basecolor")) if textures.get("basecolor") else None,
                      "rough=", os.path.basename(textures.get("roughness")) if textures.get("roughness") else None,
                      "normal=", os.path.basename(textures.get("normal")) if textures.get("normal") else None,
                      "alpha=", os.path.basename(textures.get("opacity")) if textures.get("opacity") else None)

        # Умная обработка металлов
        try:
            if data.get("hints", {}).get("metal") and bool(getattr(settings, "metal_ignore_basecolor", True)):
                base_path = data["textures"].get("basecolor")
                if base_path and not image_is_dark_or_bad_for_metal(base_path):
                    data["metal_basecolor_ignored"] = False
                    data["metal_basecolor_kept"] = True
                else:
                    data["textures"]["basecolor"] = None
                    bc = data.get("defaults", {}).get("base_color", [0.72, 0.72, 0.72, 1.0])
                    if not bc or (isinstance(bc, list) and len(bc) >= 3 and sum(bc[:3]) / 3.0 < 0.18):
                        data["defaults"]["base_color"] = [0.72, 0.72, 0.72, 1.0]
                    data["metal_basecolor_ignored"] = True
        except Exception:
            pass

        return data

    def generate_houdini_script(self, export_dir: str, asset_name: str) -> str:
        """
        Генерирует скрипт для импорта в Houdini.

        Args:
            export_dir: Директория экспорта
            asset_name: Имя ассета

        Returns:
            Содержимое скрипта
        """
        code = r'''
import hou, os, json, re, traceback
try:
    import voptoolutils
except Exception:
    voptoolutils = None
BASE_DIR = r"__BASE_DIR__".replace("\\", "/")
ASSET_NAME = "__ASSET_NAME__"
META_PATH = os.path.join(BASE_DIR, ASSET_NAME + "_bridge.json").replace("\\", "/")
with open(META_PATH, "r", encoding="utf-8") as f:
    META = json.load(f)
USD_PATH = META["usd_path"].replace("\\", "/")
MATERIALX_DIR = META.get("materialx_dir", os.path.join(BASE_DIR, "materialx")).replace("\\", "/")
MATERIALS = META.get("materials", {})
ASSIGNMENTS = META.get("assignments", [])
AXIS_FIX_ENABLED = bool(META.get("axis_fix_enabled", True))
AXIS_ROTATE_X = float(META.get("axis_rotate_x", -90.0))
UI_SAFE_MODE = bool(META.get("houdini_ui_safe_mode", False))

def safe_name(name):
    name = str(name or "item").strip().replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9_]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if not name: name = "item"
    if name[0].isdigit(): name = "_" + name
    return name

def unique_child(parent, base):
    base = safe_name(base)
    if parent.node(base) is None: return base
    i = 1
    while parent.node("%s_%03d" % (base, i)) is not None: i += 1
    return "%s_%03d" % (base, i)

def setparm(node, name, value):
    p = node.parm(name) if node else None
    if p:
        try: p.set(value); return True
        except Exception: pass
    return False

def settuple(node, names, values):
    if not node: return False
    for name in names:
        p = node.parmTuple(name)
        if p:
            try: p.set(tuple(values)); return True
            except Exception: pass
    return False

def configure_usdimport(node):
    """Set USD Import options by UI label as well as known parm names."""
    for parm in node.parms():
        try:
            template = parm.parmTemplate()
            label = template.label().strip().lower()
            if label == "unpack":
                parm.set(1)
            elif label in {"load as", "geometry type", "import type"}:
                labels = list(template.menuLabels())
                items = list(template.menuItems())
                for index, menu_label in enumerate(labels):
                    if str(menu_label).strip().lower() == "polygons":
                        parm.set(items[index] if index < len(items) else index)
                        break
        except Exception:
            pass
def make(parent, nodetype, name):
    try: return parent.createNode(nodetype, unique_child(parent, name))
    except Exception: return None

def clean_path(path):
    if not path:
        return None
    return str(path).replace(chr(92), "/")

def stage_root():
    return hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")

def create_editable_import(stage):
    base = safe_name(ASSET_NAME)
    sopcreate = stage.createNode("sopcreate", unique_child(stage, base + "_SOP_CREATE_EDITABLE"))
    sopnet = sopcreate.node("sopnet") or sopcreate.createNode("sopnet", "sopnet")
    create = sopnet.node("create") or sopnet.createNode("geo", "create")

    for c in create.children():
        try: c.destroy()
        except Exception: pass

    usd = create.createNode("usdimport", "usdimport1")
    for parm in ["filepath1", "filepath", "file", "usdfile"]: setparm(usd, parm, USD_PATH)

    # Do not scan every parameter: on Houdini 21 that can leave the UI event
    # queue busy before the Material Library and its builders are created.
    for parm_name in ["unpack", "unpackusd", "unpackgeometry", "importasgeometry"]:
        setparm(usd, parm_name, 1)
    for parm_name, value in [("geotype", "polygons"), ("geometrytype", "polygons"), ("primtype", "polygon")]:
        setparm(usd, parm_name, value)
    configure_usdimport(usd)

    last = usd
    if AXIS_FIX_ENABLED:
        xform = create.createNode("xform", "AXIS_FIX_X")
        xform.setInput(0, usd)
        if not settuple(xform, ["r", "rot", "rotate"], [AXIS_ROTATE_X, 0, 0]): setparm(xform, "rx", AXIS_ROTATE_X)
        last = xform

    out = create.createNode("null", "OUT_EDITABLE_USD")
    out.setInput(0, last); out.setDisplayFlag(True); out.setRenderFlag(True)
    if True:
        try: create.layoutChildren()
        except Exception: pass
    return sopcreate

def find_surface(builder):
    for c in builder.children():
        if c.type().name() == "mtlxstandard_surface": return c
    return None

def input_index_by_names(node, names):
    if not node:
        return None

    names = [str(x).lower() for x in names]

    try:
        input_names = list(node.inputNames())
    except Exception:
        input_names = []

    for i, n in enumerate(input_names):
        low = str(n).lower()
        if low in names:
            return i

    for i, n in enumerate(input_names):
        low = str(n).lower()
        for wanted in names:
            if wanted in low or low in wanted:
                return i

    # Houdini 21 MaterialX standard_surface common fallback indices.
    fallback = {
        "base_color": 1,
        "basecolor": 1,
        "specular_roughness": 9,
        "metalness": 3,
        "opacity": 38,
        "emission_color": 36,
        "normal": 40,
    }

    for wanted in names:
        if wanted in fallback:
            return fallback[wanted]

    return None

def connect_mtlx(builder, surface, input_name, node):
    if not surface or not node:
        return False

    aliases = {
        "base_color": ["base_color", "base", "basecolor"],
        "specular_roughness": ["specular_roughness", "roughness"],
        "metalness": ["metalness", "metallic"],
        "opacity": ["opacity", "alpha"],
        "emission_color": ["emission_color", "emission"],
        "normal": ["normal"],
    }

    names = aliases.get(input_name, [input_name])

    for n in names:
        try:
            surface.setNamedInput(n, node, 0)
            return True
        except Exception:
            pass

    # Robust fallback by input name.
    try:
        input_names = list(surface.inputNames())
    except Exception:
        input_names = []

    for wanted in names:
        for idx, inp_name in enumerate(input_names):
            if str(inp_name).lower() == wanted.lower():
                try:
                    surface.setInput(idx, node, 0)
                    return True
                except Exception:
                    pass

    # Last fallback for Houdini 21 MaterialX standard surface.
    fallback = {
        "base_color": 1,
        "metalness": 3,
        "specular_roughness": 9,
        "opacity": 38,
        "emission_color": 36,
        "normal": 40,
    }

    if input_name in fallback:
        try:
            surface.setInput(fallback[input_name], node, 0)
            return True
        except Exception:
            pass

    print("CONNECT FAILED:", input_name, "->", surface.path())
    return False

def apply_defaults(surface, data):
    d = data.get("defaults", {}); hints = data.get("hints", {})
    color = d.get("base_color", [0.5,0.5,0.5,1])
    if isinstance(color, list) and len(color) >= 3: settuple(surface, ["base_color", "basecolor"], color[:3])
    setparm(surface, "specular_roughness", float(d.get("roughness", 0.55)))
    setparm(surface, "metalness", float(d.get("metallic", 0.0)))
    setparm(surface, "ior", float(d.get("ior", 1.45)))
    if hints.get("metal"):
        setparm(surface, "metalness", 1.0); setparm(surface, "specular", 1.0)
    if hints.get("glass"):
        setparm(surface, "opacity", 1.0); setparm(surface, "thin_walled", 0); setparm(surface, "transmission", 1.0); setparm(surface, "transmission_weight", 1.0); setparm(surface, "specular_roughness", 0.02)
    if hints.get("foliage") or hints.get("alpha"):
        setparm(surface, "thin_walled", 1); setparm(surface, "metalness", 0.0)

def create_karmamtlx_builder(matlib, name):
    if voptoolutils:
        masks = []
        if hasattr(voptoolutils, "KARMAMTLX_TAB_MASK"):
            masks.append(voptoolutils.KARMAMTLX_TAB_MASK)
        if hasattr(voptoolutils, "KARMA"):
            masks.append(voptoolutils.KARMA)

        for mask in masks:
            try:
                return voptoolutils._setupMtlXBuilderSubnet(
                    destination_node=matlib,
                    name=unique_child(matlib, name),
                    mask=mask,
                    folder_label="Karma Material Builder"
                )
            except TypeError:
                try:
                    return voptoolutils._setupMtlXBuilderSubnet(
                        destination_node=matlib,
                        name=unique_child(matlib, name),
                        mask=mask
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

    try:
        builder.createNode("subinput", "inputs")
    except Exception:
        pass

    surface = builder.createNode("mtlxstandard_surface", "mtlxstandard_surface")

    try:
        disp = builder.createNode("mtlxdisplacement", "mtlxdisplacement")
    except Exception:
        disp = None

    try:
        props = builder.createNode("kma_material_properties", "material_properties")
    except Exception:
        props = None

    try:
        out = builder.createNode("suboutput", "Material_Outputs_and_AOVs")
        out.setInput(0, surface, 0)
        if disp:
            try:
                out.setInput(1, disp, 0)
            except Exception:
                pass
        if props:
            try:
                out.setInput(2, props, 0)
            except Exception:
                pass
    except Exception:
        pass

    return builder

def ensure_material_outputs(builder, surface):
    # Houdini 21 can create a builder whose Material Outputs node is not wired
    # when the subnet was created from Python.  Wire it explicitly so the
    # builder remains a valid Karma MaterialX material.
    if not builder or not surface:
        return
    outputs = []
    for child in builder.children():
        try:
            if child.type().name() in {"suboutput", "subnetconnector"} or "output" in child.name().lower() or "aov" in child.name().lower():
                outputs.append(child)
        except Exception:
            pass
    if not outputs:
        try:
            outputs.append(builder.createNode("suboutput", "Material_Outputs_and_AOVs"))
        except Exception:
            return
    for output in outputs:
        try:
            output.setInput(0, surface, 0)
            return
        except Exception:
            try:
                output.setNamedInput("surface", surface, 0)
                return
            except Exception:
                pass

def build_material(matlib, data):
    name = safe_name(data.get("name", "Material"))
    builder = create_karmamtlx_builder(matlib, name)

    surface = find_surface(builder)
    if not surface:
        surface = make(builder, "mtlxstandard_surface", "mtlxstandard_surface")

    apply_defaults(surface, data)

    parameter_node = make(builder, "parameter", "uv_tiling")
    if parameter_node:
        try:
            p0 = surface.position()
            parameter_node.setPosition(hou.Vector2(p0[0] - 11, p0[1]))
        except Exception:
            pass
        setparm(parameter_node, "parmscope", "subnet")
        setparm(parameter_node, "floatdef", 1.0)
        setparm(parameter_node, "rangeflt1", 0.0)
        setparm(parameter_node, "rangeflt2", 10.0)

    tex = data.get("textures", {})
    float_textures = {"roughness", "metallic", "opacity"}
    image_nodes = {}

    texture_map = {
        "basecolor": ("base_color", "color3"),
        "roughness": ("specular_roughness", "float"),
        "metallic": ("metalness", "float"),
        "opacity": ("opacity", "float"),
        "emission": ("emission_color", "color3"),
        "normal": ("normal", "vector3"),
    }

    try:
        p0 = surface.position()
        y = p0[1]
    except Exception:
        y = 0

    for role, (surface_input, signature) in texture_map.items():
        path = tex.get(role)
        path = clean_path(path)
        if not path or not os.path.exists(path):
            continue

        img = make(builder, "mtlxtiledimage", "image_" + role)
        if not img:
            img = make(builder, "mtlximage", "image_" + role)
        if not img:
            continue

        try:
            img.setPosition(hou.Vector2(surface.position()[0] - 8, y))
            y -= 2.4
        except Exception:
            pass

        setparm(img, "file", path)
        setparm(img, "signature", signature)
        if role == "normal":
            for parm_name in ("filecolorspace", "colorspace", "color_space"):
                setparm(img, parm_name, "raw")
        if parameter_node:
            try:
                img.setInput(3, parameter_node, 0)
            except Exception:
                pass

        image_nodes[role] = img

    if "basecolor" in image_nodes and not data.get("metal_basecolor_ignored", False):
        connect_mtlx(builder, surface, "base_color", image_nodes["basecolor"])

    if data.get("metal_basecolor_ignored", False) and "basecolor" in image_nodes:
        try:
            image_nodes["basecolor"].destroy()
            del image_nodes["basecolor"]
        except Exception:
            pass

    if "roughness" in image_nodes:
        connect_mtlx(builder, surface, "specular_roughness", image_nodes["roughness"])

    if "metallic" in image_nodes:
        connect_mtlx(builder, surface, "metalness", image_nodes["metallic"])

    if "opacity" in image_nodes:
        connect_mtlx(builder, surface, "opacity", image_nodes["opacity"])
        setparm(surface, "thin_walled", 1)
        setparm(surface, "opacity_threshold", 0.35)

    if "emission" in image_nodes:
        connect_mtlx(builder, surface, "emission_color", image_nodes["emission"])
        setparm(surface, "emission", max(float(data.get("defaults", {}).get("emission_strength", 1.0)), 0.5))

    if "normal" in image_nodes:
        nmap = make(builder, "mtlxnormalmap", "normal_converter")
        if nmap:
            try:
                nmap.setPosition(hou.Vector2(image_nodes["normal"].position()[0] + 2, image_nodes["normal"].position()[1]))
            except Exception:
                pass
            try:
                nmap.setInput(0, image_nodes["normal"], 0)
            except Exception:
                pass
            for parm_name in ("space", "normalspace", "tangentspace"):
                setparm(nmap, parm_name, "tangent")
            connect_mtlx(builder, surface, "normal", nmap)

    ensure_material_outputs(builder, surface)
    if True:
        try: builder.layoutChildren()
        except Exception: pass

    return builder

stage = stage_root()
sopcreate = create_editable_import(stage)
matlib = stage.createNode("materiallibrary", unique_child(stage, safe_name(ASSET_NAME) + "_MATERIAL_LIBRARY"))
matlib.setInput(0, sopcreate); setparm(matlib, "matpathprefix", "/materials/")
created = {}
for mat_name, data in MATERIALS.items():
    try:
        b = build_material(matlib, data); created[safe_name(data.get("name", mat_name))] = b.name(); print("CREATED MATERIAL:", b.name())
    except Exception as e:
        print("FAILED MATERIAL:", mat_name, e); traceback.print_exc()
if True:
    try: matlib.layoutChildren()
    except Exception: pass

assign = stage.createNode("assignmaterial", unique_child(stage, safe_name(ASSET_NAME) + "_ASSIGN_MATERIALS"))
assign.setInput(0, matlib)
entries = []
for item in ASSIGNMENTS:
    obj = item.get("safe_object_name") or safe_name(item.get("object_name", ""))
    target = None

    material_candidates = []
    if item.get("bth_material"):
        material_candidates.append(item.get("bth_material"))
    material_candidates.extend(item.get("materials", []))

    for m in material_candidates:
        sm = safe_name(m)
        if sm in created:
            target = created[sm]
            break

    if target:
        entries.append(("/**/*%s*" % obj, "/materials/%s" % target))
        for m in material_candidates:
            sm = safe_name(m)
            entries.append(("/**/*%s*" % sm, "/materials/%s" % target))
            entries.append(("/**/*__%s*" % sm, "/materials/%s" % target))
if not entries and created: entries.append(("/**", "/materials/%s" % list(created.values())[0]))
setparm(assign, "nummaterials", len(entries))
for i, (pattern, mpath) in enumerate(entries, start=1): setparm(assign, "primpattern%d" % i, pattern); setparm(assign, "matspecpath%d" % i, mpath)
assign.setDisplayFlag(True)
# Arrange only nodes created by this bridge. Existing /stage networks stay untouched.
try:
    stage.layoutChildren(items=[sopcreate, matlib, assign])
except Exception:
    pass
print("====================================")
print("DONE STABLE PBR BRIDGE")
print("USD:", USD_PATH)
print("MATERIALS:", list(created.keys()))
print("EDITABLE SOP:", sopcreate.path())
print("MATERIAL LIBRARY:", matlib.path())
print("MATERIALX DIR:", MATERIALX_DIR)
print("INSTANCE MODE:", META.get("export_as_instances", False))
print("UDIM MODE:", META.get("udim_mode", False))
print("====================================")
'''
        return code.replace("__BASE_DIR__", norm(export_dir)).replace("__ASSET_NAME__", asset_name)


# Глобальный экземпляр менеджера экспорта
export_manager = ExportManager()
