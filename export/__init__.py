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
from ..baking import bake_manager


class ExportManager:
    """Менеджер экспорта ассетов"""

    def __init__(self):
        self.temp_collections: List[bpy.types.Collection] = []

    def material_key(self, material, material_keys=None):
        if material_keys is None:
            return clean_material_name(material.name)
        try:
            return material_keys[material.as_pointer()]
        except KeyError:
            raise ValueError(f'No exported material key for {material.name!r}')

    def collect_assignments(self, objects: List[bpy.types.Object], material_keys=None) -> List[Dict[str, Any]]:
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
            slots = obj.material_slots
            if material_keys is not None and obj.type == 'MESH':
                indices = sorted({p.material_index for p in obj.data.polygons})
                slots = [obj.material_slots[i] for i in indices if i < len(obj.material_slots)]
            for slot in slots:
                if slot.material:
                    mats.append(self.material_key(slot.material, material_keys))

            bth_mat = None
            try:
                bth_mat = obj.get("bth_material", None) if material_keys is None else None
            except Exception:
                bth_mat = None

            if material_keys is not None and len(set(mats)) == 1:
                bth_mat = mats[0]

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

    def prepare_split_by_material_objects(self, objects: List[bpy.types.Object], material_keys=None) -> Tuple[List[bpy.types.Object], Optional[bpy.types.Collection]]:
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
                            mat_name = self.material_key(part.material_slots[idx].material, material_keys)

                    if not mat_name:
                        for slot in part.material_slots:
                            if slot.material:
                                mat_name = self.material_key(slot.material, material_keys)
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
            if material_keys is not None:
                self.cleanup_temp_collection(temp_collection)
                raise
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

    def generate_houdini_script(self, export_dir: str, asset_name: str) -> str:
        """
        Генерирует скрипт для импорта в Houdini.

        Args:
            export_dir: Директория экспорта
            asset_name: Имя ассета

        Returns:
            Содержимое скрипта
        """
        from pathlib import Path
        code = Path(__file__).with_name('houdini_template.py.txt').read_text(encoding='utf8')

        return code.replace("__BASE_DIR__", norm(export_dir)).replace("__ASSET_NAME__", asset_name)


# Глобальный экземпляр менеджера экспорта
export_manager = ExportManager()


