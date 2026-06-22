# pylint: disable=import-error, missing-module-docstring, missing-function-docstring, line-too-long, too-many-branches, too-many-locals, too-many-statements
import os
import json
import math
from pathlib import Path

import bpy
import mathutils

# --- Configuration ---
# Tolerances
TOLERANCE_FLOAT = 1e-5  # General float comparison (location, scale)
TOLERANCE_RAD = math.radians(0.1)  # Angle comparison
TOLERANCE_PROP = 1e-4  # Property comparison (like metallic, scale, fstop) - not strictly needed here

# Expected object data
EXPECTED_OBJECTS = {
    'WoodCube': {
        'type': 'MESH',  # Cube
        'location': mathutils.Vector((1.0, 2.0, 1.0)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),
        'scale': mathutils.Vector((4.0, 6.0, 2.0)),  # Non-uniform
        'parent': None,
        'material': {'slot': 0, 'name': 'AgedWoodMat'},  # Check material assignment
    }
}

# Expected material data
EXPECTED_MATERIALS = {
    'AgedWoodMat': {
        'use_nodes': True,
        # Material settings (should be default Opaque)
        'blend_method': 'OPAQUE',
        'node_checks': {
            # --- Node Presence (minimum) ---
            'principled_bsdf_exists': True,
            'image_texture_min_count': 3,  # BaseColor, Roughness, Normal
            'normal_map_node_exists': True,

            # --- Key Node Settings & Links (Standard PBR) ---
            'pbsdf_basecolor_link': {'from_type': 'TEX_IMAGE'},
            'pbsdf_roughness_link': {'from_type': 'TEX_IMAGE', 'source_colorspace': 'Non-Color'},
            'pbsdf_normal_link': {'from_type': 'NORMAL_MAP'},
            'normalmap_color_link': {'from_type': 'TEX_IMAGE', 'source_colorspace': 'Non-Color'},
            # Removed Emission and Alpha checks from previous script
        }
    }
}

# Map short node type names used in config to Blender's internal bl_idname
NODE_TYPE_TO_BL_IDNAME = {
    'TEX_IMAGE': 'ShaderNodeTexImage',
    'NORMAL_MAP': 'ShaderNodeNormalMap',
    'BSDF_PRINCIPLED': 'ShaderNodeBsdfPrincipled',
    'MIX': 'ShaderNodeMixRGB',
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
    if e1 is None or e2 is None:
        return False
    if check_order and hasattr(e2, 'order') and e1.order != e2.order:
        return False
    return (math.isclose(e1.x, e2.x, abs_tol=tolerance_rad) and
            math.isclose(e1.y, e2.y, abs_tol=tolerance_rad) and
            math.isclose(e1.z, e2.z, abs_tol=tolerance_rad))


def find_node_by_type(nodes, node_type_bl_idname):
    """Finds the first node of a specific type (by bl_idname) in a node collection."""
    if not node_type_bl_idname:
        return None  # Handle missing key in mapping
    for node in nodes:
        if node.bl_idname == node_type_bl_idname:
            return node
    return None


def get_linked_node(input_socket):
    """Gets the node linked to an input socket, if any, handling reroutes."""
    if not input_socket or not input_socket.is_linked:
        return None
    link = input_socket.links[0]
    from_socket = link.from_socket
    while from_socket and from_socket.node.bl_idname == 'NodeReroute':
        if not from_socket.node.inputs or not from_socket.node.inputs[0].is_linked:
            return None
        link = from_socket.node.inputs[0].links[0]
        from_socket = link.from_socket
    return from_socket.node if from_socket else None


def check_node_link_source(input_socket, expected_link_info, context_msg):
    """Checks the source node type and optionally color space of a link."""
    errors = []
    input_name = input_socket.name if input_socket else expected_link_info.get('input_name', 'Unknown')

    if not input_socket:
        errors.append(f"{context_msg}: Input socket '{input_name}' not found.")
        return errors, None

    from_node = get_linked_node(input_socket)

    if not from_node:
        if expected_link_info is not None:  # Check if we expected a link
            errors.append(f"{context_msg}: Input '{input_name}' is not linked or link path broken.")
        return errors, None

    # Check type if expected type is provided
    if 'from_type' in expected_link_info:
        expected_from_type_short = expected_link_info['from_type']
        expected_from_type_bl_idname = NODE_TYPE_TO_BL_IDNAME.get(expected_from_type_short)

        if not expected_from_type_bl_idname:
            errors.append(
                f"{context_msg}: Unknown expected node type '{expected_from_type_short}' in config for '{input_name}'.")
        elif from_node.bl_idname != expected_from_type_bl_idname:
            errors.append(
                f"{context_msg}: Input '{input_name}' expected link from '{expected_from_type_short}' ('{expected_from_type_bl_idname}'), found link from type '{from_node.bl_idname}'.")
            return errors, None  # Type mismatch, stop checking this link path

    # Check source node's color space if required
    if 'source_colorspace' in expected_link_info:
        if from_node.bl_idname == NODE_TYPE_TO_BL_IDNAME.get('TEX_IMAGE'):  # Check only if it's an Image Texture
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
                f"{context_msg}: Color space check requested for non-Image Texture node type '{from_node.bl_idname}' when checking link for '{input_name}'.")

    return errors, from_node


def check_material_settings_and_nodes(mat_name, expected_mat_config):
    """Checks the material settings (blend/shadow) and node tree."""
    errors = []
    mat = bpy.data.materials.get(mat_name)
    prefix = f"Material '{mat_name}':"

    if not mat:
        errors.append(f"{prefix} Material not found.")
        return errors

    # --- Check Material Settings ---
    if 'blend_method' in expected_mat_config and mat.blend_method != expected_mat_config['blend_method']:
        errors.append(
            f"{prefix} Expected Blend Mode '{expected_mat_config['blend_method']}', found '{mat.blend_method}'.")

    if 'shadow_method' in expected_mat_config:
        # Allow single value or list for shadow method
        allowed_methods = expected_mat_config['shadow_method']
        if isinstance(allowed_methods, list):
            if mat.shadow_method not in allowed_methods:
                errors.append(
                    f"{prefix} Expected Shadow Mode to be one of {allowed_methods}, found '{mat.shadow_method}'.")
        elif mat.shadow_method != allowed_methods:  # Single value check
            errors.append(f"{prefix} Expected Shadow Mode '{allowed_methods}', found '{mat.shadow_method}'.")

    # --- Check Node Tree ---
    if 'use_nodes' in expected_mat_config and not mat.use_nodes:
        errors.append(f"{prefix} Does not use nodes, but expected to.")
        return errors
    if not mat.node_tree or not mat.node_tree.nodes:
        errors.append(f"{prefix} Has no node tree or nodes.")
        return errors

    nodes = mat.node_tree.nodes
    expected_node_checks = expected_mat_config.get('node_checks', {})

    # Node Presence Checks
    pbsdf_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME.get('BSDF_PRINCIPLED'))
    normal_map_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME.get('NORMAL_MAP'))
    img_tex_nodes = [n for n in nodes if n.bl_idname == NODE_TYPE_TO_BL_IDNAME.get('TEX_IMAGE')]

    if expected_node_checks.get('principled_bsdf_exists') and not pbsdf_node:
        errors.append(f"{prefix} Principled BSDF node not found.")
        return errors  # Cannot perform further checks without PBSDF
    if expected_node_checks.get('normal_map_node_exists') and not normal_map_node:
        errors.append(f"{prefix} Normal Map node not found.")
        # Allow continuing checks not dependent on Normal Map node

    min_img_tex_count = expected_node_checks.get('image_texture_min_count', 0)
    if len(img_tex_nodes) < min_img_tex_count:
        errors.append(
            f"{prefix} Expected at least {min_img_tex_count} Image Texture nodes, found {len(img_tex_nodes)}.")

    # Specific Node Settings & Links
    if pbsdf_node:
        link_errors = []
        # Check Base Color Link
        if 'pbsdf_basecolor_link' in expected_node_checks:
            link_errs, _ = check_node_link_source(pbsdf_node.inputs.get('Base Color'),
                                                  expected_node_checks['pbsdf_basecolor_link'], f"{prefix} PBSDF")
            link_errors.extend(link_errs)
        # Check Roughness Link
        if 'pbsdf_roughness_link' in expected_node_checks:
            link_errs, _ = check_node_link_source(pbsdf_node.inputs.get('Roughness'),
                                                  expected_node_checks['pbsdf_roughness_link'], f"{prefix} PBSDF")
            link_errors.extend(link_errs)
        # Check Normal Link
        if 'pbsdf_normal_link' in expected_node_checks:
            link_errs, normal_map_node_from_link = check_node_link_source(pbsdf_node.inputs.get('Normal'),
                                                                          expected_node_checks['pbsdf_normal_link'],
                                                                          f"{prefix} PBSDF")
            link_errors.extend(link_errs)
            # Additionally check the input of the Normal Map node itself
            if normal_map_node_from_link and 'normalmap_color_link' in expected_node_checks:
                # Ensure we found the correct normal map node type before checking its input
                if normal_map_node_from_link.bl_idname == NODE_TYPE_TO_BL_IDNAME.get('NORMAL_MAP'):
                    nm_link_errs, _ = check_node_link_source(normal_map_node_from_link.inputs.get('Color'),
                                                             expected_node_checks['normalmap_color_link'],
                                                             f"{prefix} Normal Map Node")
                    link_errors.extend(nm_link_errs)
                # else: Error already generated by check_node_link_source

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

    # --- General Checks (Type, Location, Scale, Rotation, Parent) ---
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
            errors.append(f"Object '{obj_name}': Does not have material slot {slot_index}.")
        elif not obj.material_slots[slot_index].material:
            errors.append(f"Object '{obj_name}': Material slot {slot_index} is empty.")
        elif obj.material_slots[slot_index].material.name != expected_mat_name:
            errors.append(
                f"Object '{obj_name}': Material slot {slot_index} expected material '{expected_mat_name}', found '{obj.material_slots[slot_index].material.name}'.")

    return errors


# --- Main Execution ---
def run_checks():
    print(f"--- Starting Scene Validation ({bpy.data.filepath}) ---")
    all_errors = []

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
        errors = check_material_settings_and_nodes(mat_name, props)
        if errors:
            all_errors.extend(errors)
        else:
            print(f" -> '{mat_name}' checks passed.")

    print("\n--- Validation Summary ---")
    if not all_errors:
        print("Validation Successful! All checks passed.")
        # import sys; sys.exit(0)
        result = {
            "pass": True,
            "reason": ""
        }
    else:
        print("Validation Failed. Errors found:")
        for error in all_errors:
            print(f"- {error}")
        # import sys; sys.exit(1)
        result = {
            "pass": False,
            "reason": "; ".join(all_errors)
        }

    # Save results to JSON file
    parent_dir = str(Path(__file__).parent.parent)
    result_dir = f"{parent_dir}/evaluated_results"
    os.makedirs(result_dir, exist_ok=True)
    result_file = os.path.join(result_dir, "tid_8_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


if __name__ == "__main__":
    run_checks()
