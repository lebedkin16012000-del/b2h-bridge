"""Scene discovery; shader compilation lives in channels.py."""
import bpy

class MaterialAnalyzer:
    @staticmethod
    def get_export_objects(selected_only):
        objects = bpy.context.selected_objects if selected_only else bpy.context.scene.objects
        return [o for o in objects if o.type == 'MESH' and o.visible_get()]

    @staticmethod
    def used_materials_from_objects(objects):
        return list(dict.fromkeys(s.material for o in objects for s in o.material_slots if s.material))

    @staticmethod
    def material_users(material, objects):
        return [o for o in objects if any(s.material == material for s in o.material_slots)]

analyzer = MaterialAnalyzer()
