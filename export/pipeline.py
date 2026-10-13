"""Background-only export pipeline: prepare, bake, export, publish."""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import time
import uuid
from datetime import datetime, timezone
import bpy
from ..core.channels import ChannelCompiler, CHANNELS, linked, rgba
from ..baking.session import (BakeSession, prepare_uv, create_uv_bake_plane,
                              remove_uv_bake_plane)
from ..utils import safe_name, clean_material_name, copy_or_save_image

MANIFEST_SCHEMA_VERSION = 1
GENERATOR_NAME = 'B2H Bridge'
GENERATOR_VERSION = '4.8.4-beta'

def asset_identity(export_dir, asset, requested_id=''):
    """Resolve identity from the last successfully published manifest.

    Reading only the destination manifest means a failed staged export never
    consumes a revision number.
    """
    previous = {}
    manifest = Path(export_dir)/(asset+'_bridge.json')
    if manifest.is_file():
        try:
            previous = json.loads(manifest.read_text(encoding='utf8'))
        except (OSError, ValueError, TypeError):
            previous = {}
    previous_id = str(previous.get('asset_id', '')).strip()
    asset_id = previous_id or str(requested_id or '').strip() or str(uuid.uuid4())
    previous_revision = previous.get('asset_revision', 0) if previous_id == asset_id else 0
    try:
        revision = max(0, int(previous_revision)) + 1
    except (TypeError, ValueError):
        revision = 1
    return asset_id, revision

def manifest_metadata(settings, asset):
    asset_id, revision = asset_identity(
        settings.export_dir, asset, getattr(settings, 'asset_id', '')
    )
    return {
        'schema_version': MANIFEST_SCHEMA_VERSION,
        'generator': GENERATOR_NAME,
        'generator_version': GENERATOR_VERSION,
        'asset_id': asset_id,
        'asset_revision': revision,
        'export_time': datetime.now(timezone.utc).isoformat(),
        'blender_version': bpy.app.version_string,
        'features': {
            'background_export': True,
            'materialx_files': bool(settings.export_materialx_files),
            'split_by_material': bool(settings.split_by_material),
            'material_reuse_mode': getattr(settings, 'material_reuse_mode', 'BLENDER_MATERIAL'),
            'texture_cache': bool(settings.enable_texture_cache),
            'full_square_bake_uv': bool(getattr(settings, 'full_square_bake_uv', False)),
            'force_uv_grid_bake_all': bool(getattr(settings, 'force_uv_grid_bake_all', False)),
            'udim_metadata_only': bool(settings.udim_mode),
            'exact_material_assignment': False,
        },
    }

def file_digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(4*1024*1024), b''): h.update(block)
    return h.hexdigest()

def valid_texture(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0: return False
    expected = b'\x76\x2f\x31\x01' if path.suffix.lower() == '.exr' else b'\x89PNG'
    try:
        with path.open('rb') as stream: return stream.read(4) == expected
    except OSError:
        return False

def identity(text):
    return safe_name(text)[:70] + '_' + hashlib.sha256(text.encode()).hexdigest()[:10]

def material_signature(material, stage):
    """Hash the complete portable appearance, independent of object/slot names."""
    texture_hashes = {}
    for role, relative in sorted(material.get('textures', {}).items()):
        path = Path(stage)/relative
        texture_hashes[role] = file_digest(path) if path.is_file() else str(relative)
    payload = {
        'textures': texture_hashes,
        'defaults': material.get('defaults', {}),
        'hints': material.get('hints', {}),
        'metal_basecolor_ignored': bool(material.get('metal_basecolor_ignored', False)),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(encoded.encode('utf8')).hexdigest()

def material_public_base(material):
    custom = getattr(material, 'bth_export_name', '') or material.get('bth_export_name', '')
    if custom:
        return safe_name(str(custom), 'material').lower()[:48]
    cleaned = safe_name(material.name, 'material').lower()
    cleaned = re.sub(r'(?:_\d{3})+$', '', cleaned).strip('_')
    tokens = [token for token in cleaned.split('_') if token]
    generic = {'ar3dmat', 'procedural', 'stylized', 'material', 'shader'}
    while tokens and tokens[0] in generic:
        tokens.pop(0)
    if len(tokens) > 2:
        tokens = tokens[-2:]
    return ('_'.join(tokens) or 'material')[:48]

def allocate_public_stem(base, used):
    count = used.get(base, 0) + 1
    used[base] = count
    return base if count == 1 else f'{base}_{count:02d}'

def material_uses_object_data(material):
    seen = set()
    def walk(tree):
        if not tree or tree.as_pointer() in seen: return False
        seen.add(tree.as_pointer())
        for node in tree.nodes:
            if node.type == 'OBJECT_INFO' and any(output.is_linked for output in node.outputs):
                return True
            if node.type == 'TEX_COORD' and any(output.is_linked and output.name == 'Object' for output in node.outputs):
                return True
            if node.type == 'GROUP' and node.node_tree and walk(node.node_tree):
                return True
        return False
    return walk(material.node_tree if material and material.use_nodes else None)

def material_supports_uv_plane_bake(material):
    """Use a full-tile plane only when the shader is driven exclusively by UV.

    Object, Generated and geometry coordinates change when evaluated on a
    plane, so those materials must continue to bake on their real mesh.
    """
    seen = set()
    found_uv = False
    unsafe = False

    def walk(tree):
        nonlocal found_uv, unsafe
        if not tree or tree.as_pointer() in seen:
            return
        seen.add(tree.as_pointer())
        for node in tree.nodes:
            if node.type == 'TEX_COORD':
                linked_outputs = {output.name for output in node.outputs if output.is_linked}
                if 'UV' in linked_outputs:
                    found_uv = True
                if linked_outputs - {'UV'}:
                    unsafe = True
            elif node.type == 'UVMAP' and any(output.is_linked for output in node.outputs):
                found_uv = True
            elif node.type in {'OBJECT_INFO', 'NEW_GEOMETRY'} and any(
                    output.is_linked for output in node.outputs):
                unsafe = True
            elif node.type == 'ATTRIBUTE' and any(output.is_linked for output in node.outputs):
                unsafe = True

            vector = node.inputs.get('Vector') if hasattr(node, 'inputs') else None
            if (vector is not None and not vector.is_linked and
                    node.type not in {'MAPPING', 'VECTOR_MATH'}):
                # Texture nodes with an unconnected Vector implicitly depend
                # on coordinates that are not proven portable to the plane.
                unsafe = True
            if node.type == 'GROUP' and node.node_tree:
                walk(node.node_tree)

    walk(material.node_tree if material and material.use_nodes else None)
    return found_uv and not unsafe

def compatible_binding_signature(obj, slot, material):
    polygons = [p for p in obj.data.polygons if p.material_index == slot]
    loops = [index for polygon in polygons for index in polygon.loop_indices]
    vertices = sorted({index for polygon in polygons for index in polygon.vertices})
    uv = obj.data.uv_layers.active
    payload = {
        'vertices': [[round(value, 6) for value in obj.data.vertices[index].co] for index in vertices],
        'polygons': [list(p.vertices) for p in polygons],
        'uv': [[round(uv.data[index].uv.x, 6), round(uv.data[index].uv.y, 6)] for index in loops] if uv else None,
    }
    if material_uses_object_data(material):
        payload['object'] = obj.name
    return hashlib.sha256(json.dumps(payload, separators=(',', ':')).encode()).hexdigest()

def local_cache_dir(export_dir, source_key):
    """Keep acceleration data outside the package users send to other people."""
    base = Path(os.environ.get('LOCALAPPDATA') or (Path.home()/'.cache'))
    namespace = hashlib.sha256(str(Path(export_dir).resolve()).casefold().encode()).hexdigest()[:16]
    return base/'B2H_Bridge'/'cache'/namespace/source_key

def prune_local_cache(cache_dir, keep=3):
    parent = Path(cache_dir).parent
    folders = sorted((p for p in parent.iterdir() if p.is_dir()),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in folders[keep:]:
        shutil.rmtree(stale, ignore_errors=True)

def remove_legacy_export_cache(export_dir):
    export_root = Path(export_dir).resolve()
    legacy = export_root/'.b2h_cache'
    if not legacy.exists(): return
    if legacy.parent.resolve() != export_root:
        raise RuntimeError('Refusing to remove cache outside the export folder')
    if legacy.is_symlink(): legacy.unlink()
    else: shutil.rmtree(legacy)

def deduplicate_texture(role, path, stage, content_index, logs):
    """Share byte-identical outputs of the same semantic channel."""
    path = Path(path)
    key = (role, file_digest(path))
    canonical = content_index.get(key)
    if canonical is None:
        content_index[key] = path
        return path.relative_to(stage).as_posix()
    if canonical != path:
        logs.append(f'DEDUP {path.name} -> {canonical.name}')
    return canonical.relative_to(stage).as_posix()

def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    os.replace(temp, path)

def plain_uv_image(node, obj=None):
    if node.type != 'TEX_IMAGE' or not node.image or node.projection != 'FLAT':
        return False
    if node.image.source not in {'FILE', 'GENERATED'}:
        return False
    vector = node.inputs['Vector']
    if not vector.is_linked:
        return True
    socket = vector.links[0].from_socket
    while socket.node.type == 'REROUTE' and socket.node.inputs[0].is_linked:
        socket = socket.node.inputs[0].links[0].from_socket
    if socket.node.type == 'TEX_COORD' and socket.identifier == 'UV':
        return True
    if socket.node.type == 'UVMAP' and obj is not None:
        active = next((u.name for u in obj.data.uv_layers if u.active_render), None)
        return not socket.node.from_instancer and socket.node.uv_map in {'', active}
    return False


def direct_source(value, role, obj=None):
    if not linked(value): return None
    while value.node.type == 'REROUTE' and value.node.inputs[0].is_linked:
        value = value.node.inputs[0].links[0].from_socket
    component = None
    if value.node.type in {'SEPRGB', 'SEPARATE_COLOR'}:
        node = value.node
        if role == 'basecolor' or (node.type == 'SEPARATE_COLOR' and node.mode != 'RGB'):
            return None
        component = list(node.outputs).index(value)
        if component > 2 or not node.inputs[0].is_linked: return None
        value = node.inputs[0].links[0].from_socket
    node = value.node
    if not plain_uv_image(node, obj): return None
    if role == 'basecolor':
        return (node.image, None) if value.identifier == 'Color' else None
    if role not in {'roughness', 'metallic', 'opacity', 'ior', 'transmission'}:
        return None
    if value.identifier == 'Alpha': component = 3
    elif value.identifier != 'Color': return None
    elif component is None: component = 'luminance'
    return node.image, component


def save_direct_scalar(image, component, path):
    # Extract image channels without rendering the material or altering its UVs.
    import numpy as np
    pixels = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape((-1, image.channels))
    values = pixels[:, :3] @ np.array([.2126, .7152, .0722], dtype=np.float32) if component == 'luminance' else pixels[:, component]
    rgba_pixels = np.ones((len(values), 4), dtype=np.float32)
    rgba_pixels[:, :3] = values[:, None]
    out = bpy.data.images.new('_B2H_channel', width=image.size[0], height=image.size[1], alpha=True, float_buffer=True)
    try:
        out.colorspace_settings.name = 'Non-Color'
        out.pixels.foreach_set(rgba_pixels.ravel())
        out.file_format = 'PNG'
        out.filepath_raw = str(path)
        out.save()
    finally:
        bpy.data.images.remove(out)
    return str(path)


def direct_image(value, role):
    """Only transfer a plain default UV image, never discard Mapping/channel selection."""
    if not linked(value): return None
    node = value.node
    if node.type != 'TEX_IMAGE' or not node.image: return None
    if value.identifier != 'Color' or role != 'basecolor': return None
    if node.inputs['Vector'].is_linked or node.projection != 'FLAT': return None
    if node.image.source not in {'FILE', 'GENERATED'}: return None
    return node.image

def direct_normal(compiler, obj=None):
    if compiler.surface.node.type != 'BSDF_PRINCIPLED': return None
    source = compiler.surface.node.inputs.get('Normal')
    if not source or not source.is_linked: return None
    node = source.links[0].from_node
    if node.type != 'NORMAL_MAP' or node.space != 'TANGENT': return None
    if node.uv_map and (obj is None or node.uv_map != next((u.name for u in obj.data.uv_layers if u.active_render), None)): return None
    if node.inputs['Strength'].is_linked or node.inputs['Strength'].default_value != 1: return None
    source = node.inputs['Color']
    if not source.is_linked: return None
    image_node = source.links[0].from_node
    if not plain_uv_image(image_node, obj): return None
    image = image_node.image
    if not image or not image.colorspace_settings.is_data: return None
    if source.links[0].from_socket.identifier != 'Color': return None
    return image

def publish(stage, destination, clean_roots=()):
    """Rollback previously published files if a filesystem operation fails."""
    stage, destination = Path(stage), Path(destination)
    backup = stage.parent / 'previous'
    applied, removed = [], []
    try:
        staged = {p.relative_to(stage) for p in stage.rglob('*') if p.is_file()}
        for clean_root in clean_roots:
            target_root = destination/clean_root
            if not target_root.is_dir(): continue
            for dst in target_root.rglob('*'):
                if not dst.is_file(): continue
                # Houdini may create and lock RAT derivatives beside source
                # textures. They are not owned by B2H and must not abort a new
                # export while Houdini is open.
                if dst.suffix.lower() == '.rat': continue
                rel = dst.relative_to(destination)
                if rel in staged: continue
                old = backup/'removed'/rel
                old.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, old)
                dst.unlink()
                removed.append((dst, old))
        for src in sorted(stage.rglob('*')):
            if not src.is_file(): continue
            rel = src.relative_to(stage)
            dst, old = destination/rel, backup/rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            existed = dst.exists()
            if existed:
                old.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, old)
            incoming = dst.with_name(dst.name+'.b2h-incoming')
            shutil.copy2(src, incoming)
            os.replace(incoming, dst)
            applied.append((dst, old, existed))
    except Exception:
        for dst, old, existed in reversed(applied):
            if existed: os.replace(old, dst)
            else: dst.unlink(missing_ok=True)
        for dst, old in reversed(removed):
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(old, dst)
        raise

def run(settings, object_names, job_dir, source_key, status):
    from . import export_manager
    started = time.perf_counter()
    asset = safe_name(settings.asset_name, 'blender_asset')
    stage = Path(job_dir).resolve()/'export'
    texture_dir = stage/'textures'/asset
    materialx_dir = stage/'materialx'/asset
    bake_dir = Path(job_dir).resolve()/'bakes'
    texture_dir.mkdir(parents=True, exist_ok=True)
    materialx_dir.mkdir(parents=True, exist_ok=True)
    bake_dir.mkdir(parents=True, exist_ok=True)
    materials, logs, content_index = {}, [], {}
    material_index, exported_materials, material_aliases = {}, {}, {}
    reuse_records, reuse_compatibility, used_public_stems = {}, {}, {}
    forced_reuse_warnings = 0
    objects = [bpy.context.scene.objects.get(n) for n in object_names]
    if not objects or any(o is None or o.type != 'MESH' for o in objects):
        raise ValueError('Export objects changed or are missing in snapshot')
    for obj in objects:
        obj.hide_set(False)
        obj.hide_viewport = False
        obj.hide_render = False
        if not obj.data.materials or any(s.material is None for s in obj.material_slots):
            raise ValueError(f'{obj.name}: empty material slot; assign a material before exporting')
        if obj.data.users > 1: obj.data = obj.data.copy()
    # Device initialisation occurs once, outside all object/channel loops.
    session = BakeSession(settings)
    logs.append('Bake device: ' + session.device)
    if settings.use_gpu_bake and session.device == 'CPU':
        logs.append('WARNING: requested GPU was unavailable; Cycles used CPU')
        status('running', 'GPU unavailable; baking on CPU', 0.0)
    tasks = [(o, i, s.material) for o in objects for i, s in enumerate(o.material_slots)
             if any(p.material_index == i for p in o.data.polygons)]
    reuse_mode = getattr(settings, 'material_reuse_mode', 'BLENDER_MATERIAL')
    logs.append('Material reuse mode: ' + reuse_mode)
    cache_dir = local_cache_dir(settings.export_dir, source_key)
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.utime(cache_dir, None)
    for index, (obj, slot, source) in enumerate(tasks):
        material_base = 0.9 * index / len(tasks)
        material_span = 0.9 / len(tasks)
        status('running', f'{obj.name}: analysing {source.name}', material_base)
        task_name = identity(obj.name+'__'+source.name+'__'+str(slot))
        reuse_key = None
        if reuse_mode == 'BLENDER_MATERIAL':
            reuse_key = ('MATERIAL', source.as_pointer())
        elif reuse_mode == 'COMPATIBLE':
            reuse_key = ('COMPATIBLE', source.as_pointer(), compatible_binding_signature(obj, slot, source))
        if reuse_key is not None and reuse_key in reuse_records:
            name = reuse_records[reuse_key]
            canonical = materials[name]
            if reuse_mode == 'BLENDER_MATERIAL':
                current_compatibility = compatible_binding_signature(obj, slot, source)
                if current_compatibility != reuse_compatibility.get(reuse_key):
                    forced_reuse_warnings += 1
                    logs.append(f'WARNING forced material reuse on different geometry/UV/object data: {obj.name}/{source.name}[{slot}] -> {name}')
            canonical['bindings'] += 1
            if source.name not in canonical['source_materials']:
                canonical['source_materials'].append(source.name)
            material_aliases[task_name] = name
            obj.material_slots[slot].material = exported_materials[name]
            logs.append(f'REUSE {obj.name}/{source.name}[{slot}] -> {name}')
            status('running', f'{obj.name}: reused {name}', material_base + material_span)
            continue
        public_stem = allocate_public_stem(material_public_base(source), used_public_stems)
        compiler = ChannelCompiler(source)
        try:
            values = {role: compiler.compile(role) for role in CHANNELS}
            nodes = list(compiler.nodes())
            reachable = set()
            def visit(node):
                if node in reachable: return
                reachable.add(node)
                for socket in node.inputs:
                    for link in socket.links: visit(link.from_node)
            visit(compiler.output)
            has_normal = any(n.type in {'BUMP','NORMAL_MAP','BEVEL'} for n in reachable)
            if any(n.type == 'GROUP' for n in reachable):
                has_normal = has_normal or any(n.type in {'BUMP','NORMAL_MAP','BEVEL'} for n in nodes)
            textures = {}
            defaults = {'base_color':list(rgba(values['basecolor'])) if not linked(values['basecolor']) else [0.8,0.8,0.8,1],
                        'roughness':float(rgba(values['roughness'])[0]) if not linked(values['roughness']) else 0.5,
                        'metallic':float(rgba(values['metallic'])[0]) if not linked(values['metallic']) else 0.0,
                        'alpha':float(rgba(values['opacity'])[0]) if not linked(values['opacity']) else 1.0,
                        'ior':1.45, 'transmission':0.0, 'emission_strength':1.0}
            bake_roles = [r for r,v in values.items() if linked(v)]
            if not settings.fast_bake_mode:
                bake_roles = list(CHANNELS)
            elif settings.bake_missing_basecolor and 'basecolor' not in bake_roles:
                bake_roles.append('basecolor')
            for key in ('ior', 'transmission'):
                value = values[key]
                if not linked(value): defaults[key] = float(rgba(value)[0])
            # Constant emission still needs a color source in the existing importer.
            if not linked(values['emission']) and max(rgba(values['emission'])[:3]) > 0:
                if 'emission' not in bake_roles: bake_roles.append('emission')
            elif not linked(values['emission']): defaults['emission_strength'] = 0.0
            direct = {}
            if settings.fast_bake_mode or not settings.auto_bake_complex:
                for role in list(bake_roles):
                    source_image = direct_source(values[role], role, obj)
                    if source_image:
                        direct[role] = source_image
                        bake_roles.remove(role)
                    elif (not settings.auto_bake_complex and not linked(values[role])
                          and (role != 'emission' or max(rgba(values[role])[:3]) == 0)):
                        bake_roles.remove(role)
            if has_normal:
                normal_image = direct_normal(compiler, obj) if settings.fast_bake_mode or not settings.auto_bake_complex else None
                if normal_image: direct['normal'] = (normal_image, None)
                else: bake_roles.append('normal')
            if bake_roles and not settings.auto_bake_complex:
                raise ValueError(f'{source.name}: requires baking for {", ".join(bake_roles)}; enable Bake Complex Materials')
            if bake_roles:
                prepare_uv(obj, settings.bake_auto_uv)
            for role, (image, component) in direct.items():
                path = (save_direct_scalar(image, component, texture_dir/(public_stem+'_'+role+'.png'))
                        if component is not None else copy_or_save_image(image, str(texture_dir), role))
                logs.append(f'DIRECT {obj.name}/{source.name}: {role} from {image.name}')
                if not path: raise RuntimeError(f'Could not export {image.name}')
                # Avoid collisions between source images with identical filenames.
                stable = texture_dir/(public_stem+'_'+role+Path(path).suffix.lower())
                if Path(path).resolve() != stable.resolve():
                    shutil.copy2(path, stable)
                textures[role] = deduplicate_texture(role, stable, stage, content_index, logs)
            plane = None
            grid_enabled = bool(getattr(settings, 'full_square_bake_uv', False))
            grid_safe = material_supports_uv_plane_bake(source)
            grid_forced = bool(getattr(settings, 'force_uv_grid_bake_all', False))
            use_uv_plane = grid_enabled and bool(bake_roles) and (grid_safe or grid_forced)
            if use_uv_plane:
                plane = create_uv_bake_plane(obj, source)
                qualifier = 'forced 2D projection' if not grid_safe else 'UV-safe'
                logs.append(f'UV PLANE {obj.name}/{source.name}: full 0-1 texture bake ({qualifier})')
            elif grid_enabled and bake_roles:
                logs.append(f'UV PLANE SKIPPED {obj.name}/{source.name}: material uses non-UV coordinates')
            bake_obj, bake_slot = (plane, 0) if plane else (obj, slot)
            try:
                role_count = max(1, len(bake_roles))
                for role_index, role in enumerate(bake_roles):
                    channel_progress = material_base + material_span * role_index / role_count
                    status('running', f'{obj.name}: baking {role}', channel_progress)
                    ext = '.exr' if role in {'emission', 'ior'} or (role == 'normal' and settings.bake_normals_exr) else '.png'
                    output = bake_dir/(task_name+'_'+role+ext)
                    published = texture_dir/(public_stem+'_'+role+ext)
                    cached = cache_dir/output.name
                    checksum = cached.with_suffix(cached.suffix+'.sha256')
                    cache_valid = (settings.enable_texture_cache and valid_texture(cached) and checksum.is_file()
                                   and checksum.read_text() == file_digest(cached))
                    if cache_valid:
                        shutil.copy2(cached, output)
                        logs.append(f'CACHE {obj.name} {role}')
                    else:
                        # Scalar/color bakes use a disposable compiler so its graph
                        # can be pruned to this single channel before Cycles sees it.
                        role_compiler = compiler
                        try:
                            role_value = values.get(role)
                            if role != 'normal':
                                role_compiler = ChannelCompiler(source)
                                role_value = role_compiler.compile(role)
                            elapsed = session.bake(bake_obj, bake_slot, role_compiler,
                                                   role, role_value, str(output))
                        finally:
                            if role_compiler is not compiler:
                                role_compiler.close()
                        shutil.copy2(output, cached)
                        checksum.write_text(file_digest(cached))
                        logs.append(f'BAKE {obj.name} {role}: {elapsed:.3f}s' +
                                    (' via UV plane' if plane else ''))
                    shutil.copy2(output, published)
                    textures[role] = deduplicate_texture(role, published, stage, content_index, logs)
                    status('running', f'{obj.name}: finished {role}',
                           material_base + material_span * (role_index + 1) / role_count)
            finally:
                remove_uv_bake_plane(plane)
            low = source.name.lower()
            hints = {'alpha': 'opacity' in textures or defaults['alpha'] < 1,
                     'foliage':settings.smart_foliage_mode and any(k in low for k in ('leaf','leaves','foliage','grass','plant')),
                     'glass':settings.smart_glass_mode and
                             ('transmission' in textures or defaults.get('transmission',0)>0.7)}
            candidate = {'original_name':source.name, 'source_materials':[source.name],
                'textures':textures, 'defaults':defaults, 'hints':hints,
                'baked':bool(bake_roles), 'metal_basecolor_ignored':False, 'bindings':1}
            signature = material_signature(candidate, stage)
            name = material_index.get(signature)
            if name is None:
                name = public_stem
                candidate['name'] = name
                candidate['signature'] = signature
                materials[name] = candidate
                material_index[signature] = name
                exported = source.copy()
                exported.name = name
                exported_materials[name] = exported
            else:
                exported = exported_materials[name]
                canonical = materials[name]
                canonical['bindings'] += 1
                if source.name not in canonical['source_materials']:
                    canonical['source_materials'].append(source.name)
                logs.append(f'MERGE {obj.name}/{source.name}[{slot}] -> {name}')
            material_aliases[task_name] = name
            obj.material_slots[slot].material = exported
            if reuse_key is not None:
                reuse_records[reuse_key] = name
                reuse_compatibility[reuse_key] = compatible_binding_signature(obj, slot, source)
        finally:
            compiler.close()
    # Delete only unreferenced files in this job's private staging folder.
    referenced = {stage/p for m in materials.values() for p in m['textures'].values()}
    for p in texture_dir.iterdir():
        if p.is_file() and p not in referenced: p.unlink()
    status('running', 'Exporting USD geometry', 0.92)
    collection = None
    material_keys = {material.as_pointer(): key for key, material in exported_materials.items()}
    if settings.split_by_material:
        objects, collection = export_manager.prepare_split_by_material_objects(objects, material_keys)
    assignments = export_manager.collect_assignments(objects, material_keys)
    for assignment in assignments:
        for key in assignment['materials']:
            if key not in materials:
                raise ValueError(f"{assignment['object_name']}: unknown exported material {key!r}")
    usd_name = asset+('.usdc' if settings.export_usdc else '.usd')
    export_manager.export_usd(str(stage/usd_name), objects)
    source_materials = len({source.as_pointer() for _, _, source in tasks})
    material_stats = {'source_materials':source_materials, 'object_slots':len(tasks),
                      'exported_materials':len(materials), 'merged_bindings':len(tasks)-len(materials),
                      'reuse_mode':reuse_mode, 'reuse_warnings':forced_reuse_warnings}
    logs.append('MATERIALS source={source_materials} bindings={object_slots} unique={exported_materials} merged={merged_bindings}'.format(**material_stats))
    bridge = {'version':GENERATOR_VERSION, **manifest_metadata(settings, asset),
        'asset_name':asset, 'base_dir':'.', 'usd_path':usd_name,
        'texture_dir':'textures/'+asset, 'materialx_dir':'materialx/'+asset, 'materials':materials,
        'material_aliases':material_aliases, 'material_stats':material_stats,
        'assignments':assignments, 'bake_log':logs,
        'axis_fix_enabled':settings.axis_fix_enabled, 'axis_rotate_x':settings.axis_rotate_x,
        'split_by_material':settings.split_by_material, 'instance_sources':{},
        'export_as_instances':bool(settings.export_as_instances), 'udim_mode':bool(settings.udim_mode)}
    if settings.udim_mode:
        logs.append('UDIM Preparation is metadata only; tiled-image baking is not supported.')
    status('running', 'Writing manifests and MaterialX', 0.96)
    write_json(stage/(asset+'_bridge.json'), bridge)
    write_json(stage/(asset+'_assignment_debug.json'), bridge['assignments'])
    write_json(materialx_dir/(asset+'_material_manifest.json'), {'materials':materials})
    if settings.export_materialx_files:
        from .materialx import write_material
        for material in materials.values():
            write_material(materialx_dir/(material['name']+'.mtlx'), material, stage)
    script = export_manager.generate_houdini_script(settings.export_dir, asset)
    (stage/'import_to_houdini.py').write_text(script, encoding='utf8')
    final_script = (Path(settings.export_dir)/'import_to_houdini.py').as_posix()
    (stage/'COPY_THIS_TO_HOUDINI.txt').write_text('exec(open('+repr(final_script)+', encoding="utf-8").read())', encoding='utf8')
    logs.append(f'Total: {time.perf_counter()-started:.3f}s')
    logs.append('Mixed BSDF parameters are a PBR approximation. Inspect the result in Karma.')
    for suffix in ('_bake_report.txt', '_export_report.txt'):
        (stage/(asset+suffix)).write_text('\n'.join(logs), encoding='utf8')
    status('publishing', 'Publishing completed export', 0.99)
    # Every managed cleanup root belongs to this asset. Never scan or remove
    # sibling assets from a shared export library.
    clean_roots = [Path('textures')/asset, Path('materialx')/asset] if settings.cleanup_unused_textures else []
    publish(stage, settings.export_dir, clean_roots)
    remove_legacy_export_cache(settings.export_dir)
    prune_local_cache(cache_dir)
    return {'materials':len(materials), 'material_bindings':len(tasks),
            'merged_materials':len(tasks)-len(materials),
            'reuse_warnings':forced_reuse_warnings,
            'seconds':time.perf_counter()-started, 'usd':str(Path(settings.export_dir)/usd_name)}
