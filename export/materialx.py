"""Portable MaterialX standard_surface documents for the existing PBR channels."""
import os
from pathlib import Path
from xml.etree import ElementTree as ET

def write_material(path, material, asset_root=None):
    path = Path(path)
    root = ET.Element('materialx', version='1.38')
    name = material['name']
    shader = ET.SubElement(root, 'standard_surface', name=name+'_surface', type='surfaceshader')
    defaults = material['defaults']
    roles = {'basecolor':('base_color','color3'), 'roughness':('specular_roughness','float'),
             'metallic':('metalness','float'), 'opacity':('opacity','color3'),
             'emission':('emission_color','color3'), 'normal':('normal','vector3'),
             'ior':('specular_IOR','float'), 'transmission':('transmission','float')}
    for key, typ, value in [('base_color','color3',defaults['base_color'][:3]),
                            ('specular_roughness','float',defaults['roughness']),
                            ('metalness','float',defaults['metallic']),('specular_IOR','float',defaults['ior']),
                            ('transmission','float',defaults.get('transmission',0)),
                            ('opacity','color3',[defaults['alpha']]*3),
                            ('emission','float',defaults['emission_strength'])]:
        text = ', '.join(map(str,value)) if isinstance(value,list) else str(value)
        ET.SubElement(shader,'input',name=key,type=typ,value=text)
    for role, filename in material['textures'].items():
        input_name, typ = roles[role]
        for old in list(shader):
            if old.get('name') == input_name: shader.remove(old)
        image_name = name+'_'+role
        node = ET.SubElement(root,'image',name=image_name,type=typ,colorspace='srgb_texture' if role=='basecolor' else 'lin_rec709')
        if asset_root is None:
            texture_path = '../'+filename
        else:
            texture_path = os.path.relpath(
                Path(asset_root)/filename, path.parent
            ).replace('\\', '/')
        ET.SubElement(node,'input',name='file',type='filename',value=texture_path)
        source = image_name
        if role=='normal':
            source += '_convert'
            convert = ET.SubElement(root,'normalmap',name=source,type='vector3')
            ET.SubElement(convert,'input',name='in',type='vector3',nodename=image_name)
        ET.SubElement(shader,'input',name=input_name,type=typ,nodename=source)
    mat = ET.SubElement(root,'surfacematerial',name=name,type='material')
    ET.SubElement(mat,'input',name='surfaceshader',type='surfaceshader',nodename=name+'_surface')
    ET.indent(root)
    ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)
