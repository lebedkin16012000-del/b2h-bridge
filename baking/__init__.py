"""Bake compatibility helper; implementation lives in session.py."""
import bpy

class BakeManager:
    @staticmethod
    def ensure_object_mode():
        if bpy.context.mode != 'OBJECT' and bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode='OBJECT')

bake_manager = BakeManager()
