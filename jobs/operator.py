"""Nonblocking foreground launcher; only snapshot creation runs on the UI thread."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
import bpy
from .status import read_latest
from ..utils import safe_name

_active = None
ASSET_REGISTRY_KEY = '_bth_asset_registry_v1'

def persistent_asset_id(scene, export_dir, asset_name):
    """Return one stable ID per sanitized asset name in this Blender scene.

    An already published manifest wins so existing assets keep their identity
    when a scene is first exported with schema v1 or restored from a copy.
    """
    asset = safe_name(asset_name, 'blender_asset')
    previous_id = ''
    manifest = Path(export_dir)/(asset+'_bridge.json')
    if manifest.is_file():
        try:
            previous = json.loads(manifest.read_text(encoding='utf8'))
            previous_id = str(previous.get('asset_id', '')).strip()
        except (OSError, ValueError, TypeError):
            previous_id = ''

    try:
        registry = dict(scene.get(ASSET_REGISTRY_KEY, {}))
    except (TypeError, ValueError):
        registry = {}
    asset_id = previous_id or str(registry.get(asset, '')).strip() or str(uuid.uuid4())
    if registry.get(asset) != asset_id:
        registry[asset] = asset_id
        scene[ASSET_REGISTRY_KEY] = registry
    return asset_id

def format_seconds(seconds):
    seconds = max(0, int(seconds))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f'{hours:d}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'

def estimate_remaining(elapsed, progress):
    if progress < 0.02 or elapsed < 1.0:
        return None
    return elapsed * (1.0 - progress) / progress

class BTH_OT_export(bpy.types.Operator):
    bl_idname = 'bth.export_stable_pbr_bridge'
    bl_label = 'Export Stable PBR Bridge'
    bl_description = 'Export a scene snapshot in a separate Blender process; Esc cancels'

    @classmethod
    def poll(cls, context):
        return _active is None and context.mode == 'OBJECT'

    def execute(self, context):
        global _active
        if bpy.app.background:
            self.report({'ERROR'}, 'Use jobs.worker for background exports')
            return {'CANCELLED'}
        s = context.scene.bth_settings
        objects = [o for o in (context.selected_objects if s.selected_only else context.scene.objects)
                   if o.type == 'MESH' and o.visible_get()]
        if not objects:
            self.report({'ERROR'}, 'Select mesh objects, or disable Selected Only')
            return {'CANCELLED'}
        self._job = Path(tempfile.mkdtemp(prefix='b2h_job_'))
        self._timer = None
        self._process = None
        self._log = None
        self._cancel_requested = False
        self._progress_started = False
        self._started = time.monotonic()
        try:
            s.bth_job_running = True
            s.bth_job_progress = 0.0
            s.bth_job_message = 'Creating scene snapshot'
            s.bth_job_elapsed = '00:00'
            s.bth_job_eta = 'Estimating...'
            s.bth_job_can_cancel = True
            settings = {p.identifier:getattr(s,p.identifier) for p in s.bl_rna.properties
                        if p.identifier != 'rna_type' and p.type in {'BOOLEAN','INT','FLOAT','STRING','ENUM'}}
            settings['export_dir'] = str(Path(bpy.path.abspath(s.export_dir)).resolve())
            if not s.export_dir.strip(): raise ValueError('Choose an export folder')
            settings['asset_id'] = persistent_asset_id(
                context.scene, settings['export_dir'], s.asset_name
            )
            # Preserve unsaved/generated image pixels in sidecars; source images stay intact.
            image_overrides = {}
            for i, image in enumerate(list(bpy.data.images)):
                if image.source in {'GENERATED','FILE'} and (image.is_dirty or image.source == 'GENERATED') and image.has_data:
                    temporary = image.copy()
                    try:
                        path = self._job/f'image_{i}.exr'
                        render = context.scene.render.image_settings
                        previous = (render.file_format, render.color_mode,
                                    render.color_depth, render.exr_codec)
                        try:
                            render.file_format = 'OPEN_EXR'
                            render.color_mode = 'RGBA'
                            render.color_depth = '16'
                            render.exr_codec = 'ZIP'
                            temporary.save_render(str(path), scene=context.scene)
                        finally:
                            (render.file_format, render.color_mode,
                             render.color_depth, render.exr_codec) = previous
                        if path.read_bytes()[:4] != b'\x76\x2f\x31\x01':
                            raise RuntimeError(f'Could not snapshot image {image.name} as OpenEXR')
                        image_overrides[image.name] = str(path)
                    finally:
                        bpy.data.images.remove(temporary)
            package_parent = str(Path(__file__).resolve().parents[2])
            request = dict(settings=settings, objects=[o.name for o in objects],
                           package_parent=package_parent, image_overrides=image_overrides)
            (self._job/'request.json').write_text(json.dumps(request), encoding='utf8')
            result = bpy.ops.wm.save_as_mainfile(filepath=str(self._job/'scene.blend'), copy=True,
                relative_remap=True, check_existing=False, compress=False)
            if 'FINISHED' not in result: raise RuntimeError('Could not create scene snapshot')
            self._log = open(self._job/'worker.log','w',encoding='utf8')
            command = [bpy.app.binary_path,'--background','--factory-startup','--disable-autoexec',str(self._job/'scene.blend'),
                       '--python-exit-code','1','--python',str(Path(__file__).with_name('worker.py')),'--',str(self._job)]
            self._process = subprocess.Popen(command, stdout=self._log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            _active = self
            self._timer = context.window_manager.event_timer_add(0.5, window=context.window)
            context.window_manager.progress_begin(0, 1000)
            self._progress_started = True
            context.window_manager.modal_handler_add(self)
            self.report({'INFO'}, 'Background export started. Esc cancels. Log: '+str(self._job))
            return {'RUNNING_MODAL'}
        except Exception as error:
            self._finish(context)
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}

    def modal(self, context, event):
        state = read_latest(self._job)
        if event.type == 'ESC' and state.get('state') != 'publishing':
            self.request_cancel(context)
            return {'RUNNING_MODAL'}
        if event.type != 'TIMER': return {'PASS_THROUGH'}
        message = 'Cancelling after current pass' if self._cancel_requested else state.get('message','Preparing scene')
        progress = max(0.0, min(1.0, float(state.get('progress', 0.0))))
        elapsed = time.monotonic() - self._started
        remaining = estimate_remaining(elapsed, progress)
        settings = context.scene.bth_settings
        settings.bth_job_progress = progress
        settings.bth_job_message = message
        settings.bth_job_elapsed = format_seconds(elapsed)
        settings.bth_job_eta = format_seconds(remaining) if remaining is not None else 'Estimating...'
        settings.bth_job_can_cancel = state.get('state') != 'publishing' and not self._cancel_requested
        context.window_manager.progress_update(int(progress * 1000))
        context.workspace.status_text_set('B2H: '+message+' | Esc: cancel')
        for area in context.screen.areas:
            if area.type == 'VIEW_3D': area.tag_redraw()
        if self._process.poll() is None: return {'PASS_THROUGH'}
        cancelled = state.get('state') == 'cancelled' or self._cancel_requested
        ok = self._process.returncode == 0 and state.get('state') == 'done'
        final_message = state.get('message','Worker failed')
        if ok:
            result = state.get('result', {})
            if result.get('material_bindings') is not None:
                final_message = ('Export completed: {materials} unique materials from '
                                 '{material_bindings} assignments ({merged_materials} merged)').format(**result)
                if result.get('reuse_warnings'):
                    final_message += f"; {result['reuse_warnings']} compatibility warning(s) in report"
        self._finish(context)
        level = {'INFO'} if ok else ({'WARNING'} if cancelled else {'ERROR'})
        self.report(level, final_message+' | '+str(self._job/'worker.log'))
        return {'FINISHED'} if ok else {'CANCELLED'}

    def request_cancel(self, context):
        if self._cancel_requested:
            return
        (self._job/'cancel').touch()
        self._cancel_requested = True
        context.scene.bth_settings.bth_job_can_cancel = False
        context.scene.bth_settings.bth_job_message = 'Cancelling after current bake pass'
        self.report({'INFO'}, 'Cancellation requested; finishing the current bake pass')

    def _finish(self, context):
        global _active
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        if self._log:
            self._log.close()
            self._log = None
        context.workspace.status_text_set(None)
        if self._progress_started:
            context.window_manager.progress_end()
            self._progress_started = False
        if hasattr(context.scene, 'bth_settings'):
            settings = context.scene.bth_settings
            settings.bth_job_running = False
            settings.bth_job_can_cancel = False
        _active = None

class BTH_OT_cancel_export(bpy.types.Operator):
    bl_idname = 'bth.cancel_export'
    bl_label = 'Cancel B2H Export'
    bl_description = 'Cancel after the current bake pass and preserve the previous export'

    @classmethod
    def poll(cls, context):
        return _active is not None and not _active._cancel_requested

    def execute(self, context):
        _active.request_cancel(context)
        return {'FINISHED'}

def shutdown():
    if _active and _active._process and _active._process.poll() is None:
        _active._process.terminate()
