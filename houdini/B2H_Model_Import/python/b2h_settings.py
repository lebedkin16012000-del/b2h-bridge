"""Per-user settings for B2H Model Import."""

import json
import os
import tempfile


DEFAULTS = {
    "b2h_library_roots": [],
    "scan_depth": 6,
    "scan_limit": 2000,
}


def settings_path():
    root = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(root, "B2H Asset Library", "settings.json")


def _legacy_settings_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")


def load_settings():
    path = settings_path()
    source = path if os.path.isfile(path) else _legacy_settings_path()
    data = {}
    if os.path.isfile(source):
        try:
            with open(source, "r", encoding="utf-8-sig") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError, TypeError):
            data = {}
    result = dict(DEFAULTS)
    result.update(data)
    return result


def save_settings(settings_dict):
    path = settings_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    payload = dict(DEFAULTS)
    payload.update(settings_dict or {})
    descriptor, temp_path = tempfile.mkstemp(prefix="b2h_settings_", suffix=".json", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def remember_root(folder):
    data = load_settings()
    roots = [item for item in data.get("b2h_library_roots", []) if item != folder]
    data["b2h_library_roots"] = [folder] + roots[:7]
    save_settings(data)
