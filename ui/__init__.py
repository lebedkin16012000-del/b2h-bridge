"""
UI модуль для аддона Blender To Houdini Bridge
"""

import bpy
import os
import json
import traceback
from typing import Optional, Dict, Any
from .. import config
from ..utils import BakeLogger, clean_material_name, cleanup_texture_folder, get_principled, safe_name, norm, ensure_dir
from ..core import analyzer
from ..baking import bake_manager
from ..export import export_manager


RELEASE_NAME = "B2H Bridge v4.8.4 Beta"
RELEASE_VERSION = "4.8.4-beta"


from .settings import BTH_Settings

from ..jobs.operator import BTH_OT_export, BTH_OT_cancel_export


class BTH_PT_panel(bpy.types.Panel):
    """Compact, task-oriented Blender to Houdini Bridge panel."""

    bl_label = "Houdini Bridge"
    bl_idname = "BTH_PT_stable_pbr_bridge"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Houdini"

    @staticmethod
    def _section(layout, settings, state_name, title, icon):
        box = layout.box()
        row = box.row(align=True)
        expanded = bool(getattr(settings, state_name))
        row.prop(settings, state_name, text=BTH_T(title), icon="TRIA_DOWN" if expanded else "TRIA_RIGHT", emboss=False)
        row.label(text="", icon=icon)
        return box.column(align=True) if expanded else None

    def draw(self, context):
        s = context.scene.bth_settings
        layout = self.layout
        mesh_count = sum(
            1 for obj in context.scene.objects
            if obj.type == "MESH" and (not s.selected_only or obj.select_get())
        )

        summary = layout.box()
        summary.label(text=RELEASE_NAME + " | Blender to Houdini", icon="FILE_3D")
        status = summary.row()
        if mesh_count:
            status.label(text=f"{mesh_count} mesh object(s) ready", icon="CHECKMARK")
        else:
            status.alert = True
            status.label(text="No mesh objects selected", icon="ERROR")

        if s.bth_job_running:
            job = layout.box()
            job.label(text=s.bth_job_message or "Preparing export", icon="TIME")
            job.progress(factor=s.bth_job_progress, type='BAR', text=f"{s.bth_job_progress:.0%}")
            timing = job.row(align=True)
            timing.label(text=f"Elapsed: {s.bth_job_elapsed}")
            timing.label(text=f"Remaining: {s.bth_job_eta}")
            cancel = job.row()
            cancel.enabled = s.bth_job_can_cancel
            cancel.operator("bth.cancel_export", text="Cancel after current pass", icon="CANCEL")

        col = self._section(layout, s, "ui_show_export", "Export", "EXPORT")
        if col:
            col.prop(s, "export_dir")
            col.prop(s, "asset_name")
            col.prop(s, "selected_only")
            col.label(text="USD, textures and the Houdini script are saved here.", icon="INFO")

        col = self._section(layout, s, "ui_show_bake", "Bake", "RENDER_STILL")
        if col:
            col.prop(s, "auto_bake_complex")
            settings = col.column(align=True)
            settings.enabled = s.auto_bake_complex
            settings.prop(s, "fast_bake_mode")
            row = settings.row(align=True)
            row.prop(s, "bake_resolution")
            row.prop(s, "bake_samples")
            settings.prop(s, "use_gpu_bake")
            settings.prop(s, "bake_auto_uv")
            settings.prop(s, "full_square_bake_uv")
            force_grid = settings.row(align=True)
            force_grid.enabled = s.full_square_bake_uv
            force_grid.prop(s, "force_uv_grid_bake_all")
            settings.prop(s, "texture_edge_padding")
            padding = settings.row(align=True)
            padding.enabled = s.texture_edge_padding
            padding.prop(s, "texture_padding_iterations")
            settings.separator()
            settings.label(text="Fine control", icon="PREFERENCES")
            settings.prop(s, "bake_missing_basecolor")
            settings.prop(s, "bake_complex_normals")
            settings.prop(s, "bake_normals_exr")
            settings.prop(s, "enable_texture_cache")
            settings.prop(s, "cleanup_unused_textures")
            col.label(text="Keep Fast Bake on unless every PBR channel needs baking.", icon="INFO")

        col = self._section(layout, s, "ui_show_materials", "Materials", "MATERIAL")
        if col:
            col.prop(s, "material_reuse_mode")
            active_material = context.object.active_material if context.object and context.object.type == 'MESH' else None
            if active_material:
                col.prop(active_material, "bth_export_name", text="Active Export Name")
            col.prop(s, "split_by_material")
            col.prop(s, "metal_ignore_basecolor")
            col.prop(s, "smart_glass_mode")
            col.prop(s, "smart_foliage_mode")
            col.prop(s, "export_materialx_files")
            col.label(text="Empty Export Name uses the cleaned Blender material name.", icon="INFO")
            col.label(text="MaterialX data is generated for Karma in Houdini.", icon="INFO")

        col = self._section(layout, s, "ui_show_houdini", "Houdini", "FILE_3D")
        if col:
            col.prop(s, "export_usdc")
            col.prop(s, "axis_fix_enabled")
            axis = col.row(align=True)
            axis.enabled = s.axis_fix_enabled
            axis.prop(s, "axis_rotate_x")
            col.label(text="Axis correction is normally needed for Houdini.", icon="INFO")

        col = self._section(layout, s, "ui_show_advanced", "Advanced", "PREFERENCES")
        if col:
            col.prop(s, "export_as_instances")
            col.prop(s, "udim_mode")
            col.label(text="Use these only for a specific pipeline requirement.", icon="INFO")

        layout.separator()
        button = layout.column()
        button.scale_y = 1.45
        button.operator("bth.export_stable_pbr_bridge", text=BTH_T("Export Stable PBR Bridge"), icon="EXPORT")

BTH_TRANSLATIONS = {
    "ru_RU": {
        ("*", "Export Folder"): "Папка экспорта",
        ("*", "Папка для сохранения USD, текстур, MaterialX данных и скрипта Houdini"): "Куда сохранять USD, текстуры, MaterialX и скрипт для Houdini",
        ("*", "Asset Name"): "Имя ассета",
        ("*", "Имя ассета для экспортируемых файлов и нодов Houdini"): "Имя файла и корневого ассета в Houdini",
        ("*", "Selected Only"): "Только выделенное",
        ("*", "Экспортировать только выделенные mesh объекты"): "Экспортировать только выделенные mesh-объекты",
        ("*", "USD Compact (.usdc)"): "USD Compact (.usdc)",
        ("*", "Сохранять USD как компактный бинарный файл .usdc"): "Сохранять USD в компактном бинарном формате .usdc",
        ("*", "Houdini Axis Fix"): "Исправить ось для Houdini",
        ("*", "Повернуть ассет при импорте в Houdini, если он лежит/стоит неправильно"): "Повернуть объект при импорте в Houdini, если он лежит/стоит неправильно",
        ("*", "Axis Rotate X"): "Поворот X",
        ("*", "Угол поворота по X для исправления оси в Houdini"): "Угол поворота по X для исправления оси в Houdini",
        ("*", "Bake Complex Materials"): "Запекать сложные материалы",
        ("*", "Запекать procedural, noise, mix и node group материалы в PBR текстуры"): "Запекать procedural/noise/mix/node group материалы в PBR-текстуры",
        ("*", "Fast Bake"): "Быстрый bake",
        ("*", "Запекать только там, где это реально нужно. Простые материалы переносятся без запекания"): "Bake только там, где он реально нужен. Простые материалы переносятся без запекания",
        ("*", "Bake Missing BaseColor"): "Bake если нет BaseColor",
        ("*", "Если выключено, материалы без текстуры BaseColor используют простой цвет Blender вместо долгого bake"): "Если выключено, материалы без texture BaseColor используют простой цвет Blender вместо долгого bake",
        ("*", "Bake Complex Normals"): "Bake Normal для сложных",
        ("*", "Запекать normal для procedural материалов. Медленно, включать только если нужно"): "Запекать normal для procedural материалов. Медленно, включать только если нужно",
        ("*", "Use GPU Bake If Possible"): "GPU bake если возможно",
        ("*", "Пробовать использовать GPU/CUDA/OptiX/HIP/Metal/OneAPI для Cycles bake"): "Пробовать использовать GPU/CUDA/OptiX/HIP/Metal/OneAPI для Cycles bake",
        ("*", "Bake Resolution"): "Разрешение bake",
        ("*", "Размер baked-текстур: 1024, 2048, 4096"): "Размер baked-текстур: 1024, 2048, 4096",
        ("*", "Bake Samples"): "Samples bake",
        ("*", "Качество запекания. Для скорости ставь 1-8"): "Качество запекания. Для скорости ставь 1-8",
        ("*", "Auto UV If Missing"): "Auto UV если нет UV",
        ("*", "Автоматически создать простую UV-развертку, если у объекта нет UV"): "Автоматически создать простую UV-развертку, если у объекта нет UV",
        ("*", "Full Square UV Grid Bake"): "Запекать на UV-гриде 0–1",
        ("*", "UV-материалы запекать на временной плоскости 0-1, чтобы рисунок занимал всю текстуру"): "UV-материалы запекать на временной плоскости 0–1, чтобы рисунок занимал всю текстуру",
        ("*", "Include 3D Coordinates"): "Включая 3D-координаты",
        ("*", "Также запекать Generated, Object и Position материалы на плоскости; текстура заполнится полностью, но станет двумерной UV-проекцией"): "Также запекать Generated, Object и Position на плоскости; рисунок заполнит карту, но станет UV-проекцией",
        ("*", "Bake Normals as EXR"): "Normal в EXR",
        ("*", "Сохранять normal maps в EXR для лучшего качества"): "Сохранять normal maps в EXR для лучшего качества",
        ("*", "Split Meshes By Material"): "Разделять по материалам",
        ("*", "Временно разделяет mesh по material slots, чтобы Houdini точно назначал материалы"): "Временно разделяет mesh по material slots, чтобы Houdini точно назначал материалы",
        ("*", "Smart Metal BaseColor"): "Умный цвет металла",
        ("*", "Цветной металл сохраняет цвет, а плохой/чёрный basecolor отключается"): "Цветной металл сохраняет цвет, а плохой/чёрный basecolor отключается",
        ("*", "Texture Edge Padding"): "Заполнение краёв текстуры",
        ("*", "Растягивает цвет за края UV-островов, чтобы не было чёрных швов"): "Растягивает цвет за края UV-островов, чтобы не было чёрных швов",
        ("*", "Padding Iterations"): "Сила padding",
        ("*", "Насколько далеко растягивать цвет за края UV-островов"): "Насколько далеко растягивать цвет за края UV-островов",
        ("*", "Texture Cache"): "Кэш текстур",
        ("*", "Не запекать текстуры повторно, если они уже существуют"): "Не запекать текстуры повторно, если они уже существуют",
        ("*", "Cleanup Old Textures"): "Чистить старые текстуры",
        ("*", "Удалять старые generated-текстуры перед экспортом"): "Удалять старые generated-текстуры перед экспортом",
        ("*", "Smart Glass"): "Умное стекло",
        ("*", "Настроить стекло под Karma/MaterialX: transparency, IOR, roughness"): "Настроить стекло под Karma/MaterialX: transparency, IOR, roughness",
        ("*", "Smart Foliage"): "Умная листва",
        ("*", "Настроить foliage/листья: alpha, thin-walled, мягкое просвечивание"): "Настроить foliage/листья: alpha, thin-walled, мягкое просвечивание",
        ("*", "Export MaterialX Files"): "Экспорт MaterialX файлов",
        ("*", "Создавать папку materialx и простые .mtlx/manifest файлы"): "Создавать папку materialx и простые .mtlx/manifest файлы",
        ("*", "Export As Instances"): "Экспорт как instances",
        ("*", "Опционально помечать повторяющуюся геометрию как instances"): "Опционально помечать повторяющуюся геометрию как instances",
        ("*", "UDIM Preparation"): "Подготовка UDIM",
        ("*", "Включить метаданные для будущего UDIM workflow"): "Включить метаданные для будущего UDIM workflow",
        ("*", "Export Stable PBR Bridge"): "Экспорт Stable PBR Bridge",
    }
}


def BTH_T(text: str) -> str:
    """Функция для переводов"""
    return bpy.app.translations.pgettext_iface(text)





