# pylint: disable=import-error, missing-module-docstring, missing-function-docstring, line-too-long, too-many-branches, too-many-locals, too-many-statements
import os
import json
import math
from pathlib import Path

import bpy
import mathutils

# --- Configuration ---
TOLERANCE_FLOAT = 1e-5  # General float comparison
TOLERANCE_RAD = math.radians(0.1)  # Angle comparison (not used here but good practice)
TOLERANCE_PROP = 1e-4  # Property comparison (like metallic value)

# Map short node type names used in config to Blender's internal bl_idname
NODE_TYPE_TO_BL_IDNAME = {
    'TEX_IMAGE': 'ShaderNodeTexImage',
    'NORMAL_MAP': 'ShaderNodeNormalMap',
    'BSDF_PRINCIPLED': 'ShaderNodeBsdfPrincipled',
    # Add other node types here if needed by future checks
}

# Expected object data
EXPECTED_OBJECTS = {
    'RustedCube': {
        'type': 'MESH',  # Cube
        'location': mathutils.Vector((0.0, 0.0, 0.0)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),
        'scale': mathutils.Vector((5.0, 5.0, 0.2)),
        'parent': None,
        'material': {'slot': 0, 'name': 'RustedMetalMat'},  # Check material assignment
    }
}

# Expected material data
EXPECTED_MATERIALS = {
    'RustedMetalMat': {
        'use_nodes': True,
        'node_checks': {
            # Node Presence (Basic)
            'principled_bsdf_exists': True,
            'image_texture_min_count': 3,  # Need at least BaseColor, Rough, Normal
            'normal_map_node_exists': True,
            # Principled BSDF Settings
            'pbsdf_metallic': 1.0,
            # Link Structure Checks
            'pbsdf_basecolor_link': {'from_type': 'TEX_IMAGE'},
            'pbsdf_roughness_link': {'from_type': 'TEX_IMAGE', 'source_colorspace': 'Non-Color'},
            'pbsdf_normal_link': {'from_type': 'NORMAL_MAP'},
            'normalmap_color_link': {'from_type': 'TEX_IMAGE', 'source_colorspace': 'Non-Color'},
        }
    }
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


def find_node_by_type(nodes, node_type):
    """Finds the first node of a specific type in a node collection."""
    for node in nodes:
        if node.bl_idname == node_type:  # Use bl_idname for reliable type checking
            return node
    return None


def check_node_link(input_socket, expected_link_info, context_msg):
    """Checks if an input socket is linked correctly."""
    errors = []
    if not input_socket:
        errors.append(
            f"{context_msg}: Input socket '{expected_link_info.get('input_name', 'Unknown')}' not found.")  # Improved error msg
        return errors
    if not input_socket.is_linked:
        errors.append(f"{context_msg}: Input '{input_socket.name}' is not linked.")
        return errors

    # Check the node type it's linked from
    link = input_socket.links[0]
    from_node = link.from_node

    # --- FIX START ---
    # Get expected bl_idname from our mapping dictionary
    expected_from_type_short = expected_link_info['from_type']
    expected_from_type_bl_idname = NODE_TYPE_TO_BL_IDNAME.get(expected_from_type_short)

    if not expected_from_type_bl_idname:
        # If the short type name isn't in our dictionary, we can't check
        errors.append(
            f"{context_msg}: Unknown expected node type '{expected_from_type_short}' in configuration. Cannot verify link source type for '{input_socket.name}'.")
        return errors  # Cannot proceed with type check
    # --- FIX END ---

    if from_node.bl_idname != expected_from_type_bl_idname:
        errors.append(
            f"{context_msg}: Input '{input_socket.name}' expected link from '{expected_from_type_short}' ('{expected_from_type_bl_idname}'), found link from type '{from_node.bl_idname}'.")
        # If type mismatch, don't proceed with color space check
        return errors

    # Check source node's color space if required (must be TEX_IMAGE)
    if 'source_colorspace' in expected_link_info:
        if from_node.bl_idname == 'ShaderNodeTexImage':  # Ensure it's an Image Texture node
            if not from_node.image:
                errors.append(
                    f"{context_msg}: Source Image Texture node '{from_node.name}' for '{input_socket.name}' has no image assigned.")
            elif not hasattr(from_node.image, 'colorspace_settings'):
                errors.append(
                    f"{context_msg}: Source Image Texture node '{from_node.name}' for '{input_socket.name}' image lacks colorspace settings.")
            elif from_node.image.colorspace_settings.name != expected_link_info['source_colorspace']:
                errors.append(
                    f"{context_msg}: Source Image Texture for '{input_socket.name}' expected Color Space '{expected_link_info['source_colorspace']}', found '{from_node.image.colorspace_settings.name}'.")
        else:
            # This case should ideally not happen if types were checked correctly
            errors.append(
                f"{context_msg}: Color space check requested for non-Image Texture node type '{from_node.bl_idname}' when checking link for '{input_socket.name}'.")

    return errors


def check_material_nodes(mat_name, expected_node_checks):
    """Checks the node tree structure and properties of a material."""
    errors = []
    mat = bpy.data.materials.get(mat_name)
    prefix = f"Material '{mat_name}':"

    if not mat:
        errors.append(f"{prefix} Material not found.")
        return errors
    if not mat.use_nodes:
        errors.append(f"{prefix} Does not use nodes.")
        return errors
    if not mat.node_tree or not mat.node_tree.nodes:
        errors.append(f"{prefix} Has no node tree or nodes.")
        return errors

    nodes = mat.node_tree.nodes

    # Find key nodes by type (more robust than by name)
    pbsdf_node = find_node_by_type(nodes, 'ShaderNodeBsdfPrincipled')
    normal_map_node = find_node_by_type(nodes, 'ShaderNodeNormalMap')
    img_tex_nodes = [n for n in nodes if n.bl_idname == 'ShaderNodeTexImage']

    # Check Node Presence
    if expected_node_checks.get('principled_bsdf_exists') and not pbsdf_node:
        errors.append(f"{prefix} Principled BSDF node not found.")
        # If PBSDF missing, further checks dependent on it will fail anyway
        return errors  # Return early
    if expected_node_checks.get('normal_map_node_exists') and not normal_map_node:
        errors.append(f"{prefix} Normal Map node not found.")
        # Allow continuing checks not dependent on Normal Map node

    min_img_tex_count = expected_node_checks.get('image_texture_min_count', 0)
    if len(img_tex_nodes) < min_img_tex_count:
        errors.append(
            f"{prefix} Expected at least {min_img_tex_count} Image Texture nodes, found {len(img_tex_nodes)}.")

    # Check PBSDF Properties if node exists
    if pbsdf_node:
        if 'pbsdf_metallic' in expected_node_checks:
            metallic_input = pbsdf_node.inputs.get('Metallic')
            if metallic_input and not math.isclose(metallic_input.default_value, expected_node_checks['pbsdf_metallic'],
                                                   abs_tol=TOLERANCE_PROP):
                errors.append(
                    f"{prefix} Principled BSDF 'Metallic' expected default value {expected_node_checks['pbsdf_metallic']}, found {metallic_input.default_value:.3f}.")

        # Check PBSDF Links
        if 'pbsdf_basecolor_link' in expected_node_checks:
            errors.extend(
                check_node_link(pbsdf_node.inputs.get('Base Color'), expected_node_checks['pbsdf_basecolor_link'],
                                f"{prefix} PBSDF"))
        if 'pbsdf_roughness_link' in expected_node_checks:
            errors.extend(
                check_node_link(pbsdf_node.inputs.get('Roughness'), expected_node_checks['pbsdf_roughness_link'],
                                f"{prefix} PBSDF"))
        if 'pbsdf_normal_link' in expected_node_checks:
            errors.extend(check_node_link(pbsdf_node.inputs.get('Normal'), expected_node_checks['pbsdf_normal_link'],
                                          f"{prefix} PBSDF"))

    # Check Normal Map Node Links if node exists
    if normal_map_node:
        if 'normalmap_color_link' in expected_node_checks:
            errors.extend(
                check_node_link(normal_map_node.inputs.get('Color'), expected_node_checks['normalmap_color_link'],
                                f"{prefix} Normal Map Node"))

    return errors


def check_object_properties(obj_name, expected_props):
    """Checks object properties, including material assignment."""
    errors = []
    obj = bpy.data.objects.get(obj_name)

    if not obj:
        errors.append(f"Object '{obj_name}' not found.")
        return errors

    # --- General Checks (Type, Parent, Location, Scale, Rotation) ---
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
        else:
            mat_slot = obj.material_slots[slot_index]
            if not mat_slot.material:
                errors.append(f"Object '{obj_name}': Material slot {slot_index} is empty.")
            elif mat_slot.material.name != expected_mat_name:
                errors.append(
                    f"Object '{obj_name}': Material slot {slot_index} expected material '{expected_mat_name}', found '{mat_slot.material.name}'.")

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

    # Check Materials
    print("\n--- Checking Materials ---")
    for mat_name, props in EXPECTED_MATERIALS.items():
        print(f"Checking Material '{mat_name}'...")
        errors = check_material_nodes(mat_name, props['node_checks'])
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
    result_file = os.path.join(result_dir, "tid_6_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


if __name__ == "__main__":
    run_checks()
