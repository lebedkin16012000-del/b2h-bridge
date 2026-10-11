"""One Cycles session per worker; originals are never edited in the UI process."""
import math
import os
import time
import bpy
from ..core.channels import linked, rgba

def prepare_uv(obj, auto_uv, full_square=False):
    layers = obj.data.uv_layers
    if layers and not full_square:
        source = next((u for u in layers if u.active_render), layers.active)
        # A named mask can be the useful UV set while Blender's render UV is a
        # placeholder collapsed to (0, 0). Baking to that layer produces a
        # solid image even though the procedural material is correct.
        if source and _uv_has_area(obj, source):
            layers.active = source
            return source.name
    if not auto_uv and not full_square:
        raise ValueError(f'{obj.name}: no usable UV map and Auto UV is disabled')
    existing = layers.get('B2H_Bake')
    if existing:
        layers.remove(existing)
    bake_uv = layers.new(name='B2H_Bake')
    layers.active = bake_uv
    bake_uv.active_render = True
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        # Mode changes can restore the previously active UV layer. Re-select
        # the private target after entering Edit Mode so named mask UVs remain
        # byte-for-byte untouched.
        obj.data.uv_layers.active = obj.data.uv_layers['B2H_Bake']
        obj.data.uv_layers['B2H_Bake'].active_render = True
        bpy.ops.mesh.select_all(action='SELECT')
        # Smart Project creates non-overlapping islands and scales the complete
        # atlas into the 0-1 tile. In full-square mode this private atlas is
        # always rebuilt, even when the source object already has a render UV.
        # The source UV layers remain untouched in the background snapshot.
        margin = 0.005 if full_square else 0.02
        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=margin)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
    return obj.data.uv_layers.active.name

def _uv_has_area(obj, layer):
    """Reject UV layers collapsed to a point or line."""
    for polygon in obj.data.polygons:
        points = [layer.data[i].uv for i in polygon.loop_indices]
        area = 0.0
        for index, point in enumerate(points):
            other = points[(index + 1) % len(points)]
            area += point.x * other.y - other.x * point.y
        if abs(area) > 1e-10:
            return True
    return False

def bake_margin(settings):
    """Return a narrow island border; never dilate across the entire map."""
    if getattr(settings, 'full_square_bake_uv', False) or settings.texture_edge_padding:
        return max(1, int(getattr(settings, 'texture_padding_iterations', 24)))
    return 0

def create_uv_bake_plane(source_obj, material):
    """Create a disposable quad whose UVs cover the complete 0-1 tile."""
    mesh = bpy.data.meshes.new('_B2H_UV_BakePlaneMesh')
    mesh.from_pydata([(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0),
                      (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)], [], [(0, 1, 2, 3)])
    mesh.update()
    plane = bpy.data.objects.new('_B2H_UV_BakePlane', mesh)
    bpy.context.scene.collection.objects.link(plane)
    mesh.materials.append(material)

    names = [layer.name for layer in source_obj.data.uv_layers]
    if not names:
        names = ['UVMap']
    coordinates = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    for name in dict.fromkeys(names):
        layer = mesh.uv_layers.new(name=name)
        for loop, uv in zip(layer.data, coordinates):
            loop.uv = uv
    source_render = next((layer.name for layer in source_obj.data.uv_layers
                          if layer.active_render), None)
    active = mesh.uv_layers.get(source_render) if source_render else mesh.uv_layers[0]
    mesh.uv_layers.active = active
    active.active_render = True
    return plane

def remove_uv_bake_plane(plane):
    """Remove a disposable plane and its mesh without leaving job data behind."""
    if not plane:
        return
    mesh = plane.data
    bpy.data.objects.remove(plane, do_unlink=True)
    if mesh and mesh.users == 0:
        bpy.data.meshes.remove(mesh)

class BakeSession:
    def __init__(self, settings):
        self.settings = settings
        self.scene = bpy.context.scene
        self.scene.render.engine = 'CYCLES'
        self.scene.cycles.samples = settings.bake_samples
        self.scene.cycles.device = 'CPU'
        self.device = 'CPU'
        if settings.use_gpu_bake:
            prefs = bpy.context.preferences.addons.get('cycles')
            if prefs:
                cp = prefs.preferences
                choices = [cp.compute_device_type, 'OPTIX', 'CUDA', 'HIP', 'METAL', 'ONEAPI']
                for backend in dict.fromkeys(choices):
                    try:
                        cp.compute_device_type = backend
                        cp.get_devices()
                        devices = [d for d in cp.devices if d.type != 'CPU']
                        if not devices: continue
                        for d in cp.devices: d.use = d in devices
                        self.scene.cycles.device = 'GPU'
                        self.device = 'GPU (' + backend + ')'
                        break
                    except (TypeError, RuntimeError):
                        continue
        self.scene.render.bake.normal_space = 'TANGENT'
        self.scene.render.bake.normal_r = 'POS_X'
        self.scene.render.bake.normal_g = 'POS_Y'
        self.scene.render.bake.normal_b = 'POS_Z'

    def _save_image(self, image, path):
        """Save with an explicit encoder; Image.save() can retain PNG's ImBuf
        format even after file_format is changed to OPEN_EXR."""
        if path.lower().endswith('.exr'):
            settings = self.scene.render.image_settings
            previous = (settings.file_format, settings.color_mode,
                        settings.color_depth, settings.exr_codec)
            try:
                settings.file_format = 'OPEN_EXR'
                settings.color_mode = 'RGBA'
                settings.color_depth = '16'
                settings.exr_codec = 'ZIP'
                image.save_render(path, scene=self.scene)
            finally:
                settings.file_format, settings.color_mode, settings.color_depth, settings.exr_codec = previous
        else:
            image.save()

    def bake(self, obj, slot_index, compiler, channel, value, path):
        started = time.perf_counter()
        mat, tree = compiler.material, compiler.material.node_tree
        settings = self.settings
        float_buffer = path.endswith('.exr')
        image = bpy.data.images.new('_B2H_target', width=settings.bake_resolution,
                                    height=settings.bake_resolution, alpha=True, float_buffer=float_buffer)
        image.colorspace_settings.name = 'sRGB' if channel == 'basecolor' else 'Non-Color'
        image.file_format = 'OPEN_EXR' if float_buffer else 'PNG'
        image.filepath_raw = path
        target = tree.nodes.new('ShaderNodeTexImage')
        target.image = image
        tree.nodes.active = target
        emit = None
        pruned = False
        original = obj.material_slots[slot_index].material
        try:
            if channel != 'normal':
                emit = tree.nodes.new('ShaderNodeEmission')
                compiler.connect(tree, value, emit.inputs['Color'])
                emit.inputs['Strength'].default_value = 1
                tree.links.new(emit.outputs[0], compiler.output.inputs['Surface'])
                compiler.prune_to_output((target,))
                pruned = True
            else:
                tree.links.new(compiler.surface, compiler.output.inputs['Surface'])
            obj.material_slots[slot_index].material = mat
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            # Cycles compiles every material slot on the object for every bake.
            # Compiling all original procedural graphs repeatedly is extremely
            # expensive and can exceed its closure limit even though those slots
            # do not contribute to this map. Replace them temporarily with one
            # tiny scratch material writing to a separate image.
            scratch = image.copy()
            scratch_mat = bpy.data.materials.new('_B2H_scratch')
            scratch_mat.use_nodes = True
            scratch_tree = scratch_mat.node_tree
            scratch_tree.nodes.clear()
            scratch_output = scratch_tree.nodes.new('ShaderNodeOutputMaterial')
            if channel == 'normal':
                scratch_shader = scratch_tree.nodes.new('ShaderNodeBsdfPrincipled')
            else:
                scratch_shader = scratch_tree.nodes.new('ShaderNodeEmission')
                scratch_shader.inputs['Color'].default_value = (0, 0, 0, 1)
            scratch_tree.links.new(scratch_shader.outputs[0], scratch_output.inputs['Surface'])
            scratch_target = scratch_tree.nodes.new('ShaderNodeTexImage')
            scratch_target.image = scratch
            scratch_tree.nodes.active = scratch_target
            replaced = []
            try:
                for i, slot in enumerate(obj.material_slots):
                    if i != slot_index:
                        replaced.append((i, slot.material))
                        slot.material = scratch_mat
                # Padding is only a narrow filter-safe border around UV
                # islands. Extending it across the whole image creates large
                # streaks and makes the texture look stretched.
                margin = bake_margin(settings)
                result = bpy.ops.object.bake(type='NORMAL' if channel == 'normal' else 'EMIT',
                    use_clear=True, use_selected_to_active=False, use_cage=False,
                    target='IMAGE_TEXTURES', margin=margin, margin_type='EXTEND',
                    uv_layer=obj.data.uv_layers.active.name)
                if 'FINISHED' not in result: raise RuntimeError(f'Bake failed: {obj.name}/{channel}')
                self._save_image(image, path)
                if not os.path.isfile(path) or os.path.getsize(path) == 0:
                    raise RuntimeError(f'Empty bake output: {path}')
                expected = b'\x76\x2f\x31\x01' if path.lower().endswith('.exr') else b'\x89PNG'
                with open(path, 'rb') as baked_file:
                    if baked_file.read(4) != expected:
                        raise RuntimeError(f'Bake encoder produced the wrong format: {path}')
            finally:
                for index, material in replaced:
                    obj.material_slots[index].material = material
                bpy.data.materials.remove(scratch_mat)
                bpy.data.images.remove(scratch)
        finally:
            obj.material_slots[slot_index].material = original
            if emit: tree.nodes.remove(emit)
            if not pruned:
                tree.links.new(compiler.surface, compiler.output.inputs['Surface'])
            tree.nodes.remove(target)
            bpy.data.images.remove(image)
        return time.perf_counter()-started
