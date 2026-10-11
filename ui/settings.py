import bpy
from .. import config

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

    full_square_bake_uv: bpy.props.BoolProperty(
        name="Full Square UV Grid Bake",
        description="UV-материалы запекать на временной плоскости 0-1, чтобы рисунок занимал всю текстуру",
        default=False,
    )

    force_uv_grid_bake_all: bpy.props.BoolProperty(
        name="Include 3D Coordinates",
        description="Также запекать Generated, Object и Position материалы на плоскости; текстура заполнится полностью, но станет двумерной UV-проекцией",
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

    material_reuse_mode: bpy.props.EnumProperty(
        name="Material Reuse",
        description="Как объединять один материал Blender на нескольких объектах",
        items=(
            ('BLENDER_MATERIAL', "One per Blender Material",
             "Запечь один раз и назначить один материал всем объектам с этим материалом; быстрее и компактнее"),
            ('COMPATIBLE', "Compatible Copies",
             "Объединять только одинаковую геометрию и UV; Object-зависимые материалы сохранять раздельно"),
            ('EXACT', "Preserve Every Object",
             "Запекать каждый объект отдельно и объединять только полностью одинаковый результат"),
        ),
        default='BLENDER_MATERIAL',
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
    bth_job_running: bpy.props.BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})
    bth_job_progress: bpy.props.FloatProperty(default=0.0, min=0.0, max=1.0, options={"HIDDEN", "SKIP_SAVE"})
    bth_job_message: bpy.props.StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})
    bth_job_elapsed: bpy.props.StringProperty(default="00:00", options={"HIDDEN", "SKIP_SAVE"})
    bth_job_eta: bpy.props.StringProperty(default="Estimating...", options={"HIDDEN", "SKIP_SAVE"})
    bth_job_can_cancel: bpy.props.BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})
