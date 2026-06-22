"""
Основная логика аддона Blender To Houdini Bridge
"""

import bpy
from typing import List, Optional, Set, Tuple
from .. import config
from ..utils import BakeLogger, safe_name, clean_material_name, get_principled, socket_value, socket_is_linked


class MaterialAnalyzer:
    """Анализатор материалов для определения необходимости запекания"""

    def __init__(self):
        self.cache = {}  # type: dict[str, dict]

    def get_export_objects(self, selected_only: bool) -> List[bpy.types.Object]:
        """
        Получает список объектов для экспорта.

        Args:
            selected_only: Только выделенные объекты

        Returns:
            Список mesh объектов
        """
        if selected_only:
            return [o for o in bpy.context.selected_objects if o.type == "MESH" and o.visible_get()]
        return [o for o in bpy.context.scene.objects if o.type == "MESH" and o.visible_get()]

    def used_materials_from_objects(self, objects: List[bpy.types.Object]) -> List[bpy.types.Material]:
        """
        Получает уникальные материалы из объектов.

        Args:
            objects: Список объектов

        Returns:
            Список уникальных материалов
        """
        mats = []
        seen = set()
        for obj in objects:
            for slot in obj.material_slots:
                mat = slot.material
                if mat and mat.name not in seen:
                    mats.append(mat)
                    seen.add(mat.name)
        return mats

    def material_users(self, mat: bpy.types.Material, objects: List[bpy.types.Object]) -> List[bpy.types.Object]:
        """
        Находит объекты, использующие материал.

        Args:
            mat: Материал
            objects: Список объектов для поиска

        Returns:
            Список объектов, использующих материал
        """
        users = []
        for obj in objects:
            for slot in obj.material_slots:
                if slot.material == mat:
                    users.append(obj)
                    break
        return users

    def walk_socket_nodes(self, socket: bpy.types.NodeSocket, depth: int = 0,
                         visited: Optional[Set] = None, nodes: Optional[List] = None) -> List[bpy.types.Node]:
        """
        Собирает узлы, подключенные к сокету.

        Args:
            socket: Сокет для анализа
            depth: Текущая глубина рекурсии
            visited: Множество посещенных узлов
            nodes: Список найденных узлов

        Returns:
            Список узлов
        """
        if visited is None:
            visited = set()
        if nodes is None:
            nodes = []

        if not socket or not getattr(socket, "is_linked", False) or depth > 32:
            return nodes

        try:
            node = socket.links[0].from_node
        except Exception:
            return nodes

        if not node or id(node) in visited:
            return nodes

        visited.add(id(node))
        nodes.append(node)

        # Рекурсивно анализируем группы
        if node.type == "GROUP" and getattr(node, "node_tree", None):
            for gn in node.node_tree.nodes:
                nodes.append(gn)

        for inp in getattr(node, "inputs", []):
            self.walk_socket_nodes(inp, depth + 1, visited, nodes)

        return nodes

    def socket_intent(self, socket: bpy.types.NodeSocket, role: str = "basecolor"):  # Упростили аннотации типов
        """
        Анализирует намерение сокета (нужно ли запекать).

        Args:
            socket: Сокет для анализа
            role: Роль сокета (basecolor, roughness и т.д.)

        Returns:
            Словарь с информацией о намерении
        """
        nodes = self.walk_socket_nodes(socket)
        if not nodes:
            return {
                "linked": False,
                "direct_image": False,
                "has_image": False,
                "has_generator": False,
                "has_processing": False,
                "has_group": False,
                "has_bump": False,
                "needs_bake": False,
                "reason": "default_value",
            }

        types = [getattr(n, "type", "") for n in nodes]
        image_nodes = [n for n in nodes if getattr(n, "type", "") == "TEX_IMAGE" and getattr(n, "image", None)]

        has_generator = any(t in config.PROCEDURAL_GENERATORS for t in types)
        has_processing = any(t in config.PROCESSING_NODES for t in types)
        has_group = any(t == "GROUP" for t in types)
        has_bump = any(t in {"BUMP", "NORMAL_MAP"} for t in types)
        has_image = bool(image_nodes)

        first_type = types[0] if types else ""
        direct_image = first_type == "TEX_IMAGE" and has_image and not (has_generator or has_processing or has_group or has_bump)

        # Mapping/UV утилиты перед изображением безопасны для передачи
        utility_only = has_image and not (has_generator or has_processing or has_group or has_bump) and all(
            t in {"TEX_IMAGE"} or t in config.UTILITY_NODES for t in types
        )

        needs_bake = False
        reason = "direct_image" if (direct_image or utility_only) else "complex_chain"

        if role == "normal":
            # Normal maps могут передаваться, procedural bump нужно запекать
            needs_bake = has_bump and not direct_image
            reason = "procedural_or_bump_normal" if needs_bake else reason
        elif role in {"basecolor", "roughness", "metallic", "opacity", "emission"}:
            needs_bake = bool(has_generator or has_processing or has_group) and not utility_only
            if needs_bake:
                reason = "procedural_or_processed_" + role
        else:
            needs_bake = bool(has_generator or has_processing or has_group or has_bump) and not utility_only

        return {
            "linked": True,
            "direct_image": bool(direct_image or utility_only),
            "has_image": has_image,
            "has_generator": bool(has_generator),
            "has_processing": bool(has_processing),
            "has_group": bool(has_group),
            "has_bump": bool(has_bump),
            "needs_bake": bool(needs_bake),
            "reason": reason,
            "node_types": types[:24],
        }

    def material_intent_analysis(self, mat: bpy.types.Material):  # Упростили аннотации типов
        """
        Анализирует намерения материала для всех каналов.

        Args:
            mat: Материал для анализа

        Returns:
            Словарь с анализом намерений
        """
        cache_key = f"{mat.name}_intent"
        if cache_key in self.cache:
            return self.cache[cache_key]

        bsdf = get_principled(mat)
        roles = {
            "basecolor": "Base Color",
            "roughness": "Roughness",
            "metallic": "Metallic",
            "opacity": "Alpha",
            "normal": "Normal",
            "emission": "Emission Color",
        }

        result = {
            "channels": {},
            "bake_channels": [],
            "direct_channels": [],
            "summary": "simple",
        }

        if not bsdf:
            result["summary"] = "no_principled"
            self.cache[cache_key] = result
            return result

        for role, socket_name in roles.items():
            sock = bsdf.inputs.get(socket_name)
            info = self.socket_intent(sock, role)
            result["channels"][role] = info

            if info.get("needs_bake"):
                result["bake_channels"].append(role)
            elif info.get("direct_image"):
                result["direct_channels"].append(role)

        if result["bake_channels"]:
            result["summary"] = "partial_bake" if result["direct_channels"] else "full_bake_candidate"
        elif result["direct_channels"]:
            result["summary"] = "direct_transfer"

        self.cache[cache_key] = result
        return result

    def collect_images_from_socket(self, socket: bpy.types.NodeSocket, depth: int = 0,
                                  visited: Optional[Set] = None, items: Optional[List] = None,
                                  path_score: int = 0) -> List[Tuple[int, bpy.types.Image, bpy.types.Node]]:
        """
        Собирает изображения, подключенные к сокету.

        Args:
            socket: Сокет для анализа
            depth: Текущая глубина рекурсии
            visited: Множество посещенных узлов
            items: Список найденных изображений
            path_score: Текущая оценка пути

        Returns:
            Список (оценка, изображение, узел)
        """
        if visited is None:
            visited = set()
        if items is None:
            items = []

        if depth > 32 or not socket or not getattr(socket, "is_linked", False):
            return items

        try:
            node = socket.links[0].from_node
        except Exception:
            return items

        if not node or id(node) in visited:
            return items

        visited.add(id(node))

        if node.type == "TEX_IMAGE" and getattr(node, "image", None):
            items.append((path_score, node.image, node))
            return items

        # Резервный вариант для групп
        if node.type == "GROUP" and getattr(node, "node_tree", None):
            for gn in node.node_tree.nodes:
                if gn.type == "TEX_IMAGE" and getattr(gn, "image", None):
                    items.append((path_score + 10, gn.image, gn))

        # Приоритет color/image inputs над factor/masks при поиске BaseColor
        for inp in getattr(node, "inputs", []):
            n = inp.name.lower()
            extra = 20
            if "color" in n or "image" in n or n in {"a", "b"}:
                extra = 0
            elif "fac" in n or "factor" in n:
                extra = 25
            elif "normal" in n:
                extra = 5
            self.collect_images_from_socket(inp, depth + 1, visited, items, path_score + extra)

        return items

    def trace_image(self, socket: bpy.types.NodeSocket, texture_dir: str,
                   role: str = "texture") -> Optional[str]:
        """
        Находит и копирует подходящее изображение для сокета.

        Args:
            socket: Сокет для анализа
            texture_dir: Директория для текстуры
            role: Роль текстуры

        Returns:
            Путь к текстуре или None
        """
        from ..utils import texture_role_score, copy_or_save_image, BakeLogger

        candidates = self.collect_images_from_socket(socket)

        if not candidates:
            return None

        scored = []
        for path_score, image, node in candidates:
            score = path_score + texture_role_score(image, role)
            scored.append((score, image, node))

        scored.sort(key=lambda x: x[0])

        if not scored:
            return None

        best_score, best_image, best_node = scored[0]

        # Если ищем basecolor и лучший вариант все еще плохой, отвергаем его
        if role.lower() == "basecolor" and texture_role_score(best_image, "basecolor") > 100:
            BakeLogger.log("BASECOLOR TEXTURE REJECTED:", getattr(best_image, "name", ""), "score", best_score)
            return None

        return copy_or_save_image(best_image, texture_dir, role)

    def classify_material(self, mat: bpy.types.Material, bsdf: bpy.types.ShaderNodeBsdfPrincipled):  # Упростили аннотации типов
        """
        Классифицирует материал по типу.

        Args:
            mat: Материал
            bsdf: Principled BSDF узел

        Returns:
            Словарь с классификацией
        """
        low = mat.name.lower()
        transmission = float(socket_value(bsdf, "Transmission Weight", 0.0) or 0.0) if bsdf else 0.0
        metallic = float(socket_value(bsdf, "Metallic", 0.0) or 0.0) if bsdf else 0.0
        alpha = float(socket_value(bsdf, "Alpha", 1.0) or 1.0) if bsdf else 1.0

        return {
            "glass": transmission > 0.7 or any(x in low for x in ["glass", "window", "lens"]),
            "metal": metallic > 0.5 or any(x in low for x in ["metal", "metall", "chrome", "steel", "aluminium", "aluminum", "silver"]),
            "foliage": any(x in low for x in ["leaf", "leaves", "foliage", "grass", "plant", "tree", "needle", "pine", "branch"]),
            "alpha": alpha < 0.999 or any(x in low for x in ["leaf", "leaves", "opacity", "alpha", "grill", "mesh", "grid", "holes", "perforated", "fabric"]) or self.material_has_alpha(mat),
        }

    def material_is_complex(self, mat: bpy.types.Material) -> bool:
        """
        Проверяет, является ли материал сложным.

        Args:
            mat: Материал для проверки

        Returns:
            True если материал сложный
        """
        if not mat or not mat.use_nodes:
            return False

        image_count = 0
        for n in mat.node_tree.nodes:
            if n.type == "TEX_IMAGE":
                image_count += 1
            if n.type in config.COMPLEX_NODES:
                return True

        return image_count == 0

    def material_has_alpha(self, mat: bpy.types.Material) -> bool:
        """
        Проверяет, имеет ли материал альфа-канал.

        Args:
            mat: Материал для проверки

        Returns:
            True если материал имеет альфа
        """
        bsdf = get_principled(mat)
        if not bsdf:
            return False

        low = mat.name.lower()
        if any(x in low for x in ["alpha", "opacity", "transparent", "grill", "mesh", "grid", "holes", "perforated", "fabric"]):
            return True

        try:
            alpha_socket = bsdf.inputs.get("Alpha")
            if alpha_socket:
                if alpha_socket.is_linked:
                    return True
                if float(alpha_socket.default_value) < 0.999:
                    return True
        except Exception:
            pass

        return False

    def material_has_bump_or_normal(self, mat: bpy.types.Material) -> bool:
        """
        Проверяет, имеет ли материал bump или normal карту.

        Args:
            mat: Материал для проверки

        Returns:
            True если материал имеет bump/normal
        """
        bsdf = get_principled(mat)
        if not bsdf:
            return False

        try:
            sock = bsdf.inputs.get("Normal")
            if not sock or not sock.is_linked:
                return False

            node = sock.links[0].from_node
            if not node:
                return False

            if node.type in {"BUMP", "NORMAL_MAP"}:
                return True

            return True
        except Exception:
            return False

    def clear_cache(self):
        """Очищает кэш анализатора"""
        self.cache.clear()


# Глобальный экземпляр анализатора
analyzer = MaterialAnalyzer()
