"""
Конфигурация аддона Blender To Houdini Bridge
"""

import bpy
import os
from typing import Dict, Any, Set

# Константы
# Relative to the current .blend file; no user-specific export path is embedded.
DEFAULT_EXPORT_DIR = os.path.join(os.path.expanduser("~"), "Documents", "B2H_Exports")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff", ".bmp", ".tga"}

# Классификация узлов для анализа материалов
COMPLEX_NODES = {
    "TEX_NOISE", "TEX_VORONOI", "VALTORGB", "MIX", "MIX_RGB", "GAMMA",
    "CURVE_RGB", "HUE_SAT", "BRIGHTCONTRAST", "INVERT", "MATH", "VECT_MATH",
    "MAP_RANGE", "TEX_COORD", "MAPPING", "BUMP", "GROUP"
}

PROCEDURAL_GENERATORS = {
    "TEX_NOISE", "TEX_VORONOI", "TEX_MUSGRAVE", "TEX_WAVE", "TEX_MAGIC",
    "TEX_BRICK", "TEX_GRADIENT", "TEX_CHECKER", "TEX_SKY"
}

PROCESSING_NODES = {
    "VALTORGB", "MIX", "MIX_RGB", "GAMMA", "CURVE_RGB", "HUE_SAT",
    "BRIGHTCONTRAST", "INVERT", "MATH", "VECT_MATH", "MAP_RANGE",
    "RGBTOBW", "SEPRGB", "COMBRGB", "SEPXYZ", "COMBXYZ"
}

UTILITY_NODES = {
    "TEX_COORD", "MAPPING", "UVMAP", "ATTRIBUTE"
}

# Роли текстур и их ключевые слова для классификации
TEXTURE_ROLES = {
    "basecolor": {
        "good": ["basecolor", "base_color", "base-col", "albedo", "diffuse", "diff", "color", "colour", "col", "subsurfacecolor", "subsurface_color"],
        "bad": ["ao", "ambient", "occlusion", "rough", "gloss", "normal", "nrm", "nor", "bump", "height", "disp", "opacity", "alpha", "metal", "spec"],
    },
    "roughness": {
        "good": ["roughness", "rough", "gloss", "glossiness", "specularroughness"],
        "bad": ["basecolor", "albedo", "diffuse", "color", "normal", "opacity", "alpha", "ao"],
    },
    "metallic": {
        "good": ["metallic", "metalness", "metal", "metall"],
        "bad": ["basecolor", "albedo", "diffuse", "normal", "rough", "opacity", "alpha", "ao"],
    },
    "normal": {
        "good": ["normal", "normalgl", "normal_ogl", "nor_gl", "nrm", "norm"],
        "bad": ["basecolor", "albedo", "diffuse", "rough", "opacity", "alpha", "ao"],
    },
    "opacity": {
        "good": ["opacity", "alpha", "mask", "cutout", "transparent", "transparency"],
        "bad": ["basecolor", "albedo", "diffuse", "rough", "normal", "ao"],
    },
    "emission": {
        "good": ["emission", "emit", "emissive"],
        "bad": ["rough", "normal", "ao", "opacity", "alpha"],
    },
}

# Настройки по умолчанию для профилей запекания
BAKE_PROFILES = {
    "fast": {
        "samples": 4,
        "resolution": 1024,
        "use_gpu": True,
        "normal_exr": False,
        "texture_padding": False,
    },
    "balanced": {
        "samples": 8,
        "resolution": 2048,
        "use_gpu": True,
        "normal_exr": True,
        "texture_padding": True,
        "texture_padding_iterations": 16,
    },
    "production": {
        "samples": 32,
        "resolution": 4096,
        "use_gpu": True,
        "normal_exr": True,
        "texture_padding": True,
        "texture_padding_iterations": 24,
    },
}
