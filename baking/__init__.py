"""
Модуль запекания текстур для аддона Blender To Houdini Bridge
"""

import bpy
import os
from typing import Any, Dict, List, Optional
from .. import config
from ..utils import BakeLogger, safe_name, clean_material_name, norm, ensure_dir, unique_path, normalize_texture_name
from ..core import analyzer


class BakeManager:
    """Менеджер запекания текстур"""

    def __init__(self):
        self.active_bakes: Dict[str, Any] = {}

    def ensure_object_mode(self):
        """Переключает в режим объекта"""
        try:
            if bpy.ops.object.mode_set.poll():
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass

    def ensure_uv(self, obj: bpy.types.Object, auto_uv: bool = True) -> bool:
        """
        Проверяет и создает UV развертку при необходимости.

        Args:
            obj: Объект
            auto_uv: Создавать UV автоматически

        Returns:
            True если UV существуют или созданы
        """
        if obj.type != "MESH":
            return False

        if obj.data.uv_layers:
            obj.data.uv_layers.active = obj.data.uv_layers[0]
            return True

        if not auto_uv:
            BakeLogger.log("NO UV:", obj.name)
            return False

        old_active = bpy.context.view_layer.objects.active
        old_sel = [o for o in bpy.context.scene.objects if o.select_get()]

        try:
            self.ensure_object_mode()
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.02)
            bpy.ops.object.mode_set(mode="OBJECT")
            BakeLogger.log("AUTO UV:", obj.name)
            return bool(obj.data.uv_layers)
        except Exception as e:
            BakeLogger.log("AUTO UV FAILED:", obj.name, e)
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass
            return False
        finally:
            bpy.ops.object.select_all(action="DESELECT")
            for o in old_sel:
                try:
                    o.select_set(True)
                except Exception:
                    pass
            bpy.context.view_layer.objects.active = old_active

    def set_active_material_slot(self, obj: bpy.types.Object, mat: bpy.types.Material) -> bool:
        """
        Устанавливает активный материал слот для объекта.

        Args:
            obj: Объект
            mat: Материал

        Returns:
            True если успешно
        """
        for i, slot in enumerate(obj.material_slots):
            if slot.material == mat:
                obj.active_material_index = i
                return True
        return False

    def create_bake_image(self, mat: bpy.types.Material, channel: str,
                         texture_dir: str, resolution: int,
                         normal_exr: bool = False) -> tuple:
        """
        Создает изображение для запекания.

        Args:
            mat: Материал
            channel: Канал запекания
            texture_dir: Директория для текстуры
            resolution: Разрешение текстуры
            normal_exr: Сохранять нормали как EXR

        Returns:
            Кортеж (изображение, путь)
        """
        mat_name = clean_material_name(mat.name)

        if channel == "normal" and normal_exr:
            filename = f"{mat_name}_normal.exr"
            fmt = "OPEN_EXR"
            float_buffer = True
        else:
            filename = f"{mat_name}_{channel}.png"
            fmt = "PNG"
            float_buffer = False

        path = unique_path(
            texture_dir,
            normalize_texture_name(filename, force_ext=".exr" if fmt == "OPEN_EXR" else ".png")
        )

        img = bpy.data.images.new(
            mat_name + "_" + channel,
            resolution,
            resolution,
            alpha=True,
            float_buffer=float_buffer
        )
        img.filepath_raw = path
        img.file_format = fmt

        return img, path

    def create_bake_target(self, mat: bpy.types.Material, image: bpy.types.Image) -> bpy.types.Node:
        """
        Создает узел для запекания в материале.

        Args:
            mat: Материал
            image: Изображение для запекания

        Returns:
            Узел для запекания
        """
        mat.use_nodes = True
        node = mat.node_tree.nodes.new(type="ShaderNodeTexImage")
        node.name = "BTH_BAKE_TARGET"
        node.label = "BTH Bake Target"
        node.image = image

        for n in mat.node_tree.nodes:
            n.select = False
        node.select = True
        mat.node_tree.nodes.active = node

        return node

    def find_principled_input(self, mat: bpy.types.Material, channel: str):
        """
        Находит вход Principled BSDF для канала.

        Args:
            mat: Материал
            channel: Канал (basecolor, roughness и т.д.)

        Returns:
            Сокет или None
        """
        from ..utils import get_principled
        bsdf = get_principled(mat)
        if not bsdf:
            return None

        channel_map = {
            "basecolor": "Base Color",
            "roughness": "Roughness",
            "metallic": "Metallic",
            "opacity": "Alpha",
            "emission": "Emission Color",
        }

        socket_name = channel_map.get(channel)
        if socket_name:
            return bsdf.inputs.get(socket_name)

        return None

    def find_material_output(self, mat: bpy.types.Material):
        """
        Находит выход материала.

        Args:
            mat: Материал

        Returns:
            Узел выхода материала или None
        """
        if not mat or not mat.use_nodes:
            return None

        for n in mat.node_tree.nodes:
            if n.type == "OUTPUT_MATERIAL":
                return n

        return None

    def make_emit_bake_override(self, mat: bpy.types.Material, channel: str) -> Optional[Dict[str, Any]]:
        """
        Создает временную структуру для запекания через Emission.

        Args:
            mat: Материал
            channel: Канал для запекания

        Returns:
            Состояние для восстановления или None
        """
        if not mat or not mat.use_nodes:
            return None

        nt = mat.node_tree
        out = self.find_material_output(mat)
        if not out:
            return None

        surface = out.inputs.get("Surface")
        if not surface:
            return None

        # Сохраняем оригинальные соединения
        original_links = []
        for link in list(surface.links):
            original_links.append((link.from_socket, link.to_socket))
            nt.links.remove(link)

        # Создаем Emission узел для запекания
        emit = nt.nodes.new(type="ShaderNodeEmission")
        emit.name = "BTH_EMIT_BAKE_OVERRIDE"
        emit.label = "BTH Emit Bake Override"

        try:
            emit.inputs["Strength"].default_value = 1.0
        except Exception:
            pass

        source = self.find_principled_input(mat, channel)
        helper_nodes = []

        if source:
            if source.is_linked:
                from_socket = source.links[0].from_socket

                # Для скалярных каналов преобразуем в цвет
                if channel in {"roughness", "metallic", "opacity"}:
                    combine = nt.nodes.new(type="ShaderNodeCombineColor")
                    combine.name = "BTH_FLOAT_TO_COLOR"
                    combine.label = "BTH Float To Color"
                    helper_nodes.append(combine)

                    for input_name in ["Red", "Green", "Blue"]:
                        try:
                            nt.links.new(from_socket, combine.inputs[input_name])
                        except Exception:
                            pass

                    try:
                        nt.links.new(combine.outputs["Color"], emit.inputs["Color"])
                    except Exception:
                        pass
                else:
                    try:
                        nt.links.new(from_socket, emit.inputs["Color"])
                    except Exception:
                        pass
            else:
                # Используем значение по умолчанию
                try:
                    value = source.default_value
                    if isinstance(value, float):
                        emit.inputs["Color"].default_value = (value, value, value, 1.0)
                    else:
                        vals = list(value)
                        if len(vals) >= 3:
                            emit.inputs["Color"].default_value = (
                                vals[0], vals[1], vals[2],
                                vals[3] if len(vals) > 3 else 1.0
                            )
                except Exception:
                    pass

        # Подключаем Emission к выходу
        try:
            nt.links.new(emit.outputs["Emission"], surface)
        except Exception:
            pass

        return {
            "surface": surface,
            "original_links": original_links,
            "nodes": [emit] + helper_nodes,
        }

    def restore_emit_bake_override(self, mat: bpy.types.Material, state: Dict[str, Any]):
        """
        Восстанавливает оригинальную структуру материала.

        Args:
            mat: Материал
            state: Состояние для восстановления
        """
        if not state or not mat or not mat.use_nodes:
            return

        nt = mat.node_tree
        surface = state.get("surface")

        try:
            if surface:
                for link in list(surface.links):
                    nt.links.remove(link)

            # Восстанавливаем оригинальные соединения
            for from_socket, to_socket in state.get("original_links", []):
                try:
                    nt.links.new(from_socket, to_socket)
                except Exception:
                    pass

            # Удаляем временные узлы
            for n in state.get("nodes", []):
                try:
                    nt.nodes.remove(n)
                except Exception:
                    pass
        except Exception:
            pass

    def setup_bake_render(self, samples: int, use_gpu: bool = True):  # Упростили аннотации типов
        """
        Настраивает рендер для запекания.

        Args:
            samples: Количество сэмплов
            use_gpu: Использовать GPU

        Returns:
            Словарь с оригинальными настройками
        """
        scene = bpy.context.scene
        old = {"engine": scene.render.engine}
        scene.render.engine = "CYCLES"

        try:
            old["samples"] = scene.cycles.samples
            scene.cycles.samples = int(samples)
        except Exception:
            pass

        try:
            old["device"] = scene.cycles.device
            if use_gpu:
                scene.cycles.device = "GPU"
        except Exception:
            pass

        # Настройка GPU устройств
        try:
            prefs = bpy.context.preferences.addons.get("cycles")
            if prefs and use_gpu:
                cprefs = prefs.preferences
                old["compute_device_type"] = getattr(cprefs, "compute_device_type", None)

                # Пробуем разные типы устройств
                for dev_type in ["OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"]:
                    try:
                        cprefs.compute_device_type = dev_type
                        break
                    except Exception:
                        pass

                # Включаем все доступные устройства
                try:
                    cprefs.get_devices()
                    for d in cprefs.devices:
                        d.use = True
                except Exception:
                    pass
        except Exception:
            pass

        try:
            old["bake_clear"] = scene.render.bake.use_clear
            old["normal_space"] = scene.render.bake.normal_space
            old["normal_r"] = scene.render.bake.normal_r
            old["normal_g"] = scene.render.bake.normal_g
            old["normal_b"] = scene.render.bake.normal_b
            scene.render.bake.use_clear = True
            scene.render.bake.normal_space = "TANGENT"
            scene.render.bake.normal_r = "POS_X"
            scene.render.bake.normal_g = "POS_Y"
            scene.render.bake.normal_b = "POS_Z"
        except Exception:
            pass

        return old

    def restore_bake_render(self, old: Dict[str, Any]):
        """
        Восстанавливает оригинальные настройки рендера.

        Args:
            old: Словарь с оригинальными настройками
        """
        scene = bpy.context.scene

        try:
            scene.render.engine = old["engine"]
        except Exception:
            pass

        try:
            if "samples" in old:
                scene.cycles.samples = old["samples"]
        except Exception:
            pass

        try:
            if "device" in old:
                scene.cycles.device = old["device"]
        except Exception:
            pass

        try:
            if "bake_clear" in old:
                scene.render.bake.use_clear = old["bake_clear"]
            for key in ("normal_space", "normal_r", "normal_g", "normal_b"):
                if key in old:
                    setattr(scene.render.bake, key, old[key])
        except Exception:
            pass

    def existing_bake_path(self, texture_dir: str, mat_name: str,
                          channel: str, exr_normals: bool = True) -> str:
        """
        Получает путь для запеченной текстуры.

        Args:
            texture_dir: Директория текстур
            mat_name: Имя материала
            channel: Канал
            exr_normals: Использовать EXR для нормалей

        Returns:
            Путь к текстуре
        """
        ext = ".exr" if channel == "normal" and exr_normals else ".png"
        return os.path.join(texture_dir, "%s_%s%s" % (clean_material_name(mat_name), channel, ext))

    def bake_channel(self, mat: bpy.types.Material, objects: List[bpy.types.Object],
                     channel: str, texture_dir: str, resolution: int,
                     samples: int = 64, auto_uv: bool = True,
                     normal_exr: bool = True, use_cache: bool = True,
                     use_gpu: bool = True) -> Optional[str]:
        """Bake on a temporary material copy; never alter the source material."""
        users = analyzer.material_users(mat, objects)
        if not users:
            return None
        if use_cache:
            cache_path = self.existing_bake_path(texture_dir, mat.name, channel, normal_exr)
            if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
                BakeLogger.log("CACHE HIT:", mat.name, channel, cache_path)
                return norm(cache_path)

        image, path = self.create_bake_image(
            mat, channel, texture_dir, resolution,
            normal_exr=(channel == "normal" and normal_exr),
        )
        duplicate = mat.copy()
        duplicate.name = "__BTH_BAKE_%s_%s" % (clean_material_name(mat.name), channel)
        target = None
        override_state = None
        swapped = []
        old_active = bpy.context.view_layer.objects.active
        old_sel = [obj for obj in bpy.context.scene.objects if obj.select_get()]
        old_render = self.setup_bake_render(samples, use_gpu=use_gpu)

        try:
            target = self.create_bake_target(duplicate, image)
            if channel in {"basecolor", "roughness", "metallic", "opacity", "emission"}:
                override_state = self.make_emit_bake_override(duplicate, channel)

            for obj in users:
                for index, slot in enumerate(obj.material_slots):
                    if slot.material == mat:
                        swapped.append((obj, index, mat))
                        slot.material = duplicate

            for obj in users:
                if not self.ensure_uv(obj, auto_uv):
                    BakeLogger.log("BAKE SKIPPED: missing UV", mat.name, channel, obj.name)
                    continue
                if not self.set_active_material_slot(obj, duplicate):
                    continue
                self.ensure_object_mode()
                bpy.ops.object.select_all(action="DESELECT")
                obj.select_set(True)
                bpy.context.view_layer.objects.active = obj
                duplicate.node_tree.nodes.active = target
                bake_type = "NORMAL" if channel == "normal" else "EMIT"
                if bpy.ops.object.bake.poll():
                    bpy.ops.object.bake(type=bake_type, margin=8)
                    BakeLogger.log("BAKED SAFE:", mat.name, channel, obj.name)
                else:
                    BakeLogger.log("BAKE POLL FAILED:", mat.name, channel, obj.name)

            image.save()
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return norm(path)
            BakeLogger.log("BAKE OUTPUT MISSING:", mat.name, channel, path)
            return None
        except Exception as error:
            BakeLogger.log("SAFE BAKE FAILED:", mat.name, channel, error)
            return None
        finally:
            for obj, index, original in swapped:
                try:
                    if index < len(obj.material_slots):
                        obj.material_slots[index].material = original
                except Exception as error:
                    BakeLogger.log("MATERIAL RESTORE FAILED:", obj.name, error)
            try:
                self.restore_emit_bake_override(duplicate, override_state)
                if target:
                    duplicate.node_tree.nodes.remove(target)
            except Exception:
                pass
            try:
                bpy.data.materials.remove(duplicate)
            except Exception as error:
                BakeLogger.log("TEMP MATERIAL CLEANUP FAILED:", duplicate.name, error)
            self.ensure_object_mode()
            bpy.ops.object.select_all(action="DESELECT")
            for obj in old_sel:
                try:
                    obj.select_set(True)
                except Exception:
                    pass
            bpy.context.view_layer.objects.active = old_active
            self.restore_bake_render(old_render)

bake_manager = BakeManager()
