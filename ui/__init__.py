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


RELEASE_NAME = "B2H Bridge v4.0.0 Beta"
RELEASE_VERSION = "4.0.0-beta"


def write_export_report(report_path: str, asset_name: str, materials: Dict[str, Any],
                        usd_path: str, texture_dir: str, materialx_dir: str,
                        script_path: str) -> None:
    """Write a human-readable export summary without changing export data."""
    expected_channels = ("basecolor", "roughness", "metallic", "normal", "opacity", "emission")
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


class BTH_Settings(bpy.types.PropertyGroup):
    """Настройки аддона"""

    export_dir: bpy.props.StringProperty(
        name="Export Folder",
        description="Папка для сохранения USD, текстур, MaterialX данных и скрипта Houdini",
        subtype="DIR_PATH",
        default=config.DEFAULT_EXPORT_DIR,
    )

    asset_name: bpy.props.StringProperty(
        name="Asset Name",
        description="Имя ассета для экспортируемых файлов и нодов Houdini",
        default="blender_asset",
    )

    selected_only: bpy.props.BoolProperty(
        name="Selected Only",
        description="Экспортировать только выделенные mesh объекты",
        default=True,
    )

    export_usdc: bpy.props.BoolProperty(
        name="USD Compact (.usdc)",
        description="Сохранять USD как компактный бинарный файл .usdc",
        default=True,
    )

    axis_fix_enabled: bpy.props.BoolProperty(
        name="Houdini Axis Fix",
        description="Повернуть ассет при импорте в Houdini, если он лежит/стоит неправильно",
        default=True,
    )

    axis_rotate_x: bpy.props.FloatProperty(
        name="Axis Rotate X",
        description="Угол поворота по X для исправления оси в Houdini",
        default=-90.0,
    )

    auto_bake_complex: bpy.props.BoolProperty(
        name="Bake Complex Materials",
        description="Запекать procedural, noise, mix и node group материалы в PBR текстуры",
        default=True,
    )

    fast_bake_mode: bpy.props.BoolProperty(
        name="Fast Bake",
        description="Запекать только там, где это реально нужно. Простые материалы переносятся без запекания",
        default=True,
    )

    bake_missing_basecolor: bpy.props.BoolProperty(
        name="Bake Missing BaseColor",
        description="Если выключено, материалы без текстуры BaseColor используют простой цвет Blender вместо долгого bake",
        default=False,
    )

    bake_complex_normals: bpy.props.BoolProperty(
        name="Bake Complex Normals",
        description="Запекать normal для procedural материалов. Медленно, включать только если нужно",
        default=False,
    )

    use_gpu_bake: bpy.props.BoolProperty(
        name="Use GPU Bake If Possible",
        description="Пробовать использовать GPU/CUDA/OptiX/HIP/Metal/OneAPI для Cycles bake",
        default=True,
    )

    bake_resolution: bpy.props.IntProperty(
        name="Bake Resolution",
        description="Размер baked-текстур: 1024, 2048, 4096",
        default=1024,
        min=256,
        max=4096,
    )

    bake_samples: bpy.props.IntProperty(
        name="Bake Samples",
        description="Качество запекания. Для скорости ставь 1-8",
        default=8,
        min=1,
        max=512,
    )

    bake_auto_uv: bpy.props.BoolProperty(
        name="Auto UV If Missing",
        description="Автоматически создать простую UV-развертку, если у объекта нет UV",
        default=True,
    )

    bake_normals_exr: bpy.props.BoolProperty(
        name="Bake Normals as EXR",
        description="Сохранять normal maps в EXR для лучшего качества",
        default=True,
    )

    split_by_material: bpy.props.BoolProperty(
        name="Split Meshes By Material",
        description="Временно разделяет mesh по material slots, чтобы Houdini точно назначал материалы",
        default=True,
    )

    metal_ignore_basecolor: bpy.props.BoolProperty(
        name="Smart Metal BaseColor",
        description="Цветной металл сохраняет цвет, а плохой/чёрный basecolor отключается",
        default=True,
    )

    texture_edge_padding: bpy.props.BoolProperty(
        name="Texture Edge Padding",
        description="Растягивает цвет за края UV-островов, чтобы не было чёрных швов",
        default=True,
    )

    texture_padding_iterations: bpy.props.IntProperty(
        name="Padding Iterations",
        description="Насколько далеко растягивать цвет за края UV-островов",
        default=24,
        min=1,
        max=128,
    )

    enable_texture_cache: bpy.props.BoolProperty(
        name="Texture Cache",
        description="Не запекать текстуры повторно, если они уже существуют",
        default=True,
    )

    cleanup_unused_textures: bpy.props.BoolProperty(
        name="Cleanup Old Textures",
        description="Удалять старые generated-текстуры перед экспортом",
        default=True,
    )

    smart_glass_mode: bpy.props.BoolProperty(
        name="Smart Glass",
        description="Настроить стекло под Karma/MaterialX: transparency, IOR, roughness",
        default=True,
    )

    smart_foliage_mode: bpy.props.BoolProperty(
        name="Smart Foliage",
        description="Настроить foliage/листья: alpha, thin-walled, мягкое просвечивание",
        default=True,
    )

    export_materialx_files: bpy.props.BoolProperty(
        name="Export MaterialX Files",
        description="Создавать папку materialx и простые .mtlx/manifest файлы",
        default=True,
    )

    export_as_instances: bpy.props.BoolProperty(
        name="Export As Instances",
        description="Опционально помечать повторяющуюся геометрию как instances",
        default=False,
    )

    udim_mode: bpy.props.BoolProperty(
        name="UDIM Preparation",
        description="Включить метаданные для будущего UDIM workflow",
        default=False,
    )


    ui_show_export: bpy.props.BoolProperty(default=True, options={"HIDDEN"})
    ui_show_bake: bpy.props.BoolProperty(default=True, options={"HIDDEN"})
    ui_show_materials: bpy.props.BoolProperty(default=False, options={"HIDDEN"})
    ui_show_houdini: bpy.props.BoolProperty(default=False, options={"HIDDEN"})
    ui_show_advanced: bpy.props.BoolProperty(default=False, options={"HIDDEN"})
class BTH_OT_export(bpy.types.Operator):
    """Оператор экспорта"""

    bl_idname = "bth.export_stable_pbr_bridge"
    bl_label = "Export Stable PBR Bridge"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        """Выполняет экспорт"""
        s = context.scene.bth_settings
        export_dir = bpy.path.abspath(s.export_dir)
        asset_name = safe_name(s.asset_name, "blender_asset")
        texture_dir = os.path.join(export_dir, "textures")
        materialx_dir = os.path.join(export_dir, "materialx")

        # Очищаем логи и создаем директории
        BakeLogger.clear()
        ensure_dir(export_dir)
        ensure_dir(texture_dir)
        ensure_dir(materialx_dir)

        # Очищаем старые текстуры если нужно
        texture_cache_enabled = bool(getattr(s, "enable_texture_cache", True))
        if bool(getattr(s, "cleanup_unused_textures", False)):
            cleanup_texture_folder(texture_dir)
            # The folder was just cleared, so cache misses are expected for this
            # export only.  Do not mutate the user's saved UI preference.
            texture_cache_enabled = False

        temp_collection = None
        progress = context.window_manager
        progress_started = False
        try:
            # Получаем объекты для экспорта
            source_objects = analyzer.get_export_objects(s.selected_only)
            if not source_objects:
                self.report({"ERROR"}, "No mesh objects to export")
                return {"CANCELLED"}

            objects = source_objects

            # Разделяем по материалам если нужно
            if bool(s.split_by_material):
                objects, temp_collection = export_manager.prepare_split_by_material_objects(source_objects)

            # Экспортируем USD
            usd_path = os.path.join(export_dir, asset_name + (".usdc" if s.export_usdc else ".usd"))
            export_manager.export_usd(usd_path, objects)

            # Собираем материалы
            materials = {}
            for mat in analyzer.used_materials_from_objects(objects):
                try:
                    data = export_manager.collect_material(mat, objects, texture_dir, s)
                    materials[data["name"]] = data
                except Exception as e:
                    # Отладочная информация для понимания ошибки
                    try:
                        mat_name = getattr(mat, 'name', str(mat))
                        mat_type = type(mat).__name__
                        # Получаем полный traceback
                        import traceback
                        tb_str = traceback.format_exc()
                        BakeLogger.log(f"MATERIAL FAILED: name={mat_name}, type={mat_type}, error={e}")
                        BakeLogger.log(f"TRACEBACK: {tb_str}")
                    except Exception as e2:
                        BakeLogger.log(f"MATERIAL FAILED LOGGING ERROR: {e2}, original error: {e}")
                    traceback.print_exc()

            # Определяем каналы для запекания
            material_total = max(1, len(materials))
            progress.progress_begin(0, material_total)
            progress_started = True
            for material_index, mat_data in enumerate(materials.values(), start=1):
                mat_name = mat_data["name"]
                mat = next((m for m in analyzer.used_materials_from_objects(objects) if clean_material_name(m.name) == mat_name), None)
                if not mat:
                    continue

                intent = mat_data.get("intent", {})
                bake_channels = set(intent.get("bake_channels", []))
                has_detail_chain = bool(bake_channels)
                has_alpha = analyzer.material_has_alpha(mat)
                has_bump = analyzer.material_has_bump_or_normal(mat)
                missing_base = not bool(mat_data["textures"].get("basecolor"))
                is_complex = analyzer.material_is_complex(mat)

                # V3.0 intent-aware partial bake
                if not bool(getattr(s, "fast_bake_mode", True)) and (is_complex or has_detail_chain):
                    bake_channels.update(["basecolor", "roughness", "metallic", "opacity"])

                if missing_base and bool(getattr(s, "bake_missing_basecolor", False)):
                    bake_channels.add("basecolor")

                if has_alpha and not mat_data["textures"].get("opacity"):
                    alpha_info = intent.get("channels", {}).get("opacity", {})
                    bsdf = get_principled(mat)
                    if alpha_info.get("needs_bake") or (bsdf and bsdf.inputs.get("Alpha") and bsdf.inputs["Alpha"].is_linked):
                        bake_channels.add("opacity")

                if has_bump and (bool(getattr(s, "bake_complex_normals", False)) or intent.get("channels", {}).get("normal", {}).get("needs_bake")):
                    bake_channels.add("normal")

                should_bake = bool(s.auto_bake_complex) and bool(bake_channels)

                if should_bake:
                    BakeLogger.log("INTENT BAKE MATERIAL:", mat.name, "summary=", intent.get("summary"),
                                 "channels=", sorted(bake_channels), "complex=", is_complex,
                                 "alpha=", has_alpha, "bump=", has_bump, "missing_base=", missing_base)

                    # Запекаем каналы
                    # A set is useful for deduplication above, but baking must run
                    # in a deterministic order for reproducible logs and output.
                    for channel in ("basecolor", "roughness", "metallic", "opacity", "emission", "normal"):
                        if channel not in bake_channels:
                            continue
                        context.workspace.status_text_set(f"Baking {mat.name}: {channel} ({material_index}/{material_total})")
                        if channel == "basecolor":
                            from ..utils.image_utils import pad_image_black_background, image_is_dark_or_bad_for_metal
                            b = bake_manager.bake_channel(
                                mat, objects, "basecolor", texture_dir, s.bake_resolution,
                                s.bake_samples, s.bake_auto_uv, s.bake_normals_exr,
                                texture_cache_enabled,
                                getattr(s, "use_gpu_bake", True)
                            )
                            if b:
                                if bool(getattr(s, "texture_edge_padding", True)):
                                    pad_image_black_background(b, int(getattr(s, "texture_padding_iterations", 24)))

                                if mat_data.get("hints", {}).get("metal") and bool(getattr(s, "metal_ignore_basecolor", True)) and image_is_dark_or_bad_for_metal(b):
                                    BakeLogger.log("METAL BASECOLOR BAKE IGNORED:", mat.name, b)
                                    mat_data["textures"]["basecolor"] = None
                                    mat_data["metal_basecolor_ignored"] = True
                                else:
                                    mat_data["textures"]["basecolor"] = b
                                    if mat_data.get("hints", {}).get("metal"):
                                        mat_data["metal_basecolor_kept"] = True
                                        mat_data["metal_basecolor_ignored"] = False
                                mat_data["baked"] = True

                        elif channel in ["roughness", "metallic", "emission"]:
                            baked = bake_manager.bake_channel(
                                mat, objects, channel, texture_dir, s.bake_resolution,
                                s.bake_samples, s.bake_auto_uv, False,
                                texture_cache_enabled,
                                getattr(s, "use_gpu_bake", True)
                            )
                            if baked:
                                mat_data["textures"][channel] = baked
                                mat_data["baked"] = True

                        elif channel == "opacity":
                            a = bake_manager.bake_channel(
                                mat, objects, "opacity", texture_dir, s.bake_resolution,
                                s.bake_samples, s.bake_auto_uv, False,
                                texture_cache_enabled,
                                getattr(s, "use_gpu_bake", True)
                            )
                            if a:
                                mat_data["textures"]["opacity"] = a
                                mat_data["hints"]["alpha"] = True
                                mat_data["baked"] = True

                        elif channel == "normal":
                            n = bake_manager.bake_channel(
                                mat, objects, "normal", texture_dir, s.bake_resolution,
                                s.bake_samples, s.bake_auto_uv, s.bake_normals_exr,
                                texture_cache_enabled,
                                getattr(s, "use_gpu_bake", True)
                            )
                            if n:
                                mat_data["textures"]["normal"] = n
                                mat_data["baked"] = True

            # Создаем bridge файл
                progress.progress_update(material_index)

            # Blender's USD export can write its own source-texture copies.
            # Houdini uses only the files referenced below, so remove every
            # unreferenced file and keep one portable PBR texture set.
            referenced_textures = {
                path
                for material in materials.values()
                for path in material.get("textures", {}).values()
                if path
            }
            cleanup_texture_folder(texture_dir, referenced_textures)

            bridge = {
                "version": RELEASE_VERSION,
                "release_name": RELEASE_NAME,
                "asset_name": asset_name,
                "base_dir": norm(export_dir),
                "usd_path": norm(usd_path),
                "texture_dir": norm(texture_dir),
                "materialx_dir": norm(materialx_dir),
                "axis_fix_enabled": bool(s.axis_fix_enabled),
                "axis_rotate_x": float(s.axis_rotate_x),
                "split_by_material": bool(s.split_by_material),
                "metal_ignore_basecolor": bool(s.metal_ignore_basecolor),
                "texture_edge_padding": bool(s.texture_edge_padding),
                "texture_padding_iterations": int(s.texture_padding_iterations),
                "export_as_instances": bool(s.export_as_instances),
                "udim_mode": bool(s.udim_mode),
                "houdini_ui_safe_mode": True,
                "instance_sources": export_manager.detect_instance_sources(objects) if bool(s.export_as_instances) else {},
                "fast_bake_mode": bool(s.fast_bake_mode),
                "bake_missing_basecolor": bool(s.bake_missing_basecolor),
                "bake_complex_normals": bool(s.bake_complex_normals),
                "use_gpu_bake": bool(s.use_gpu_bake),
                "materials": materials,
                "assignments": export_manager.collect_assignments(objects),
                "bake_log": BakeLogger.get_log(),
            }

            # Сохраняем bridge.json
            with open(os.path.join(export_dir, asset_name + "_bridge.json"), "w", encoding="utf-8") as f:
                json.dump(bridge, f, indent=4, ensure_ascii=False)

            # Сохраняем material manifest
            with open(os.path.join(materialx_dir, asset_name + "_material_manifest.json"), "w", encoding="utf-8") as f:
                json.dump({"materials": materials}, f, indent=4, ensure_ascii=False)

            # UDIM информация
            if bool(getattr(s, "udim_mode", False)):
                with open(os.path.join(materialx_dir, "UDIM_INFO.txt"), "w", encoding="utf-8") as f:
                    f.write("UDIM PREPARATION ENABLED\n")
                    f.write("Future UDIM workflow compatibility enabled.\n")

            # MaterialX файлы
            if bool(getattr(s, "export_materialx_files", True)):
                for mname, mdata in materials.items():
                    try:
                        mtlx_path = os.path.join(materialx_dir, safe_name(mname) + ".mtlx")
                        with open(mtlx_path, "w", encoding="utf-8") as mf:
                            mf.write('<?xml version="1.0"?>\n')
                            mf.write('<materialx version="1.38">\n')
                            mf.write('  <surfacematerial name="%s"/>\n' % safe_name(mname))
                            mf.write('</materialx>\n')
                    except Exception:
                        pass

            # Генерируем Houdini скрипт
            script_path = os.path.join(export_dir, "import_to_houdini.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(export_manager.generate_houdini_script(export_dir, asset_name))

            # Создаем инструкцию для пользователя
            with open(os.path.join(export_dir, "COPY_THIS_TO_HOUDINI.txt"), "w", encoding="utf-8") as f:
                f.write('exec(open(r"' + norm(script_path) + '", encoding="utf-8").read())')

            # Сохраняем прежний bake-лог и расширенный отчёт для поддержки.
            with open(os.path.join(export_dir, asset_name + "_bake_report.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(BakeLogger.get_log()))
            write_export_report(
                os.path.join(export_dir, asset_name + "_export_report.txt"),
                asset_name, materials, usd_path, texture_dir, materialx_dir, script_path,
            )

            # Debug информация о назначениях
            with open(os.path.join(export_dir, asset_name + "_assignment_debug.json"), "w", encoding="utf-8") as f:
                json.dump(export_manager.collect_assignments(objects), f, indent=4, ensure_ascii=False)

            # Очищаем временные объекты
            export_manager.cleanup_temp_collection(temp_collection)

            self.report({"INFO"}, RELEASE_NAME + " exported")
            BakeLogger.log("STABLE PBR BRIDGE EXPORTED", norm(usd_path), list(materials.keys()))
            return {"FINISHED"}

        except Exception as e:
            export_manager.cleanup_temp_collection(temp_collection)
            traceback.print_exc()
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        finally:
            if progress_started:
                try:
                    progress.progress_end()
                except Exception:
                    pass
            try:
                context.workspace.status_text_set(None)
            except Exception:
                pass


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
            col.prop(s, "split_by_material")
            col.prop(s, "metal_ignore_basecolor")
            col.prop(s, "smart_glass_mode")
            col.prop(s, "smart_foliage_mode")
            col.prop(s, "export_materialx_files")
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
