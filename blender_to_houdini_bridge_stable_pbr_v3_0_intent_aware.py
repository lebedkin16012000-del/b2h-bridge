"""
B2H Bridge v4.0.0 Beta
Модульная версия аддона
"""

import bpy

# Импорт модулей
from . import config
from . import utils
from . import core
from . import baking
from . import export
from . import ui

bl_info = {
    "name": "B2H Bridge v4.0.0 Beta",
    "author": "NEO_LESHA",
    "version": (4, 0, 0),
    "warning": "Beta / Work In Progress",
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > Houdini Bridge",
    "description": "B2H Bridge v4.0.0 Beta: USD, PBR textures, partial bake, and Houdini MaterialX import",
    "category": "Import-Export",
}

# Регистрация классов
classes = (
    ui.BTH_Settings,
    ui.BTH_OT_export,
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

    print(f"[BTH] B2H Bridge V{bl_info['version']} зарегистрирован")

def unregister():
    """Отмена регистрации аддона в Blender"""
    try:
        bpy.app.translations.unregister(__name__)
    except Exception:
        pass

    # Удаление свойств сцены
    if hasattr(bpy.types.Scene, "bth_settings"):
        del bpy.types.Scene.bth_settings

    # Отмена регистрации классов
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    print("[BTH] B2H Bridge отменен")

if __name__ == "__main__":
    # Регистрация при прямом запуске
    register()