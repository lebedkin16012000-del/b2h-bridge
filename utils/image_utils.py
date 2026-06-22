"""
Утилиты для работы с изображениями
"""

import bpy
import os
from typing import Any, Dict, Optional, Tuple
from ..utils import BakeLogger


def image_average_rgb_luma(image_path: str, sample_limit: int = 4096) -> Optional[float]:
    """
    Вычисляет среднюю яркость изображения.

    Args:
        image_path: Путь к изображению
        sample_limit: Максимальное количество пикселей для выборки

    Returns:
        Средняя яркость или None
    """
    if not image_path or not os.path.exists(image_path):
        return None

    try:
        img = bpy.data.images.load(image_path, check_existing=True)
        pixels = img.pixels
        length = len(pixels)

        if length < 4:
            return None

        # Выборка пикселей для производительности
        step = max(4, int(length / max(sample_limit, 1)))
        total = 0.0
        count = 0

        for i in range(0, length, step):
            try:
                r = pixels[i]
                g = pixels[i + 1]
                b = pixels[i + 2]
                a = pixels[i + 3]

                # Игнорируем прозрачные/пустые пиксели
                if a < 0.05:
                    continue

                total += (r + g + b) / 3.0
                count += 1
            except Exception:
                pass

        if count <= 0:
            return None

        return total / count

    except Exception as e:
        BakeLogger.log("IMAGE LUMINANCE FAILED:", image_path, e)
        return None


def image_is_dark_or_bad_for_metal(image_path: str, threshold: float = 0.16) -> bool:
    """
    Проверяет, является ли изображение слишком темным для металла.

    Args:
        image_path: Путь к изображению
        threshold: Порог яркости

    Returns:
        True если изображение слишком темное
    """
    avg = image_average_rgb_luma(image_path)
    if avg is None:
        return False
    return avg < threshold


def pad_image_black_background(image_path: str, iterations: int = 24,
                               alpha_threshold: float = 0.01,
                               luma_threshold: float = 0.015) -> bool:
    """
    Простое расширение текстуры: растягивает цветные пиксели в черный/пустой фон.
    Предотвращает черные границы UV островов в Houdini/Karma.

    Args:
        image_path: Путь к изображению
        iterations: Количество итераций расширения
        alpha_threshold: Порог альфа-канала
        luma_threshold: Порог яркости

    Returns:
        True если успешно
    """
    if not image_path or not os.path.exists(image_path):
        return False

    ext = os.path.splitext(image_path.lower())[1]
    if ext not in {".png", ".jpg", ".jpeg", ".bmp", ".tga"}:
        # Не изменяем EXR нормали или HDR/data карты
        return False

    try:
        img = bpy.data.images.load(image_path, check_existing=True)
        w, h = img.size

        if w <= 2 or h <= 2:
            return False

        pix = list(img.pixels[:])
        total = w * h

        def is_valid(idx: int) -> bool:
            """Проверяет, является ли пиксель валидным (не пустым)"""
            r = pix[idx]
            g = pix[idx + 1]
            b = pix[idx + 2]
            a = pix[idx + 3]
            luma = (r + g + b) / 3.0
            return a > alpha_threshold and luma > luma_threshold

        # Маска валидных пикселей
        valid = [False] * total
        for p in range(total):
            valid[p] = is_valid(p * 4)

        # Итеративное расширение
        for _ in range(int(iterations)):
            changed = False
            new_pix = pix[:]
            new_valid = valid[:]

            for y in range(h):
                for x in range(w):
                    p = y * w + x
                    if valid[p]:
                        continue

                    found = None
                    # Поиск в 8-соседях
                    for nx, ny in (
                        (x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1),
                        (x - 1, y - 1), (x + 1, y - 1), (x - 1, y + 1), (x + 1, y + 1)
                    ):
                        if 0 <= nx < w and 0 <= ny < h:
                            np = ny * w + nx
                            if valid[np]:
                                found = np * 4
                                break

                    if found is not None:
                        i = p * 4
                        new_pix[i] = pix[found]
                        new_pix[i + 1] = pix[found + 1]
                        new_pix[i + 2] = pix[found + 2]
                        new_pix[i + 3] = 1.0
                        new_valid[p] = True
                        changed = True

            pix = new_pix
            valid = new_valid

            if not changed:
                break

        # Сохраняем изменения
        img.pixels[:] = pix
        img.save()
        BakeLogger.log("TEXTURE PADDING:", os.path.basename(image_path), "iterations", iterations)
        return True

    except Exception as e:
        BakeLogger.log("TEXTURE PADDING FAILED:", image_path, e)
        return False


def get_image_stats(image_path: str) -> Optional[Dict[str, Any]]:
    """
    Получает статистику изображения.

    Args:
        image_path: Путь к изображению

    Returns:
        Словарь со статистикой или None
    """
    if not image_path or not os.path.exists(image_path):
        return None

    try:
        img = bpy.data.images.load(image_path, check_existing=True)
        w, h = img.size
        size_bytes = os.path.getsize(image_path)

        return {
            "width": w,
            "height": h,
            "size_bytes": size_bytes,
            "channels": len(img.channels),
            "is_float": img.is_float,
            "file_format": img.file_format,
        }
    except Exception as e:
        BakeLogger.log("IMAGE STATS FAILED:", image_path, e)
        return None


def validate_image_for_export(image_path: str, role: str = "texture") -> Tuple[bool, str]:
    """
    Проверяет изображение для экспорта.

    Args:
        image_path: Путь к изображению
        role: Роль текстуры

    Returns:
        Кортеж (валидно, сообщение об ошибке)
    """
    if not image_path:
        return False, "Путь к изображению не указан"

    if not os.path.exists(image_path):
        return False, f"Изображение не найдено: {image_path}"

    if os.path.getsize(image_path) == 0:
        return False, "Изображение пустое"

    # Проверка формата
    ext = os.path.splitext(image_path.lower())[1]
    if ext not in {".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff", ".bmp", ".tga"}:
        return False, f"Неподдерживаемый формат: {ext}"

    # Проверка размера
    try:
        img = bpy.data.images.load(image_path, check_existing=True)
        w, h = img.size
        if w == 0 or h == 0:
            return False, "Неверный размер изображения"
        if w > 8192 or h > 8192:
            return False, f"Слишком большое изображение: {w}x{h}"
    except Exception as e:
        return False, f"Ошибка загрузки изображения: {str(e)}"

    return True, "OK"
