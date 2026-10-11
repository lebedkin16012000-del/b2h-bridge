"""Compile PBR channels on isolated material/group copies, without UI operators."""
import bpy

CHANNELS = {'basecolor': 'Base Color', 'roughness': 'Roughness',
            'metallic': 'Metallic', 'opacity': 'Alpha', 'emission': 'Emission Color',
            'ior': 'IOR', 'transmission': 'Transmission Weight'}
DEFAULTS = {'basecolor': (0.8, 0.8, 0.8, 1), 'roughness': 0.5,
            'metallic': 0.0, 'opacity': 1.0, 'emission': (0, 0, 0, 1), 'ior':1.45, 'transmission':0.0}
EMPTY_SHADER = dict(DEFAULTS, basecolor=(0, 0, 0, 1), opacity=0.0)

def active_output(tree, kind='OUTPUT_MATERIAL'):
    return next((n for n in tree.nodes if n.type == kind and n.is_active_output), None)

def rgba(value):
    if isinstance(value, (int, float)):
        return (value, value, value, 1.0)
    return tuple(value[:3]) + (1.0,)

def linked(value):
    return isinstance(value, bpy.types.NodeSocket)

class ChannelCompiler:
    def __init__(self, source):
        self.material = source.copy()
        self.groups = []
        # Every group instance receives its own node-tree copy.  Besides
        # preventing edits to the user's material this gives us an unambiguous
        # route from an inner Group Input back to that exact outer instance.
        self.group_owners = {}
        self.cache = {}
        self._isolate(self.material.node_tree, set())
        self.output = active_output(self.material.node_tree)
        if self.output is None:
            self.close()
            raise ValueError(f'{source.name}: no active material output')
        surface = self.output.inputs.get('Surface')
        self.surface = surface.links[0].from_socket if surface.is_linked else None

    def _isolate(self, tree, ancestors):
        if tree is None:
            raise ValueError('Material has no node tree')
        for node in tree.nodes:
            if node.type == 'GROUP' and node.node_tree:
                original = node.node_tree
                if original.as_pointer() in ancestors:
                    raise ValueError('Recursive node group')
                node.node_tree = original.copy()
                self.groups.append(node.node_tree)
                self.group_owners[node.node_tree.as_pointer()] = node
                self._isolate(node.node_tree, ancestors | {original.as_pointer()})

    def value(self, socket):
        if socket.is_linked:
            return socket.links[0].from_socket
        val = socket.default_value
        return tuple(val) if hasattr(val, '__len__') else val

    def connect(self, tree, value, target):
        if linked(value):
            tree.links.new(value, target)
        else:
            target.default_value = rgba(value) if target.type == 'RGBA' else value

    def mix(self, tree, a, b, factor, mode='MIX'):
        if not linked(a) and not linked(b):
            aa, bb = rgba(a), rgba(b)
            if mode == 'MULTIPLY': return tuple(aa[i]*bb[i] for i in range(3)) + (1,)
            if aa == bb: return a
            if not linked(factor):
                f = max(0, min(1, float(factor)))
                return tuple(aa[i]*(1-f)+bb[i]*f for i in range(3))+(1,)
        n = tree.nodes.new('ShaderNodeMixRGB')
        n.blend_type = mode
        self.connect(tree, factor, n.inputs[0])
        self.connect(tree, a, n.inputs[1])
        self.connect(tree, b, n.inputs[2])
        return n.outputs[0]

    def add(self, tree, a, b):
        if not linked(a) and not linked(b):
            aa, bb = rgba(a), rgba(b)
            return tuple(aa[i] + bb[i] for i in range(3)) + (1.0,)
        return self.mix(tree, a, b, 1.0, 'ADD')

    def _input_shader(self, node, index, channel, depth):
        socket = node.inputs[index]
        if not socket.is_linked:
            return EMPTY_SHADER[channel]
        return self._shader(socket.links[0].from_socket, channel, depth + 1)

    def _group_input_shader(self, socket, channel, depth):
        owner = self.group_owners.get(socket.id_data.as_pointer())
        if owner is None:
            raise ValueError(f'Group Input has no owning instance: {socket.node.name}')
        outer = next((item for item in owner.inputs
                      if item.identifier == socket.identifier), None)
        if outer is None:
            raise ValueError(f'Group Input socket is missing on {owner.name}: {socket.name}')
        if not outer.is_linked:
            return EMPTY_SHADER[channel]
        return self._shader(outer.links[0].from_socket, channel, depth + 1)

    def compile(self, channel):
        return self._shader(self.surface, channel, 0)

    def _shader(self, socket, channel, depth):
        if depth > 64: raise ValueError('Shader graph nesting exceeds 64')
        if socket is None: raise ValueError('Unconnected shader branch')
        key = (socket.as_pointer(), channel)
        if key in self.cache: return self.cache[key]
        n, tree = socket.node, socket.id_data
        # Blender permits color/value -> shader links (implicit emission).
        if socket.type != 'SHADER':
            result = socket if channel == 'emission' else (0.0 if channel == 'basecolor' else DEFAULTS[channel])
        elif n.mute:
            internal = next((l for l in n.internal_links if l.to_socket == socket), None)
            if internal is None or not internal.from_socket.is_linked:
                raise ValueError(f'Unsupported muted shader: {n.name}')
            result = self._shader(internal.from_socket.links[0].from_socket, channel, depth+1)
        elif n.type == 'REROUTE':
            result = self._input_shader(n, 0, channel, depth)
        elif n.type == 'GROUP_INPUT':
            result = self._group_input_shader(socket, channel, depth)
        elif n.type == 'BSDF_PRINCIPLED':
            result = self.value(n.inputs[dict(CHANNELS, ior='IOR', transmission='Transmission Weight')[channel]])
            if channel == 'emission':
                strength = self.value(n.inputs['Emission Strength'])
                if not linked(strength) and strength == 0: result = (0,0,0,1)
                else: result = self.mix(tree, result, strength, 1.0, 'MULTIPLY')
        elif n.type == 'EMISSION':
            if channel == 'emission':
                color = self.value(n.inputs['Color'])
                strength = self.value(n.inputs['Strength'])
                result = self.mix(tree, color, strength, 1.0, 'MULTIPLY')
            elif channel == 'basecolor':
                # Avoid adding a diffuse lobe to an emission-only branch.
                result = (0.0, 0.0, 0.0, 1.0)
            else:
                result = DEFAULTS[channel]
        elif n.type in {'BSDF_GLOSSY', 'BSDF_DIFFUSE', 'BSDF_GLASS',
                        'BSDF_REFRACTION', 'BSDF_TRANSLUCENT', 'BSDF_TOON'}:
            # Map Blender's focused BSDFs to the closest portable
            # Standard Surface channels. Their full lobe models differ, but
            # baking the spatial inputs preserves their visible pattern.
            sockets = {item.name: item for item in n.inputs}
            if channel == 'basecolor':
                result = self.value(sockets['Color']) if 'Color' in sockets else DEFAULTS[channel]
            elif channel == 'roughness':
                result = self.value(sockets['Roughness']) if 'Roughness' in sockets else 0.5
            elif channel == 'metallic':
                result = 1.0 if n.type == 'BSDF_GLOSSY' else 0.0
            elif channel == 'transmission':
                result = 1.0 if n.type in {'BSDF_GLASS','BSDF_REFRACTION'} else 0.0
            elif channel == 'ior':
                result = self.value(sockets['IOR']) if 'IOR' in sockets else 1.45
            else:
                result = DEFAULTS[channel]
        elif n.type == 'MIX_SHADER':
            factor = self.value(n.inputs[0])
            if not linked(factor) and factor in (0, 1):
                result = self._input_shader(n, 1+int(factor), channel, depth)
            else:
                a = self._input_shader(n, 1, channel, depth)
                b = self._input_shader(n, 2, channel, depth)
                result = self.mix(tree, a, b, factor)
        elif n.type == 'ADD_SHADER':
            a = self._input_shader(n, 0, channel, depth)
            b = self._input_shader(n, 1, channel, depth)
            # Emission lobes are additive.  Standard Surface has only one set
            # of the remaining PBR inputs, so use an energy-balanced blend.
            result = self.add(tree, a, b) if channel == 'emission' else self.mix(tree, a, b, 0.5)
        elif n.type == 'GROUP':
            output = active_output(n.node_tree, 'GROUP_OUTPUT')
            inner = next((s for s in output.inputs if s.identifier == socket.identifier), None) if output else None
            if inner is None or not inner.is_linked: raise ValueError(f'Unconnected group output: {n.name}')
            result = self._shader(inner.links[0].from_socket, channel, depth+1)
            if linked(result):
                iface = n.node_tree.interface.new_socket(name='_B2H_'+channel, in_out='OUTPUT', socket_type='NodeSocketColor')
                dest = next(s for s in output.inputs if s.identifier == iface.identifier)
                n.node_tree.links.new(result, dest)
                result = next(s for s in n.outputs if s.identifier == iface.identifier)
        elif n.type == 'BSDF_TRANSPARENT':
            result = 0.0 if channel == 'opacity' else DEFAULTS[channel]
        elif n.type in {'VOLUME_ABSORPTION', 'VOLUME_SCATTER'}:
            sockets = {item.name: item for item in n.inputs}
            if channel == 'basecolor' and 'Color' in sockets:
                result = self.value(sockets['Color'])
            elif channel == 'transmission':
                result = 1.0
            elif channel == 'opacity':
                result = 0.0
            else:
                result = DEFAULTS[channel]
        else:
            raise ValueError(f'Unsupported shader {n.type} in {n.name}; export stopped instead of losing material')
        self.cache[key] = result
        return result

    def nodes(self):
        for tree in [self.material.node_tree] + self.groups:
            yield from tree.nodes

    def prune_to_output(self, preserve=()):
        """Remove branches that cannot affect the current material surface.

        Cycles otherwise compiles every old output inside large imported node
        groups, even when the bake surface is a small generated Emission graph.
        This method is intentionally destructive and is used only on a private
        per-channel compiler copy.
        """
        kept = {}

        def keep(node):
            kept.setdefault(node.id_data.as_pointer(), set()).add(node.as_pointer())

        def visit(socket):
            node = socket.node
            keep(node)
            if node.type == 'GROUP':
                output = active_output(node.node_tree, 'GROUP_OUTPUT')
                if output:
                    keep(output)
                    inner = next((item for item in output.inputs
                                  if item.identifier == socket.identifier), None)
                    if inner and inner.is_linked:
                        visit(inner.links[0].from_socket)
                return
            if node.type == 'GROUP_INPUT':
                owner = self.group_owners.get(socket.id_data.as_pointer())
                if owner:
                    keep(owner)
                    outer = next((item for item in owner.inputs
                                  if item.identifier == socket.identifier), None)
                    if outer and outer.is_linked:
                        visit(outer.links[0].from_socket)
                return
            for item in node.inputs:
                if item.is_linked:
                    visit(item.links[0].from_socket)

        keep(self.output)
        surface = self.output.inputs.get('Surface')
        if surface and surface.is_linked:
            visit(surface.links[0].from_socket)
        for node in preserve:
            keep(node)
        for tree in [self.material.node_tree] + self.groups:
            allowed = kept.get(tree.as_pointer(), set())
            for node in list(tree.nodes):
                if node.as_pointer() not in allowed:
                    tree.nodes.remove(node)

    def close(self):
        if self.material:
            bpy.data.materials.remove(self.material)
            self.material = None
        for tree in self.groups:
            bpy.data.node_groups.remove(tree)
        self.groups.clear()
        self.group_owners.clear()
