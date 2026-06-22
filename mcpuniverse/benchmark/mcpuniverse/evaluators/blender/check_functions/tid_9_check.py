# pylint: disable=import-error, missing-module-docstring, missing-function-docstring, line-too-long, too-many-branches, too-many-locals, too-many-statements
import os
import json
import math
from pathlib import Path

import bpy
import mathutils

# --- Configuration ---
# Tolerances
TOLERANCE_FLOAT = 1e-5  # General float comparison
TOLERANCE_RAD = math.radians(0.1)  # Angle comparison
TOLERANCE_PROP = 1e-4  # Property comparison (like roughness, scale, detail)
TOLERANCE_COLOR = 1e-3  # Color comparison tolerance per component

# Expected object data
EXPECTED_OBJECTS = {
    'ConcreteCube': {
        'type': 'MESH',  # Cube
        'location': mathutils.Vector((0.0, 0.0, 0.0)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),
        'scale': mathutils.Vector((15.0, 15.0, 2.0)),  # Non-uniform
        'parent': None,
        'material': {'slot': 0, 'name': 'ConcreteMixMat'},  # Check material assignment
    }
}

# Expected material data
EXPECTED_MATERIALS = {
    'ConcreteMixMat': {
        'use_nodes': True,
        'node_checks': {
            # --- Node Presence (minimum counts/existence) ---
            'principled_bsdf_min_count': 2,
            'image_texture_min_count': 3,  # Concrete BaseColor, Rough, Normal
            'normal_map_node_exists': True,
            'noise_texture_node_exists': True,
            'mix_shader_node_exists': True,
            'material_output_exists': True,

            # --- Structure & Settings Verification (starting from output) ---
            'output_surface_link': {'from_type': 'MIX_SHADER'},

            'mix_shader_fac_link': {'from_type': 'TEX_NOISE', 'from_socket_name': 'Fac'},
            'mix_shader_shader1_link': {'from_type': 'BSDF_PRINCIPLED'},  # Linked to Concrete PBSDF
            'mix_shader_shader2_link': {'from_type': 'BSDF_PRINCIPLED'},  # Linked to Brown PBSDF

            'noise_texture_config': {  # Config for the Noise Texture linked to Mix Shader Fac
                'scale_value': 10.0,
                'detail_value': 5.0,
            },

            'pbsdf1_config': {  # Config for PBSDF linked to Mix Shader Input 1 (Concrete)
                'basecolor_link': {'from_type': 'TEX_IMAGE'},
                'roughness_link': {'from_type': 'TEX_IMAGE', 'source_colorspace': 'Non-Color'},
                'normal_link': {'from_type': 'NORMAL_MAP'},
                # Implicitly checks Normal Map node input later
            },

            'pbsdf2_config': {  # Config for PBSDF linked to Mix Shader Input 2 (Brown)
                'basecolor_default': mathutils.Color((0.1, 0.05, 0.02)),  # Check default value
                'roughness_default': 0.9,  # Check default value
            },

            # Config for Normal Map node linked to PBSDF1 Normal input
            'normalmap_color_link': {'from_type': 'TEX_IMAGE', 'source_colorspace': 'Non-Color'},
        }
    }
}

# Map short node type names used in config to Blender's internal bl_idname
NODE_TYPE_TO_BL_IDNAME = {
    'TEX_IMAGE': 'ShaderNodeTexImage',
    'NORMAL_MAP': 'ShaderNodeNormalMap',
    'BSDF_PRINCIPLED': 'ShaderNodeBsdfPrincipled',
    'MIX': 'ShaderNodeMixRGB',  # Keep for potential use, though Mix Shader used here
    'MIX_SHADER': 'ShaderNodeMixShader',  # Correct type for Mix Shader
    'TEX_NOISE': 'ShaderNodeTexNoise',  # Correct type for Noise Texture
    'DISPLACEMENT': 'ShaderNodeDisplacement',
    'OUTPUT_MATERIAL': 'ShaderNodeOutputMaterial',
}


# --- Helper Functions ---

def vector_compare(v1, v2, tolerance):
    """Compares two vectors component-wise within a given tolerance."""
    if v1 is None or v2 is None:
        return False
    return (v1 - v2).length < tolerance


def euler_compare(e1, e2, tolerance_rad, check_order=False):
    """Compares two Euler angles component-wise within a given radian tolerance."""
    # ... (same as before) ...
    if e1 is None or e2 is None:
        return False
    if check_order and hasattr(e2, 'order') and e1.order != e2.order:
        return False
    return (math.isclose(e1.x, e2.x, abs_tol=tolerance_rad) and
            math.isclose(e1.y, e2.y, abs_tol=tolerance_rad) and
            math.isclose(e1.z, e2.z, abs_tol=tolerance_rad))


def color_compare(c1, c2, tolerance):
    """Compares two Color objects component-wise."""
    if c1 is None or c2 is None:
        return False
    # Compare RGB components, ignore Alpha unless needed
    return (math.isclose(c1.r, c2.r, abs_tol=tolerance) and
            math.isclose(c1.g, c2.g, abs_tol=tolerance) and
            math.isclose(c1.b, c2.b, abs_tol=tolerance))


def find_node_by_type(nodes, node_type_bl_idname):
    """Finds the first node of a specific type (by bl_idname) in a node collection."""
    # ... (same as before) ...
    if not node_type_bl_idname:
        return None
    for node in nodes:
        if node.bl_idname == node_type_bl_idname:
            return node
    return None


def get_linked_node_and_socket(input_socket):
    """Gets the node and the output socket linked to an input socket, handling reroutes."""
    if not input_socket or not input_socket.is_linked:
        return None, None

    link = input_socket.links[0]
    from_socket = link.from_socket
    # Basic reroute handling
    while from_socket and from_socket.node.bl_idname == 'NodeReroute':
        if not from_socket.node.inputs or not from_socket.node.inputs[0].is_linked:
            return None, None
        link = from_socket.node.inputs[0].links[0]
        from_socket = link.from_socket

    return (from_socket.node, from_socket) if from_socket else (None, None)


def check_node_link_source(input_socket, expected_link_info, context_msg, check_socket_name=True):
    """Checks the source node type, optionally socket name, and optionally color space."""
    errors = []
    input_name = input_socket.name if input_socket else expected_link_info.get('input_name', 'Unknown')

    if not input_socket:
        errors.append(f"{context_msg}: Input socket '{input_name}' not found.")
        return errors, None, None  # errors, from_node, from_socket

    from_node, from_socket = get_linked_node_and_socket(input_socket)

    if not from_node:
        if expected_link_info is not None:
            errors.append(f"{context_msg}: Input '{input_name}' is not linked or link path broken.")
        return errors, None, None

    # Check source socket name if required
    if check_socket_name and 'from_socket_name' in expected_link_info:
        if from_socket.name != expected_link_info['from_socket_name']:
            errors.append(
                f"{context_msg}: Input '{input_name}' expected link from socket '{expected_link_info['from_socket_name']}', found '{from_socket.name}'.")
            # Don't necessarily return yet, type check might still be relevant

    # Check source node type if expected type is provided
    if 'from_type' in expected_link_info:
        expected_from_type_short = expected_link_info['from_type']
        expected_from_type_bl_idname = NODE_TYPE_TO_BL_IDNAME.get(expected_from_type_short)

        if not expected_from_type_bl_idname:
            errors.append(
                f"{context_msg}: Unknown expected node type '{expected_from_type_short}' in config for '{input_name}'.")
        elif from_node.bl_idname != expected_from_type_bl_idname:
            errors.append(
                f"{context_msg}: Input '{input_name}' expected link from '{expected_from_type_short}' ('{expected_from_type_bl_idname}'), found link from type '{from_node.bl_idname}'.")
            return errors, None, None  # Type mismatch, stop checking this link path

    # Check source node's color space if required
    if 'source_colorspace' in expected_link_info:
        if from_node.bl_idname == NODE_TYPE_TO_BL_IDNAME.get('TEX_IMAGE'):  # Check only if it's an Image Texture
            # ... (color space check logic - same as before) ...
            if not from_node.image:
                errors.append(
                    f"{context_msg}: Source Image Texture node '{from_node.name}' for '{input_name}' has no image assigned.")
            elif not hasattr(from_node.image, 'colorspace_settings'):
                errors.append(
                    f"{context_msg}: Source Image Texture '{from_node.name}' image lacks colorspace settings.")
            elif from_node.image.colorspace_settings.name != expected_link_info['source_colorspace']:
                errors.append(
                    f"{context_msg}: Source Image Texture for '{input_name}' expected Color Space '{expected_link_info['source_colorspace']}', found '{from_node.image.colorspace_settings.name}'.")
        else:
            errors.append(
                f"{context_msg}: Color space check requested for non-Image Texture node type '{from_node.bl_idname}'.")

    return errors, from_node, from_socket  # Return errors, source node, source socket


def check_material_nodes(mat_name, expected_mat_config):
    """Checks the node tree structure, properties, and material settings."""
    errors = []
    mat = bpy.data.materials.get(mat_name)
    prefix = f"Material '{mat_name}':"

    if not mat:
        errors.append(f"{prefix} Material not found.")
        return errors
    if 'use_nodes' in expected_mat_config and not mat.use_nodes:
        errors.append(f"{prefix} Does not use nodes.")
        return errors
    if not mat.node_tree or not mat.node_tree.nodes:
        errors.append(f"{prefix} Has no node tree/nodes.")
        return errors

    nodes = mat.node_tree.nodes
    node_checks = expected_mat_config.get('node_checks', {})

    # --- Node Presence Checks ---
    pbsdf_nodes = [n for n in nodes if n.bl_idname == NODE_TYPE_TO_BL_IDNAME.get('BSDF_PRINCIPLED')]
    img_tex_nodes = [n for n in nodes if n.bl_idname == NODE_TYPE_TO_BL_IDNAME.get('TEX_IMAGE')]
    normal_map_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME.get('NORMAL_MAP'))
    noise_tex_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME.get('TEX_NOISE'))
    mix_shader_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME.get('MIX_SHADER'))
    output_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME.get('OUTPUT_MATERIAL'))

    # Check counts / existence
    min_pbsdf_count = node_checks.get('principled_bsdf_min_count', 0)
    if len(pbsdf_nodes) < min_pbsdf_count:
        errors.append(f"{prefix} Expected at least {min_pbsdf_count} Principled BSDF nodes, found {len(pbsdf_nodes)}.")
    min_img_tex_count = node_checks.get('image_texture_min_count', 0)
    if len(img_tex_nodes) < min_img_tex_count:
        errors.append(
            f"{prefix} Expected at least {min_img_tex_count} Image Texture nodes, found {len(img_tex_nodes)}.")
    if node_checks.get('normal_map_node_exists') and not normal_map_node:
        errors.append(f"{prefix} Normal Map node not found.")
    if node_checks.get('noise_texture_node_exists') and not noise_tex_node:
        errors.append(f"{prefix} Noise Texture node not found.")
    if node_checks.get('mix_shader_node_exists') and not mix_shader_node:
        errors.append(f"{prefix} Mix Shader node not found.")
    if node_checks.get('material_output_exists') and not output_node:
        errors.append(f"{prefix} Material Output node not found.")

    # If essential nodes are missing, maybe return early
    if not output_node:
        errors.append(f"{prefix} Cannot proceed without Material Output.")
        return errors

    # --- Structure & Settings Checks (Trace back from Output) ---
    link_errors = []

    # 1. Check Material Output Surface link
    surface_input = output_node.inputs.get('Surface')
    link_errs, mix_shader_node_actual, _ = check_node_link_source(surface_input,
                                                                  node_checks.get('output_surface_link', {}),
                                                                  f"{prefix} Material Output")
    link_errors.extend(link_errs)

    # Proceed only if the main Mix Shader node is correctly linked
    if mix_shader_node_actual and mix_shader_node_actual.bl_idname == NODE_TYPE_TO_BL_IDNAME.get('MIX_SHADER'):
        # 2. Check Mix Shader Factor link
        fac_input = mix_shader_node_actual.inputs.get('Fac')
        link_errs, noise_tex_node_actual, _ = check_node_link_source(fac_input,
                                                                     node_checks.get('mix_shader_fac_link', {}),
                                                                     f"{prefix} Mix Shader")
        link_errors.extend(link_errs)

        # 3. Check Noise Texture settings if found
        if noise_tex_node_actual and noise_tex_node_actual.bl_idname == NODE_TYPE_TO_BL_IDNAME.get('TEX_NOISE'):
            noise_config = node_checks.get('noise_texture_config', {})
            scale_in = noise_tex_node_actual.inputs.get('Scale')
            detail_in = noise_tex_node_actual.inputs.get('Detail')
            if scale_in and 'scale_value' in noise_config and not math.isclose(scale_in.default_value,
                                                                               noise_config['scale_value'],
                                                                               abs_tol=TOLERANCE_PROP):
                link_errors.append(
                    f"{prefix} Noise Texture: Expected Scale {noise_config['scale_value']}, found {scale_in.default_value:.3f}.")
            if detail_in and 'detail_value' in noise_config and not math.isclose(detail_in.default_value,
                                                                                 noise_config['detail_value'],
                                                                                 abs_tol=TOLERANCE_PROP):
                link_errors.append(
                    f"{prefix} Noise Texture: Expected Detail {noise_config['detail_value']}, found {detail_in.default_value:.3f}.")

        # 4. Check Mix Shader Input 1 -> PBSDF1 (Concrete)
        shader1_input = mix_shader_node_actual.inputs[1]  # Index 1 is usually first shader input
        link_errs, pbsdf1_node_actual, _ = check_node_link_source(shader1_input,
                                                                  node_checks.get('mix_shader_shader1_link', {}),
                                                                  f"{prefix} Mix Shader Input 1")
        link_errors.extend(link_errs)

        # 5. Check PBSDF1 (Concrete) inputs if found
        if pbsdf1_node_actual and pbsdf1_node_actual.bl_idname == NODE_TYPE_TO_BL_IDNAME.get('BSDF_PRINCIPLED'):
            pbsdf1_config = node_checks.get('pbsdf1_config', {})
            # Check BaseColor link
            link_errs, _, _ = check_node_link_source(pbsdf1_node_actual.inputs.get('Base Color'),
                                                     pbsdf1_config.get('basecolor_link', {}),
                                                     f"{prefix} Concrete PBSDF")
            link_errors.extend(link_errs)
            # Check Roughness link
            link_errs, _, _ = check_node_link_source(pbsdf1_node_actual.inputs.get('Roughness'),
                                                     pbsdf1_config.get('roughness_link', {}),
                                                     f"{prefix} Concrete PBSDF")
            link_errors.extend(link_errs)
            # Check Normal link
            link_errs, normal_map_node_actual, _ = check_node_link_source(pbsdf1_node_actual.inputs.get('Normal'),
                                                                          pbsdf1_config.get('normal_link', {}),
                                                                          f"{prefix} Concrete PBSDF")
            link_errors.extend(link_errs)
            # Check Normal Map node's input if Normal Map node found
            if normal_map_node_actual and normal_map_node_actual.bl_idname == NODE_TYPE_TO_BL_IDNAME.get('NORMAL_MAP'):
                link_errs_nm, _, _ = check_node_link_source(normal_map_node_actual.inputs.get('Color'),
                                                            node_checks.get('normalmap_color_link', {}),
                                                            f"{prefix} Normal Map Node")
                link_errors.extend(link_errs_nm)

        # 6. Check Mix Shader Input 2 -> PBSDF2 (Brown)
        shader2_input = mix_shader_node_actual.inputs[2]  # Index 2 is usually second shader input
        link_errs, pbsdf2_node_actual, _ = check_node_link_source(shader2_input,
                                                                  node_checks.get('mix_shader_shader2_link', {}),
                                                                  f"{prefix} Mix Shader Input 2")
        link_errors.extend(link_errs)

        # 7. Check PBSDF2 (Brown) default values if found
        if pbsdf2_node_actual and pbsdf2_node_actual.bl_idname == NODE_TYPE_TO_BL_IDNAME.get('BSDF_PRINCIPLED'):
            pbsdf2_config = node_checks.get('pbsdf2_config', {})
            bc_in = pbsdf2_node_actual.inputs.get('Base Color')
            rg_in = pbsdf2_node_actual.inputs.get('Roughness')
            # Check Base Color default value
            if bc_in and 'basecolor_default' in pbsdf2_config:
                expected_color = pbsdf2_config['basecolor_default']
                # default_value for color sockets is usually a 4-component list/vector (RGBA)
                actual_color = mathutils.Color(bc_in.default_value[:3])  # Take RGB only
                if not color_compare(actual_color, expected_color, TOLERANCE_COLOR):
                    errors.append(
                        f"{prefix} Brown PBSDF: Expected Base Color default ~{expected_color[:3]}, found ~{actual_color[:3]}.")
            # Check Roughness default value
            if rg_in and 'roughness_default' in pbsdf2_config:
                expected_rough = pbsdf2_config['roughness_default']
                if not math.isclose(rg_in.default_value, expected_rough, abs_tol=TOLERANCE_PROP):
                    errors.append(
                        f"{prefix} Brown PBSDF: Expected Roughness default {expected_rough}, found {rg_in.default_value:.3f}.")

    errors.extend(link_errors)
    return errors


def check_object_properties(obj_name, expected_props):
    """Checks object properties, including material assignment."""
    # Simplified version focusing on transform and material slot
    errors = []
    obj = bpy.data.objects.get(obj_name)
    if not obj:
        errors.append(f"Object '{obj_name}' not found.")
        return errors

    # --- General Checks ---
    if 'type' in expected_props and obj.type != expected_props['type']:
        errors.append(f"Object '{obj_name}': Type mismatch.")
    if 'parent' in expected_props:
        expected_parent_name = expected_props.get('parent')
        expected_parent_obj = bpy.data.objects.get(expected_parent_name) if expected_parent_name else None
        if obj.parent != expected_parent_obj:
            errors.append(f"Object '{obj_name}': Parent mismatch.")
    if 'location' in expected_props and not vector_compare(obj.location, expected_props['location'], TOLERANCE_FLOAT):
        errors.append(f"Object '{obj_name}': Location mismatch.")
    if 'scale' in expected_props and not vector_compare(obj.scale, expected_props['scale'], TOLERANCE_FLOAT):
        errors.append(f"Object '{obj_name}': Scale mismatch.")
    if 'rotation_euler' in expected_props and not euler_compare(obj.rotation_euler, expected_props['rotation_euler'],
                                                                TOLERANCE_RAD):
        errors.append(f"Object '{obj_name}': Rotation mismatch.")

    # --- Material Assignment Check ---
    if 'material' in expected_props:
        expected_mat_info = expected_props['material']
        slot_index = expected_mat_info['slot']
        expected_mat_name = expected_mat_info['name']
        if len(obj.material_slots) <= slot_index:
            errors.append(f"Object '{obj_name}': No material slot {slot_index}.")
        elif not obj.material_slots[slot_index].material:
            errors.append(f"Object '{obj_name}': Slot {slot_index} is empty.")
        elif obj.material_slots[slot_index].material.name != expected_mat_name:
            errors.append(
                f"Object '{obj_name}': Slot {slot_index} expected '{expected_mat_name}', found '{obj.material_slots[slot_index].material.name}'.")

    return errors


def check_scene_settings(expected_settings):
    """ Checks global scene settings like render engine """
    errors = []
    if 'render_engine' in expected_settings:
        if bpy.context.scene.render.engine != expected_settings['render_engine']:
            errors.append(
                f"Scene: Expected render engine '{expected_settings['render_engine']}', found '{bpy.context.scene.render.engine}'.")
    return errors


# --- Main Execution ---
def run_checks():
    print(f"--- Starting Scene Validation ({bpy.data.filepath}) ---")
    all_errors = []

    # Check Scene Settings (Render engine not specified in task, skip for now)
    # print("\n--- Checking Scene Settings ---")
    # scene_errors = check_scene_settings(EXPECTED_SCENE_SETTINGS)
    # if scene_errors: all_errors.extend(scene_errors)
    # else: print(" -> Scene settings checks passed.")

    # Check Objects
    print("\n--- Checking Objects ---")
    for obj_name, props in EXPECTED_OBJECTS.items():
        print(f"Checking Object '{obj_name}'...")
        errors = check_object_properties(obj_name, props)
        if errors:
            all_errors.extend(errors)
        else:
            print(f" -> '{obj_name}' checks passed.")

    # Check Materials (includes node tree and material settings)
    print("\n--- Checking Materials ---")
    for mat_name, props in EXPECTED_MATERIALS.items():
        print(f"Checking Material '{mat_name}'...")
        errors = check_material_nodes(mat_name, props)  # Pass the whole props dict
        if errors:
            all_errors.extend(errors)
        else:
            print(f" -> '{mat_name}' checks passed.")

    print("\n--- Validation Summary ---")
    if not all_errors:
        print("Validation Successful! All checks passed.")
        result = {
            "pass": True,
            "reason": ""
        }
    else:
        print("Validation Failed. Errors found:")
        for error in all_errors:
            print(f"- {error}")
        result = {
            "pass": False,
            "reason": "; ".join(all_errors)
        }

    # Save results to JSON file
    parent_dir = str(Path(__file__).parent.parent)
    result_dir = f"{parent_dir}/evaluated_results"
    os.makedirs(result_dir, exist_ok=True)
    result_file = os.path.join(result_dir, "tid_9_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


if __name__ == "__main__":
    run_checks()
