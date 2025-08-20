# pylint: disable=import-error, missing-module-docstring, missing-function-docstring, line-too-long, too-many-branches, too-many-locals, too-many-statements
import math
import os
import json
from pathlib import Path

import bpy
import mathutils

# --- Configuration ---
# Tolerances
TOLERANCE_FLOAT = 1e-5  # General float comparison
TOLERANCE_RAD = math.radians(0.1)  # Angle comparison
TOLERANCE_PROP = 1e-4  # Property comparison (like strength, AO distance)
TOLERANCE_RES = 5  # Pixel tolerance for resolution check

# Expected scene settings
EXPECTED_SCENE_SETTINGS = {
    'render_engine': 'CYCLES',
    'cycles_device': 'CPU',
    'cycles_samples': 128,
    'cycles_preview_samples': 64,
    'resolution_x': 1920,
    'resolution_y': 1080,
    'resolution_percentage': 121,
    'ao_enabled': True,
    'ao_distance': 0.5,
}

# Expected world settings
EXPECTED_WORLD = {
    'use_nodes': True,
    'node_checks': {
        'background_exists': True,
        'env_texture_exists': True,
        'background_color_link': {
            'from_type': 'TEX_ENVIRONMENT',
            'from_socket_name': 'Color'
        },
        'background_strength': 1.5,
        'env_texture_has_image': True,
        'env_texture_resolution': {
            'width': 1024,
            'height_min': 512,
            'height_max': 1024
        },
        'env_texture_image_format': ['HDR', 'OPEN_EXR'],
    }
}

# No object or material checks for this task
EXPECTED_OBJECTS = {}
EXPECTED_MATERIALS = {}

# Node type mappings (only those needed)
NODE_TYPE_TO_BL_IDNAME = {
    'TEX_ENVIRONMENT': 'ShaderNodeTexEnvironment',
    'BACKGROUND': 'ShaderNodeBackground',
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

def check_scene_settings(expected_settings):
    """ Checks global scene settings """
    errors = []
    scene = bpy.context.scene
    prefix = "Scene Settings:"

    if 'render_engine' in expected_settings and scene.render.engine != expected_settings['render_engine']:
        errors.append(
            f"{prefix} Expected render engine '{expected_settings['render_engine']}', found '{scene.render.engine}'.")
        # If engine isn't Cycles, don't check Cycles specific settings
        if scene.render.engine != 'CYCLES':
            return errors

    # Check Cycles specific settings only if engine is Cycles
    if scene.render.engine == 'CYCLES':
        if 'cycles_device' in expected_settings and scene.cycles.device != expected_settings['cycles_device']:
            errors.append(
                f"{prefix} Expected Cycles device '{expected_settings['cycles_device']}', found '{scene.cycles.device}'.")
        if 'cycles_samples' in expected_settings and scene.cycles.samples != expected_settings['cycles_samples']:
            errors.append(
                f"{prefix} Expected render samples {expected_settings['cycles_samples']}, found {scene.cycles.samples}.")
        if 'cycles_preview_samples' in expected_settings and scene.cycles.preview_samples != expected_settings[
            'cycles_preview_samples']:
            errors.append(
                f"{prefix} Expected viewport samples {expected_settings['cycles_preview_samples']}, found {scene.cycles.preview_samples}.")

    # Check resolution settings (engine independent)
    if 'resolution_x' in expected_settings and scene.render.resolution_x != expected_settings['resolution_x']:
        errors.append(
            f"{prefix} Expected resolution X {expected_settings['resolution_x']}, found {scene.render.resolution_x}.")
    if 'resolution_y' in expected_settings and scene.render.resolution_y != expected_settings['resolution_y']:
        errors.append(
            f"{prefix} Expected resolution Y {expected_settings['resolution_y']}, found {scene.render.resolution_y}.")
    if 'resolution_percentage' in expected_settings and scene.render.resolution_percentage != expected_settings[
        'resolution_percentage']:
        errors.append(
            f"{prefix} Expected resolution % {expected_settings['resolution_percentage']}, found {scene.render.resolution_percentage}.")

    return errors


def check_world_settings_and_nodes(expected_world_config):
    """ Checks world settings (like AO) and the world node setup """
    errors = []
    world = bpy.context.scene.world
    prefix = "World:"

    if not world:
        errors.append(f"{prefix} No World found in scene.")
        return errors

    # --- Check World Settings (like AO) ---
    if 'ao_enabled' in expected_world_config and world.light_settings.use_ambient_occlusion != expected_world_config[
        'ao_enabled']:
        errors.append(
            f"{prefix} Expected Ambient Occlusion enabled state '{expected_world_config['ao_enabled']}', found '{world.light_settings.use_ambient_occlusion}'.")
    # Only check distance if AO is expected to be enabled
    if expected_world_config.get('ao_enabled', False) and 'ao_distance' in expected_world_config:
        if not math.isclose(world.light_settings.distance, expected_world_config['ao_distance'],
                            abs_tol=TOLERANCE_PROP):
            errors.append(
                f"{prefix} Expected AO Distance {expected_world_config['ao_distance']}, found {world.light_settings.distance:.4f}.")

    # --- Check Node Setup ---
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
    env_tex_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME.get('TEX_ENVIRONMENT'))

    # Check presence
    if node_checks.get('background_exists') and not bg_node:
        errors.append(f"{prefix} Background node not found.")
    if node_checks.get('env_texture_exists') and not env_tex_node:
        errors.append(f"{prefix} Environment Texture node not found.")

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

        # Check link to Background Color input
        if 'background_color_link' in node_checks:
            link_errors, _, _ = check_node_link_source(bg_node.inputs.get('Color'),
                                                       node_checks['background_color_link'],
                                                       prefix + " Background Node", check_socket_name=True)
            errors.extend(link_errors)

    # Check Environment Texture state if exists
    if env_tex_node:
        image_loaded = False
        if node_checks.get('env_texture_has_image'):
            if not env_tex_node.image:
                errors.append(f"{prefix} Environment Texture node has no image loaded.")
            else:
                image_loaded = True

        # Only check resolution/format if image is loaded
        if image_loaded:
            image = env_tex_node.image
            if 'env_texture_resolution' in node_checks:
                res_check = node_checks['env_texture_resolution']
                expected_w = res_check['width']
                min_h = res_check['height_min']
                max_h = res_check['height_max']
                # Check width matches and height is within range (e.g., 1024x512 to 1024x1024 for 1K)
                if (not math.isclose(image.size[0], expected_w, abs_tol=TOLERANCE_RES)) or (
                not (min_h - TOLERANCE_RES) <= image.size[1] <= (max_h + TOLERANCE_RES)):
                    errors.append(
                        f"{prefix} Environment Texture resolution expected ~{expected_w}x({min_h}-{max_h}), found {image.size[0]}x{image.size[1]}.")

            if 'env_texture_image_format' in node_checks:
                allowed_formats = node_checks['env_texture_image_format']
                if hasattr(image, 'file_format') and image.file_format not in allowed_formats:
                    errors.append(
                        f"{prefix} Environment Texture image format '{image.file_format}' not in expected {allowed_formats}.")

    return errors


# --- Main Execution ---
def run_checks():
    print(f"--- Starting Scene Validation ({bpy.data.filepath}) ---")
    all_errors = []

    # Check Scene Settings
    print("\n--- Checking Scene Settings ---")
    scene_errors = check_scene_settings(EXPECTED_SCENE_SETTINGS)
    if scene_errors:
        all_errors.extend(scene_errors)
    else:
        print(" -> Scene settings checks passed.")

    # Check World Settings & Nodes
    print("\n--- Checking World Settings & Nodes ---")
    world_errors = check_world_settings_and_nodes(EXPECTED_WORLD)
    if world_errors:
        all_errors.extend(world_errors)
    else:
        print(" -> World settings & nodes checks passed.")

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
    result_file = os.path.join(result_dir, "tid_11_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


if __name__ == "__main__":
    run_checks()
