# pylint: disable=import-error, missing-module-docstring, missing-function-docstring, line-too-long, too-many-branches, too-many-locals, too-many-statements
import os
import json
import math
from pathlib import Path

import bpy
import mathutils

# --- Configuration ---
TOLERANCE_FLOAT = 1e-5  # General float comparison
TOLERANCE_RAD = math.radians(0.1)  # Angle comparison
TOLERANCE_PROP = 1e-4  # Property comparison (like metallic, scale, fstop)

# Expected object data
EXPECTED_OBJECTS = {
    'BrickCube': {
        'type': 'MESH',  # Cube
        'location': mathutils.Vector((0.0, 0.0, 0.0)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),
        'scale': mathutils.Vector((5.0, 10.0, 2.0)),  # Non-uniform
        'parent': None,
        'material': {'slot': 0, 'name': 'BrickWallMat'},
    }
}

# Expected material data
EXPECTED_MATERIALS = {
    'BrickWallMat': {
        'use_nodes': True,
        # Cycles specific material setting for displacement
        # 'cycles_displacement_method': ['DISPLACEMENT', 'BOTH'], # Allow either
        'node_checks': {
            # --- Node Presence (minimum) ---
            'principled_bsdf_exists': True,
            'material_output_exists': True,
            'image_texture_min_count': 5,  # BaseColor, Rough, Norm, AO, Disp
            'normal_map_node_exists': True,
            'mix_node_exists': True,  # For AO mix
            'displacement_node_exists': True,

            # --- Key Node Settings & Links ---
            # Roughness Path
            'pbsdf_roughness_link': {'from_type': 'TEX_IMAGE'},
            # Normal Path
            'pbsdf_normal_link': {'from_type': 'NORMAL_MAP'},
            'normalmap_color_link': {'from_type': 'TEX_IMAGE'},
            # Base Color + AO Path
            'pbsdf_basecolor_link': {'from_type': 'MIX'},  # Check it comes from the Mix node
            'mix_node_config': {  # Configuration for the Mix node connected to Base Color
                'blend_type': 'MULTIPLY',
                'factor_value': 1.0,  # Check Factor input default value
                'color1_link': {'from_type': 'TEX_IMAGE'},  # Input A/Color1 from BaseColor Tex
                'color2_link': {'from_type': 'TEX_IMAGE'},  # Input B/Color2 from AO Tex
            },
            # Displacement Path
            'material_output_displacement_link': {'from_type': 'DISPLACEMENT'},
            'displacement_node_config': {  # Config for Displacement node linked to output
                'scale_value': 0.05,
                'height_link': {'from_type': 'TEX_IMAGE'},
            }
        }
    }
}

# Map short node type names used in config to Blender's internal bl_idname
NODE_TYPE_TO_BL_IDNAME = {
    'TEX_IMAGE': 'ShaderNodeTexImage',
    'NORMAL_MAP': 'ShaderNodeNormalMap',
    'BSDF_PRINCIPLED': 'ShaderNodeBsdfPrincipled',
    'MIX': 'ShaderNodeMixRGB',  # Use ShaderNodeMixRGB for wider compatibility, works like Mix in newer Blender
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
    for node in nodes:
        if node.bl_idname == node_type_bl_idname:
            return node
    return None


def get_linked_node(input_socket):
    """Gets the node linked to an input socket, if any."""
    if input_socket and input_socket.is_linked:
        # Follow links until a node socket is found (handles reroutes)
        link = input_socket.links[0]
        from_socket = link.from_socket
        while from_socket and from_socket.node.bl_idname == 'NodeReroute':
            # Assuming single input for reroute
            if not from_socket.node.inputs[0].is_linked:
                return None
            link = from_socket.node.inputs[0].links[0]
            from_socket = link.from_socket

        return from_socket.node if from_socket else None
    return None


def check_node_link_source(input_socket, expected_link_info, context_msg):
    """Checks the source node type and optionally color space of a link."""
    errors = []
    if not input_socket:
        errors.append(f"{context_msg}: Input socket ('{expected_link_info.get('input_name', 'Unknown')}') not found.")
        return errors

    from_node = get_linked_node(input_socket)  # Use helper to handle reroutes etc.

    if not from_node:
        errors.append(f"{context_msg}: Input '{input_socket.name}' is not linked or link path broken.")
        return errors

    # Get expected bl_idname from our mapping dictionary
    expected_from_type_short = expected_link_info['from_type']
    expected_from_type_bl_idname = NODE_TYPE_TO_BL_IDNAME.get(expected_from_type_short)

    if not expected_from_type_bl_idname:
        errors.append(
            f"{context_msg}: Unknown expected node type '{expected_from_type_short}' in config for '{input_socket.name}'.")
        return errors

    if from_node.bl_idname != expected_from_type_bl_idname:
        errors.append(
            f"{context_msg}: Input '{input_socket.name}' expected link from '{expected_from_type_short}' ('{expected_from_type_bl_idname}'), found link from type '{from_node.bl_idname}'.")
        return errors  # Don't check color space if type is wrong

    return errors


def check_material_nodes(mat_name, expected_mat_config):
    """Checks the node tree structure, properties, and material settings."""
    errors = []
    mat = bpy.data.materials.get(mat_name)
    prefix = f"Material '{mat_name}':"

    if not mat:
        errors.append(f"{prefix} Material not found.")
        return errors
    if 'use_nodes' in expected_mat_config and not mat.use_nodes:
        errors.append(f"{prefix} Does not use nodes, but expected to.")
        return errors
    if not mat.node_tree or not mat.node_tree.nodes:
        errors.append(f"{prefix} Has no node tree or nodes.")
        return errors

    nodes = mat.node_tree.nodes
    expected_node_checks = expected_mat_config.get('node_checks', {})

    # --- Node Presence Checks ---
    pbsdf_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME['BSDF_PRINCIPLED'])
    output_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME['OUTPUT_MATERIAL'])
    normal_map_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME['NORMAL_MAP'])
    mix_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME['MIX'])  # Found first mix node
    disp_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME['DISPLACEMENT'])
    img_tex_nodes = [n for n in nodes if n.bl_idname == NODE_TYPE_TO_BL_IDNAME['TEX_IMAGE']]

    if expected_node_checks.get('principled_bsdf_exists') and not pbsdf_node:
        errors.append(f"{prefix} Principled BSDF node not found.")
    if expected_node_checks.get('material_output_exists') and not output_node:
        errors.append(f"{prefix} Material Output node not found.")
    if expected_node_checks.get('normal_map_node_exists') and not normal_map_node:
        errors.append(f"{prefix} Normal Map node not found.")
    if expected_node_checks.get('mix_node_exists') and not mix_node:
        errors.append(f"{prefix} Mix node not found.")  # Might need more specific check later
    if expected_node_checks.get('displacement_node_exists') and not disp_node:
        errors.append(f"{prefix} Displacement node not found.")  # Might need more specific check later

    min_img_tex_count = expected_node_checks.get('image_texture_min_count', 0)
    if len(img_tex_nodes) < min_img_tex_count:
        errors.append(
            f"{prefix} Expected at least {min_img_tex_count} Image Texture nodes, found {len(img_tex_nodes)}.")

    # --- Specific Node and Link Checks ---
    # Need the key nodes to exist to proceed with link checks
    if not pbsdf_node or not output_node:
        errors.append(f"{prefix} Cannot perform link checks due to missing core nodes (PBSDF or Output).")
        return errors

    # Check Roughness Path
    if 'pbsdf_roughness_link' in expected_node_checks:
        errors.extend(
            check_node_link_source(pbsdf_node.inputs.get('Roughness'), expected_node_checks['pbsdf_roughness_link'],
                                   f"{prefix} PBSDF"))

    # Check Normal Path
    if 'pbsdf_normal_link' in expected_node_checks:
        errors.extend(check_node_link_source(pbsdf_node.inputs.get('Normal'), expected_node_checks['pbsdf_normal_link'],
                                             f"{prefix} PBSDF"))
        # Additionally check the source of the Normal Map node itself
        if normal_map_node and 'normalmap_color_link' in expected_node_checks:
            errors.extend(check_node_link_source(normal_map_node.inputs.get('Color'),
                                                 expected_node_checks['normalmap_color_link'],
                                                 f"{prefix} Normal Map Node"))

    # Check Base Color + AO Path (more complex)
    if 'pbsdf_basecolor_link' in expected_node_checks:
        base_color_input = pbsdf_node.inputs.get('Base Color')
        # 1. Check if Base Color is linked from the expected type (Mix)
        errors.extend(
            check_node_link_source(base_color_input, expected_node_checks['pbsdf_basecolor_link'], f"{prefix} PBSDF"))
        # 2. If linked, get the specific Mix node and check its config
        mix_node_driving_basecolor = get_linked_node(base_color_input)
        if mix_node_driving_basecolor and mix_node_driving_basecolor.bl_idname == NODE_TYPE_TO_BL_IDNAME[
            'MIX'] and 'mix_node_config' in expected_node_checks:
            mix_config = expected_node_checks['mix_node_config']
            # Check Mix blend type (using 'blend_type' attribute)
            if 'blend_type' in mix_config and mix_node_driving_basecolor.blend_type != mix_config['blend_type']:
                errors.append(
                    f"{prefix} Mix node driving BaseColor: Expected blend_type '{mix_config['blend_type']}', found '{mix_node_driving_basecolor.blend_type}'.")
            # Check Mix Factor default value
            factor_input = mix_node_driving_basecolor.inputs.get('Factor')
            if factor_input and 'factor_value' in mix_config and not math.isclose(factor_input.default_value,
                                                                                  mix_config['factor_value'],
                                                                                  abs_tol=TOLERANCE_FLOAT):
                errors.append(
                    f"{prefix} Mix node driving BaseColor: Expected Factor default value {mix_config['factor_value']}, found {factor_input.default_value:.3f}.")
            # Check Mix Color1/Color2 links
            # Note: Indices for MixRGB Color1/Color2 inputs are typically 6 and 7, but accessing by name is safer if available
            color1_input = mix_node_driving_basecolor.inputs.get('Color1') or mix_node_driving_basecolor.inputs[
                6]  # Fallback index
            color2_input = mix_node_driving_basecolor.inputs.get('Color2') or mix_node_driving_basecolor.inputs[
                7]  # Fallback index
            if 'color1_link' in mix_config:
                errors.extend(check_node_link_source(color1_input, mix_config['color1_link'],
                                                     f"{prefix} Mix Node (BaseColor Input 1)"))
            if 'color2_link' in mix_config:
                errors.extend(check_node_link_source(color2_input, mix_config['color2_link'],
                                                     f"{prefix} Mix Node (BaseColor Input 2)"))
        elif mix_node_driving_basecolor and mix_node_driving_basecolor.bl_idname != NODE_TYPE_TO_BL_IDNAME['MIX']:
            errors.append(f"{prefix} PBSDF Base Color is linked, but not from a Mix node as expected.")

    # Check Displacement Path
    if 'material_output_displacement_link' in expected_node_checks:
        disp_input_on_output = output_node.inputs.get('Displacement')
        # 1. Check if Material Output's Displacement is linked from the expected type (Displacement Node)
        errors.extend(
            check_node_link_source(disp_input_on_output, expected_node_checks['material_output_displacement_link'],
                                   f"{prefix} Material Output"))
        # 2. If linked, get the specific Displacement node and check its config
        disp_node_driving_output = get_linked_node(disp_input_on_output)
        if disp_node_driving_output and disp_node_driving_output.bl_idname == NODE_TYPE_TO_BL_IDNAME[
            'DISPLACEMENT'] and 'displacement_node_config' in expected_node_checks:
            disp_config = expected_node_checks['displacement_node_config']
            # Check Displacement Scale default value
            scale_input = disp_node_driving_output.inputs.get('Scale')
            if scale_input and 'scale_value' in disp_config and not math.isclose(scale_input.default_value,
                                                                                 disp_config['scale_value'],
                                                                                 abs_tol=TOLERANCE_PROP):
                errors.append(
                    f"{prefix} Displacement node driving output: Expected Scale default value {disp_config['scale_value']}, found {scale_input.default_value:.4f}.")
            # Check Displacement Height link
            height_input = disp_node_driving_output.inputs.get('Height')
            if 'height_link' in disp_config:
                errors.extend(
                    check_node_link_source(height_input, disp_config['height_link'], f"{prefix} Displacement Node"))
        elif disp_node_driving_output and disp_node_driving_output.bl_idname != NODE_TYPE_TO_BL_IDNAME['DISPLACEMENT']:
            errors.append(
                f"{prefix} Material Output Displacement is linked, but not from a Displacement node as expected.")

    return errors


def check_object_properties(obj_name, expected_props):
    """Checks object properties, including material assignment."""
    # Simplified version focusing on material assignment for this check
    errors = []
    obj = bpy.data.objects.get(obj_name)

    if not obj:
        errors.append(f"Object '{obj_name}' not found.")
        return errors

    # --- General Checks (Type, Location, Scale, Rotation) ---
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

    # Check Materials
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
    result_file = os.path.join(result_dir, "tid_7_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


if __name__ == "__main__":
    # Corrected the helper function call to pass the correct dictionary key
    NODE_TYPE_TO_BL_IDNAME['MIX'] = 'ShaderNodeMixRGB'  # Ensure using the compatible ID name
    run_checks()
