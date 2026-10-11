"""
B2H Bridge v4.8.3 Beta
Модульная версия аддона
"""

import bpy
import importlib

# Импорт модулей
from . import config
from . import utils
from . import core
from . import baking
from . import export
from . import ui

# Перезагрузка модулей для разработки
def reload_modules():
    importlib.reload(config)
    importlib.reload(utils)
    importlib.reload(core)
    importlib.reload(baking)
    importlib.reload(export)
    importlib.reload(ui)

bl_info = {
    "name": "B2H Bridge v4.8.3 Beta",
    "author": "NEO_LESHA",
    "version": (4, 8, 3),
    "warning": "Beta / Work In Progress",
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > Houdini Bridge",
    "description": "B2H Bridge v4.8.3 Beta: optional full-tile projection for 3D materials",
    "category": "Import-Export",
}

# Регистрация классов
classes = (
    ui.BTH_Settings,
    ui.BTH_OT_export,
    ui.BTH_OT_cancel_export,
    ui.BTH_PT_panel,
)

def register():
    """Регистрация аддона в Blender"""
    try:
        # Регистрация переводов
        bpy.app.translations.register(__name__, ui.BTH_TRANSLATIONS)
    except Exception:
        pass

    # Регистрация классов
    for cls in classes:
        bpy.utils.register_class(cls)

    # Регистрация свойств сцены
    bpy.types.Scene.bth_settings = bpy.props.PointerProperty(type=ui.BTH_Settings)
    bpy.types.Material.bth_export_name = bpy.props.StringProperty(
        name="B2H Export Name",
        description="Короткое имя материала и его публичных текстур, например stone",
        default="",
    )

    print(f"B2H Bridge V{bl_info['version']} зарегистрирован")

def unregister():
    from .jobs.operator import shutdown
    shutdown()
    """Отмена регистрации аддона в Blender"""
    try:
        bpy.app.translations.unregister(__name__)
    except Exception:
        pass

    # Удаление свойств сцены
    if hasattr(bpy.types.Scene, "bth_settings"):
        del bpy.types.Scene.bth_settings
    if hasattr(bpy.types.Material, "bth_export_name"):
        del bpy.types.Material.bth_export_name

    # Отмена регистрации классов
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    print("B2H Bridge отменен")

if __name__ == "__main__":
    # Регистрация при прямом запуске
    register()
