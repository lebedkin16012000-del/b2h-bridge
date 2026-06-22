"""
Утилиты для аддона Blender To Houdini Bridge
"""

import bpy
import os
import re
import shutil
import traceback
from typing import List, Optional, Set
from .. import config


# One Blender image is often referenced by several material channels. Keep its
# exported path stable during a single export after JPG-to-PNG conversion.
_EXPORTED_IMAGE_PATHS = {}


class BakeLogger:
    """Логгер для операций запекания"""

    _log: List[str] = []

    @classmethod
    def log(cls, *parts):
        """Добавить запись в лог"""
        text = " ".join(str(p) for p in parts)
        cls._log.append(text)
        print(f"[BTH] {text}")

    @classmethod
    def clear(cls):
        """Очистить лог"""
        cls._log.clear()

    @classmethod
    def get_log(cls) -> List[str]:
        """Получить полный лог"""
        return cls._log.copy()


def safe_name(name: Optional[str], fallback: str = "Asset") -> str:
    """
    Создает безопасное имя для файлов и объектов.

    Args:
        name: Исходное имя
        fallback: Имя по умолчанию

    Returns:
        Безопасное имя
    """
    name = str(name or fallback).strip().replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9_]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if not name:
        name = fallback
    if name[0].isdigit():
        name = "_" + name
    return name


def clean_material_name(name: str) -> str:
    """
    Очищает имя материала от префиксов и суффиксов.

    Args:
        name: Исходное имя материала

    Returns:
        Очищенное имя
    """
    name = safe_name(name, "Material")
    for prefix in ["blender_asset_UV_", "blender_asset_", "UV_"]:
        if name.startswith(prefix):
            name = name[len(prefix):]
    name = re.sub(r"_Mat(_\d+)?$", "", name, flags=re.IGNORECASE)
    return safe_name(name, "Material")


def norm(path: Optional[str]) -> Optional[str]:
    """
    Нормализует путь, преобразуя обратные слеши в прямые.

    Args:
        path: Путь для нормализации

    Returns:
        Нормализованный путь или None
    """
    if not path:
        return None
    return os.path.abspath(path).replace("\\", "/")


def ensure_dir(path: str):
    """
    Создает директорию, если она не существует.

    Args:
        path: Путь к директории
    """
    if path:
        os.makedirs(path, exist_ok=True)


def unique_path(folder: str, filename: str) -> str:
    """
    Создает уникальный путь для файла.

    Args:
        folder: Папка для сохранения
        filename: Имя файла

    Returns:
        Уникальный путь
    """
    ensure_dir(folder)
    base, ext = os.path.splitext(filename)
    if not ext:
        ext = ".png"
    out = os.path.join(folder, base + ext)
    i = 1
    while os.path.exists(out):
        out = os.path.join(folder, f"{base}_{i:03d}{ext}")
        i += 1
    return out


def normalize_texture_name(name: str, force_ext: Optional[str] = None) -> str:
    """
    Нормализует имя текстуры.

    Args:
        name: Исходное имя текстуры
        force_ext: Принудительное расширение файла

    Returns:
        Нормализованное имя
    """
    name = str(name or "texture").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9_\-.]+", "_", name).strip("._") or "texture"
    low = name.lower()

    # Исправление имен типа "texture.png.001"
    for ext in sorted(config.IMAGE_EXTS, key=len, reverse=True):
        token = ext + "."
        if token in low:
            idx = low.rfind(token)
            suffix = name[idx + len(ext) + 1:]
            if suffix.isdigit():
                name = name[:idx] + "_" + suffix + ext
                break

    base, ext = os.path.splitext(name)
    if force_ext:
        return base + force_ext
    if ext.lower() not in config.IMAGE_EXTS:
        return base + ".png"
    if ext.lower() in {".tif", ".tiff"}:
        return base + ".png"
    return base + ext.lower()


def texture_role_score(image: bpy.types.Image, role: str) -> int:
    """
    Оценивает пригодность изображения для роли.
    Меньшая оценка = лучше.

    Args:
        image: Изображение Blender
        role: Роль текстуры (basecolor, roughness и т.д.)

    Returns:
        Оценка пригодности
    """
    name = ""
    try:
        raw = getattr(image, "filepath", "") or getattr(image, "filepath_raw", "")
        name = (image.name + " " + os.path.basename(raw)).lower()
    except Exception:
        name = str(getattr(image, "name", "")).lower()

    role = str(role or "").lower()
    cfg = config.TEXTURE_ROLES.get(role, {"good": [role], "bad": []})

    score = 50  # Базовая оценка

    # Понижение оценки за хорошие ключевые слова
    for token in cfg["good"]:
        if token in name:
            score -= 40

    # Повышение оценки за плохие ключевые слова
    for token in cfg["bad"]:
        if token in name:
            score += 80

    # AO никогда не должен быть basecolor
    if role == "basecolor" and any(x in name for x in ["_ao", "-ao", " ao", "ambient", "occlusion"]):
        score += 200

    return score


def copy_or_save_image(image: bpy.types.Image, texture_dir: str, role: str = "texture") -> Optional[str]:
    """
    Копирует или сохраняет изображение в указанную директорию.

    Args:
        image: Изображение Blender
        texture_dir: Директория для сохранения
        role: Роль текстуры

    Returns:
        Путь к сохраненному файлу или None
    """
    if not image:
        return None

    ensure_dir(texture_dir)

    raw = getattr(image, "filepath", "") or getattr(image, "filepath_raw", "")
    src = bpy.path.abspath(raw) if raw else ""
    ext = os.path.splitext(src.lower())[1] if src else ""

    # Определяем, нужно ли сохранять как PNG
    # Houdini bridge textures must be portable PNG files. Convert JPG/JPEG
    # before writing the bridge, while retaining EXR normal-map support.
    force_png = (
        not src or
        not os.path.exists(src) or
        bool(getattr(image, "packed_file", None)) or
        ext in {".jpg", ".jpeg", ".tif", ".tiff"}
    )

    filename_source = image.name or os.path.basename(src) or role

    if force_png:
        # Сохраняем как PNG
        try:
            image_id = image.as_pointer()
        except Exception:
            image_id = id(image)
        cache_key = (os.path.normcase(os.path.abspath(texture_dir)), image_id)
        cached_path = _EXPORTED_IMAGE_PATHS.get(cache_key)
        if cached_path and os.path.isfile(cached_path):
            return norm(cached_path)

        dst = unique_path(texture_dir, normalize_texture_name(filename_source, force_ext=".png"))
        old_raw = getattr(image, "filepath_raw", "")
        old_fmt = getattr(image, "file_format", "PNG")

        try:
            image.filepath_raw = dst
            image.file_format = "PNG"
            image.save()
            dst = norm(dst)
            _EXPORTED_IMAGE_PATHS[cache_key] = dst
            return dst
        except Exception as e:
            BakeLogger.log("SAVE IMAGE FAILED:", image.name, e)
            return None
        finally:
            try:
                image.filepath_raw = old_raw
                image.file_format = old_fmt
            except Exception:
                pass
    else:
        # Копируем существующий файл
        dst = os.path.join(texture_dir, normalize_texture_name(os.path.basename(src)))
        try:
            if os.path.abspath(src) != os.path.abspath(dst):
                if os.path.exists(dst):
                    try:
                        if os.path.getsize(src) != os.path.getsize(dst):
                            dst = unique_path(texture_dir, os.path.basename(dst))
                    except Exception:
                        dst = unique_path(texture_dir, os.path.basename(dst))
                shutil.copy2(src, dst)
            return norm(dst)
        except Exception as e:
            BakeLogger.log("COPY IMAGE FAILED:", src, e)
            return None


def cleanup_texture_folder(texture_dir: str, keep_files: Optional[Set[str]] = None):
    """
    Очищает папку с текстурами от старых файлов.

    Args:
        texture_dir: Папка с текстурами
        keep_files: Множество файлов для сохранения
    """
    keep_files = {
        os.path.normcase(os.path.abspath(path))
        for path in (keep_files or [])
        if path
    }
    if not os.path.isdir(texture_dir):
        return

    try:
        for fn in os.listdir(texture_dir):
            fp = os.path.join(texture_dir, fn)
            if os.path.isfile(fp) and os.path.normcase(os.path.abspath(fp)) not in keep_files:
                try:
                    os.remove(fp)
                except Exception:
                    pass
    except Exception as e:
        BakeLogger.log("CLEANUP FAILED:", texture_dir, e)


def get_principled(mat: bpy.types.Material) -> Optional[bpy.types.ShaderNodeBsdfPrincipled]:
    """
    Находит Principled BSDF узел в материале.

    Args:
        mat: Материал Blender

    Returns:
        Principled BSDF узел или None
    """
    if not mat or not mat.use_nodes:
        return None

    for n in mat.node_tree.nodes:
        if n.type == "BSDF_PRINCIPLED":
            return n

    return None


def socket_value(node: bpy.types.Node, name: str, default=None):
    """
    Получает значение сокета узла.

    Args:
        node: Узел Blender
        name: Имя сокета
        default: Значение по умолчанию

    Returns:
        Значение сокета
    """
    if not node or name not in node.inputs:
        return default

    try:
        v = node.inputs[name].default_value
        if hasattr(v, "__len__") and not isinstance(v, str):
            return list(v)
        return v
    except Exception:
        return default


def socket_is_linked(node: bpy.types.Node, socket_name: str) -> bool:
    """
    Проверяет, подключен ли сокет.

    Args:
        node: Узел Blender
        socket_name: Имя сокета

    Returns:
        True если с��кет подключен
    """
    try:
        return bool(node and socket_name in node.inputs and node.inputs[socket_name].is_linked)
    except Exception:
        return False
