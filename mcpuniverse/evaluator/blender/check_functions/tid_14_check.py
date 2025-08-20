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
TOLERANCE_RAD = math.radians(0.1)  # Angle comparison (for sun elev/rot)
TOLERANCE_PROP = 1e-4  # Property comparison (like strength, density, fstop)

# Expected world settings using Nishita Sky
EXPECTED_WORLD = {
    'use_nodes': True,
    'node_checks': {
        'background_exists': True,
        'sky_texture_exists': True,  # Specifically Sky Texture now
        'background_color_link': {'from_type': 'TEX_SKY', 'from_socket_name': 'Color'},
        # Strength wasn't specified to change, check default 1.0
        'background_strength': 1.0,
        'sky_texture_config': {  # Checks for the Sky Texture node itself
            'sky_type': 'NISHITA',
            'sun_elevation_deg': 16.4,  # Expected value in Degrees
            'sun_rotation_deg': 121.0,  # Expected value in Degrees
            'air_density': 1.9,
        }
    }
}

# Expected object data
EXPECTED_OBJECTS = {
    'Camera': {  # Assuming default Camera name
        'type': 'CAMERA',
        'parent': None,
        # Location/Rotation not specified, so not checked
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),  # Check if scale is default
        'camera_data_checks': {  # Camera specific data checks
            'dof_enabled': True,
            'dof_focus_target': 'Pillar',  # Name of the target object
            'dof_fstop': 1.2,
        }
    },
    'Pillar': {  # The DOF target object
        # Type not specified, just check for existence
        'exists': True,
        # Can add type check if needed, e.g., 'type': 'MESH'
    }
}

# Expected material data (Empty for this task)
EXPECTED_MATERIALS = {}

# Map short node type names used in config to Blender's internal bl_idname
NODE_TYPE_TO_BL_IDNAME = {
    'TEX_IMAGE': 'ShaderNodeTexImage',
    'NORMAL_MAP': 'ShaderNodeNormalMap',
    'BSDF_PRINCIPLED': 'ShaderNodeBsdfPrincipled',
    'MIX': 'ShaderNodeMixRGB',
    'MIX_SHADER': 'ShaderNodeMixShader',
    'TEX_NOISE': 'ShaderNodeTexNoise',
    'DISPLACEMENT': 'ShaderNodeDisplacement',
    'OUTPUT_MATERIAL': 'ShaderNodeOutputMaterial',
    'BACKGROUND': 'ShaderNodeBackground',
    'TEX_ENVIRONMENT': 'ShaderNodeTexEnvironment',
    'TEX_SKY': 'ShaderNodeTexSky',  # Added Sky Texture
    'TEX_COORD': 'ShaderNodeTexCoord',
    'MAPPING': 'ShaderNodeMapping',
}


# --- Helper Functions ---
# (Include vector_compare, euler_compare, find_node_by_type, get_linked_node_and_socket, check_node_link_source)
# Assume these helpers are defined correctly as in previous examples.
def vector_compare(v1, v2, tolerance):
    if v1 is None or v2 is None:
        return False
    if isinstance(v1, mathutils.Vector) and len(v1) == 3 and isinstance(v2, mathutils.Vector) and len(v2) == 3:
        return (v1 - v2).length < tolerance
    elif hasattr(v1, '__len__') and hasattr(v2, '__len__') and len(v1) == len(v2):
        return all(math.isclose(v1[i], v2[i], abs_tol=tolerance) for i in range(len(v1)))
    elif not hasattr(v1, '__len__') and not hasattr(v2, '__len__'):
        return math.isclose(v1, v2, abs_tol=tolerance)
    else:
        return False


def euler_compare(e1, e2, tolerance_rad, check_order=False):
    if e1 is None or e2 is None:
        return False
    if check_order and hasattr(e2, 'order') and e1.order != e2.order:
        return False
    return (math.isclose(e1.x, e2.x, abs_tol=tolerance_rad) and
            math.isclose(e1.y, e2.y, abs_tol=tolerance_rad) and
            math.isclose(e1.z, e2.z, abs_tol=tolerance_rad))


def find_node_by_type(nodes, node_type_bl_idname):
    if not node_type_bl_idname:
        return None
    for node in nodes:
        if node.bl_idname == node_type_bl_idname:
            return node
    return None


def get_linked_node_and_socket(input_socket):
    if not input_socket or not input_socket.is_linked:
        return None, None
    link = input_socket.links[0]
    from_socket = link.from_socket
    while from_socket and from_socket.node.bl_idname == 'NodeReroute':
        if not from_socket.node.inputs or not from_socket.node.inputs[0].is_linked:
            return None, None
        link = from_socket.node.inputs[0].links[0]
        from_socket = link.from_socket
    return (from_socket.node, from_socket) if from_socket else (None, None)


def check_node_link_source(input_socket, expected_link_info, context_msg, check_socket_name=True):
    errors = []
    input_name = input_socket.name if input_socket else expected_link_info.get('input_name', 'Unknown')
    if not input_socket:
        errors.append(f"{context_msg}: Input socket '{input_name}' not found.")
        return errors, None, None
    from_node, from_socket = get_linked_node_and_socket(input_socket)

    if not from_node:
        if expected_link_info is not None:
            errors.append(f"{context_msg}: Input '{input_name}' is not linked or link path broken.")
            return errors, None, None
    if check_socket_name and 'from_socket_name' in expected_link_info and from_socket.name != expected_link_info[
        'from_socket_name']:
        errors.append(
            f"{context_msg}: Input '{input_name}' expected link from socket '{expected_link_info['from_socket_name']}', found '{from_socket.name}'.")
    if 'from_type' in expected_link_info:
        expected_from_type_short = expected_link_info['from_type']
        expected_from_type_bl_idname = NODE_TYPE_TO_BL_IDNAME.get(expected_from_type_short)
        if not expected_from_type_bl_idname:
            errors.append(
                f"{context_msg}: Unknown expected node type '{expected_from_type_short}' in config for '{input_name}'.")
        elif from_node.bl_idname != expected_from_type_bl_idname:
            errors.append(
                f"{context_msg}: Input '{input_name}' expected link from '{expected_from_type_short}', found type '{from_node.bl_idname}'.")
            return errors, None, None
    if 'source_colorspace' in expected_link_info and from_node.bl_idname == NODE_TYPE_TO_BL_IDNAME.get('TEX_IMAGE'):
        if not from_node.image:
            errors.append(f"{context_msg}: Source Image Texture '{from_node.name}' for '{input_name}' has no image.")
        elif not hasattr(from_node.image, 'colorspace_settings'):
            errors.append(f"{context_msg}: Source Image '{from_node.image.name}' lacks colorspace settings.")
        elif from_node.image.colorspace_settings.name != expected_link_info['source_colorspace']:
            errors.append(
                f"{context_msg}: Source Image Texture for '{input_name}' expected Color Space '{expected_link_info['source_colorspace']}', found '{from_node.image.colorspace_settings.name}'.")
    return errors, from_node, from_socket


# --- Check Functions ---

def check_world_settings_and_nodes(expected_world_config):
    """ Checks world settings and the world node setup for Nishita Sky"""
    errors = []
    world = bpy.context.scene.world
    prefix = "World:"

    if not world:
        errors.append(f"{prefix} No World found in scene.")
        return errors

    # Check Use Nodes
    if 'use_nodes' in expected_world_config and world.use_nodes != expected_world_config['use_nodes']:
        errors.append(f"{prefix} Expected use_nodes={expected_world_config['use_nodes']}, found {world.use_nodes}.")
        if not world.use_nodes:
            return errors  # Cannot check nodes if not used
    if not world.node_tree or not world.node_tree.nodes:
        errors.append(f"{prefix} Has no node tree/nodes.")
        return errors

    nodes = world.node_tree.nodes
    node_checks = expected_world_config.get('node_checks', {})

    # Find nodes
    bg_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME.get('BACKGROUND'))
    sky_tex_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME.get('TEX_SKY'))  # Find Sky Texture

    # Check presence
    if node_checks.get('background_exists') and not bg_node:
        errors.append(f"{prefix} Background node not found.")
    if node_checks.get('sky_texture_exists') and not sky_tex_node:
        errors.append(f"{prefix} Sky Texture node not found.")

    # Check Background node state if exists
    if bg_node:
        if 'background_strength' in node_checks:
            strength_input = bg_node.inputs.get('Strength')
            expected_strength = node_checks['background_strength']
            if strength_input and not math.isclose(strength_input.default_value, expected_strength,
                                                   abs_tol=TOLERANCE_PROP):
                errors.append(
                    f"{prefix} Background node: Expected Strength {expected_strength}, found {strength_input.default_value:.3f}.")
            elif not strength_input:
                errors.append(f"{prefix} Background node: 'Strength' input not found.")

        # Check link to Background Color input (should be Sky Texture)
        if 'background_color_link' in node_checks:
            link_errors, _, _ = check_node_link_source(bg_node.inputs.get('Color'),
                                                       node_checks['background_color_link'],
                                                       prefix + " Background Node", check_socket_name=True)
            errors.extend(link_errors)

    # Check Sky Texture node state if exists
    if sky_tex_node and 'sky_texture_config' in node_checks:
        sky_config = node_checks['sky_texture_config']

        if 'sky_type' in sky_config and sky_tex_node.sky_type != sky_config['sky_type']:
            errors.append(
                f"{prefix} Sky Texture: Expected type '{sky_config['sky_type']}', found '{sky_tex_node.sky_type}'.")

        # Check properties only if type is Nishita (as properties differ)
        if sky_tex_node.sky_type == 'NISHITA':
            if 'sun_elevation_deg' in sky_config:
                expected_rad = math.radians(sky_config['sun_elevation_deg'])
                if not math.isclose(sky_tex_node.sun_elevation, expected_rad, abs_tol=TOLERANCE_RAD):
                    found_deg = math.degrees(sky_tex_node.sun_elevation)
                    errors.append(
                        f"{prefix} Sky Texture: Expected Sun Elevation {sky_config['sun_elevation_deg']:.1f} deg, found {found_deg:.1f} deg.")
            if 'sun_rotation_deg' in sky_config:
                expected_rad = math.radians(sky_config['sun_rotation_deg'])
                if not math.isclose(sky_tex_node.sun_rotation, expected_rad, abs_tol=TOLERANCE_RAD):
                    found_deg = math.degrees(sky_tex_node.sun_rotation)
                    errors.append(
                        f"{prefix} Sky Texture: Expected Sun Rotation {sky_config['sun_rotation_deg']:.1f} deg, found {found_deg:.1f} deg.")
            if 'air_density' in sky_config:
                expected_density = sky_config['air_density']
                if not math.isclose(sky_tex_node.air_density, expected_density, abs_tol=TOLERANCE_PROP):
                    errors.append(
                        f"{prefix} Sky Texture: Expected Air Density {expected_density}, found {sky_tex_node.air_density:.3f}.")
        elif 'sky_type' in sky_config and sky_config['sky_type'] == 'NISHITA':
            # Log error if Nishita was expected but not found, preventing checks on wrong props
            errors.append(f"{prefix} Sky Texture: Cannot check Nishita parameters because sky type is not 'NISHITA'.")

    return errors


def check_object_properties(obj_name, expected_props):
    """Checks object properties, including camera DOF settings."""
    errors = []
    obj = bpy.data.objects.get(obj_name)

    if not obj:
        # Handle simple existence check first
        if expected_props.get('exists'):
            errors.append(f"Object '{obj_name}' not found (existence check failed).")
        else:
            errors.append(f"Object '{obj_name}' not found.")
        return errors
    elif expected_props.get('exists'):
        # Object exists, and that's all we needed to check
        print(f" -> '{obj_name}' existence check passed.")
        return errors  # Return empty error list

    # --- General Checks (Type, Parent, Location, Scale, Rotation) ---
    if 'type' in expected_props and expected_props['type'] is not None and obj.type != expected_props['type']:
        errors.append(f"Object '{obj_name}': Expected type '{expected_props['type']}', found '{obj.type}'.")
    if 'parent' in expected_props:
        expected_parent_name = expected_props.get('parent')
        expected_parent_obj = bpy.data.objects.get(expected_parent_name) if expected_parent_name else None
        if obj.parent != expected_parent_obj:
            errors.append(f"Object '{obj_name}': Parent mismatch.")
    if 'location' in expected_props and expected_props['location'] is not None and not vector_compare(obj.location,
                                                                                                      expected_props[
                                                                                                          'location'],
                                                                                                      TOLERANCE_FLOAT):
        errors.append(f"Object '{obj_name}': Location mismatch.")
    if 'scale' in expected_props and expected_props['scale'] is not None and not vector_compare(obj.scale,
                                                                                                expected_props['scale'],
                                                                                                TOLERANCE_FLOAT):
        errors.append(f"Object '{obj_name}': Scale mismatch.")
    if 'rotation_euler' in expected_props and expected_props['rotation_euler'] is not None and not euler_compare(
            obj.rotation_euler, expected_props['rotation_euler'], TOLERANCE_RAD):
        errors.append(f"Object '{obj_name}': Rotation mismatch.")

    # --- Camera Specific Checks ---
    if 'camera_data_checks' in expected_props:
        if obj.type != 'CAMERA':
            errors.append(f"Object '{obj_name}': Expected CAMERA type for camera data checks, found '{obj.type}'.")
        elif not obj.data:
            errors.append(f"Object '{obj_name}': Camera object has no camera data block.")
        else:
            cam_data = obj.data
            cam_checks = expected_props['camera_data_checks']
            prefix_cam = f"Object '{obj_name}' Camera Data:"

            # Check DOF Enabled
            if 'dof_enabled' in cam_checks and cam_data.dof.use_dof != cam_checks['dof_enabled']:
                errors.append(
                    f"{prefix_cam} Expected DOF enabled state '{cam_checks['dof_enabled']}', found '{cam_data.dof.use_dof}'.")

            # Check DOF settings only if DOF is expected to be enabled
            if cam_checks.get('dof_enabled', False):
                # Check DOF Focus Target
                if 'dof_focus_target' in cam_checks:
                    expected_target_name = cam_checks['dof_focus_target']
                    expected_target_obj = bpy.data.objects.get(expected_target_name)
                    found_target_obj = cam_data.dof.focus_object
                    if not expected_target_obj:
                        errors.append(
                            f"{prefix_cam} DOF focus target check failed: Expected target object '{expected_target_name}' not found in scene.")
                    elif found_target_obj != expected_target_obj:
                        found_name = found_target_obj.name if found_target_obj else "None"
                        errors.append(
                            f"{prefix_cam} Expected DOF focus target '{expected_target_name}', found '{found_name}'.")

                # Check DOF F-Stop
                if 'dof_fstop' in cam_checks:
                    expected_fstop = cam_checks['dof_fstop']
                    if not math.isclose(cam_data.dof.aperture_fstop, expected_fstop, abs_tol=TOLERANCE_PROP):
                        errors.append(
                            f"{prefix_cam} Expected DOF F-Stop {expected_fstop}, found {cam_data.dof.aperture_fstop:.2f}.")

    return errors


# --- Main Execution ---
def run_checks():
    print(f"--- Starting Scene Validation ({bpy.data.filepath}) ---")
    all_errors = []

    # Check World Settings & Nodes
    print("\n--- Checking World Settings & Nodes ---")
    world_errors = check_world_settings_and_nodes(EXPECTED_WORLD)
    if world_errors:
        all_errors.extend(world_errors)
    else:
        print(" -> World settings & nodes checks passed.")

    # Check Objects (Camera and Pillar)
    print("\n--- Checking Objects ---")
    for obj_name, props in EXPECTED_OBJECTS.items():
        print(f"Checking Object '{obj_name}'...")
        errors = check_object_properties(obj_name, props)
        if errors:
            all_errors.extend(errors)
        # Don't print "passed" for simple existence check, handled inside function
        elif not props.get('exists'):
            print(f" -> '{obj_name}' checks passed.")

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
    result_file = os.path.join(result_dir, "tid_14_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


if __name__ == "__main__":
    run_checks()
