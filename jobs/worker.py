"""Entry point executed by a separate Blender process, never imported by the UI."""
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback
from types import SimpleNamespace
import bpy

def main():
    job = Path(sys.argv[sys.argv.index('--')+1]).resolve()
    request = json.loads((job/'request.json').read_text(encoding='utf8'))
    sys.path.insert(0, request['package_parent'])
    # Factory startup avoids importing the installed version of the bridge.
    from B2H_Bridge.export.pipeline import run, file_digest, write_json
    from B2H_Bridge.jobs.status import StatusJournal
    journal = StatusJournal(job)
    def status(state, message, progress=0, **extra):
        if state in {'running','publishing'} and (job/'cancel').exists():
            raise InterruptedError('Export cancelled; previous export preserved')
        journal.write(dict(state=state,message=message,progress=progress,**extra))
    try:
        for image_name, path in request.get('image_overrides', {}).items():
            image = bpy.data.images.get(image_name)
            if image:
                image.filepath = path
                image.source = 'FILE'
                image.reload()
        # Conservative cache: entire scene snapshot, settings, and external files.
        # Any change invalidates it; no stale material-name-only cache hits.
        digest = hashlib.sha256()
        digest.update(file_digest(job/'scene.blend').encode())
        digest.update(json.dumps(request['settings'],sort_keys=True).encode())
        digest.update(json.dumps(request['objects']).encode())
        for code in sorted(Path(__file__).resolve().parents[1].rglob('*.py')):
            digest.update(file_digest(code).encode())
        for path in sorted(set(bpy.utils.blend_paths(absolute=True))):
            if os.path.isfile(path): digest.update(file_digest(path).encode())
        result = run(SimpleNamespace(**request['settings']), request['objects'], job, digest.hexdigest(), status)
        status('done', 'Export completed', 1, result=result)
    except InterruptedError as error:
        status('cancelled', str(error))
    except Exception as error:
        traceback.print_exc()
        status('error', str(error))
        raise

if __name__ == '__main__': main()
