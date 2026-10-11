"""Lock-free progress exchange between the UI and background Blender."""
import json
from pathlib import Path
from ..export.pipeline import write_json


class StatusJournal:
    def __init__(self, job, retain=8):
        self.job = Path(job)
        self.retain = retain
        existing = []
        for path in self.job.glob('status-*.json'):
            try: existing.append(int(path.stem.rsplit('-', 1)[1]))
            except (IndexError, ValueError): pass
        self.sequence = max(existing, default=0)

    def write(self, payload):
        self.sequence += 1
        path = self.job/f'status-{self.sequence:08d}.json'
        # The final name is new for every update. The UI never opens the temp
        # file, and Windows never needs to replace a file that is being read.
        write_json(path, payload)
        old = sorted(self.job.glob('status-*.json'))[:-self.retain]
        for stale in old:
            try: stale.unlink()
            except OSError: pass
        return path


def read_latest(job):
    job = Path(job)
    candidates = sorted(job.glob('status-*.json'), reverse=True)
    legacy = job/'status.json'
    if not candidates and legacy.is_file():
        candidates.append(legacy)
    for path in candidates:
        try:
            return json.loads(path.read_text(encoding='utf8'))
        except (OSError, ValueError):
            continue
    return {}
