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
TOLERANCE_PROP = 1e-4  # Property comparison (like strength, scale)

# Expected world settings
EXPECTED_WORLD = {
    'use_nodes': True,
    'node_checks': {
        'background_exists': True,
        'env_texture_exists': True,
        'background_color_link': {'from_type': 'TEX_ENVIRONMENT', 'from_socket_name': 'Color'},
        'background_strength': 2.0,
        'env_texture_has_image': True,  # Check an image is loaded
        'env_texture_image_format': ['HDR', 'OPEN_EXR'],  # Heuristic check for HDRI format
    }
}

# Expected object data
EXPECTED_OBJECTS = {
    'Floorboard': {
        'type': 'MESH',  # Plane
        'location': mathutils.Vector((0.0, 0.0, 0.0)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),
        'parent': None,
        'material': {'slot': 0, 'name': 'WoodenMat'},
        # Optional heuristic: Check if it's a simple plane
        'mesh_verts': 4,
        'mesh_faces': 1,
    }
}

# Expected material data
EXPECTED_MATERIALS = {
    'WoodenMat': {
        'use_nodes': True,
        'node_checks': {
            # --- Node Presence (minimum) ---
            'principled_bsdf_exists': True,
            'image_texture_min_count': 2,  # BaseColor, Roughness
            'mapping_node_exists': True,
            'tex_coord_node_exists': True,

            # --- Key Node Settings & Links ---
            # PBR Links to PBSDF
            'pbsdf_basecolor_link': {'from_type': 'TEX_IMAGE'},
            'pbsdf_roughness_link': {'from_type': 'TEX_IMAGE', 'source_colorspace': 'Non-Color'},

            # UV Mapping Chain
            'mapping_vector_link': {'from_type': 'TEX_COORD', 'from_socket_name': 'UV'},
            'basecolor_tex_vector_link': {'from_type': 'MAPPING'},
            'roughness_tex_vector_link': {'from_type': 'MAPPING'},

            # Mapping Node Settings
            'mapping_node_scale': mathutils.Vector((3.0, 1.0, 1.0)),
        }
    }
}

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
    'BACKGROUND': 'ShaderNodeBackground',  # World node
    'TEX_ENVIRONMENT': 'ShaderNodeTexEnvironment',  # World node
    'TEX_COORD': 'ShaderNodeTexCoord',  # Input node
    'MAPPING': 'ShaderNodeMapping',  # Vector node
}


# --- Helper Functions ---
# Include vector_compare, euler_compare, find_node_by_type, get_linked_node_and_socket, check_node_link_source
def vector_compare(v1, v2, tolerance):
    """Compares two vectors component-wise within a given tolerance."""
    if v1 is None or v2 is None:
        return False
    # Check using vector length difference for 3D vectors for simplicity
    if isinstance(v1, mathutils.Vector) and len(v1) == 3 and isinstance(v2, mathutils.Vector) and len(v2) == 3:
        return (v1 - v2).length < tolerance
    # Fallback to component-wise for other vector types/sizes or basic floats
    elif hasattr(v1, '__len__') and hasattr(v2, '__len__') and len(v1) == len(v2):
        return all(math.isclose(v1[i], v2[i], abs_tol=tolerance) for i in range(len(v1)))
    elif not hasattr(v1, '__len__') and not hasattr(v2, '__len__'):  # Treat as single floats
        return math.isclose(v1, v2, abs_tol=tolerance)
    else:  # Mismatched types/lengths
        return False


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
        return errors, None, None

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

    # Check source node type if expected type is provided
    if 'from_type' in expected_link_info:
        expected_from_type_short = expected_link_info['from_type']
        expected_from_type_bl_idname = NODE_TYPE_TO_BL_IDNAME.get(expected_from_type_short)
        if not expected_from_type_bl_idname:
            errors.append(
                f"{context_msg}: Unknown expected node type '{expected_from_type_short}' in config for '{input_name}'.")
        elif from_node.bl_idname != expected_from_type_bl_idname:
            errors.append(
                f"{context_msg}: Input '{input_name}' expected link from '{expected_from_type_short}', found type '{from_node.bl_idname}'.")
            return errors, None, None  # Type mismatch

    # Check source node's color space if required
    if 'source_colorspace' in expected_link_info:
        if from_node.bl_idname == NODE_TYPE_TO_BL_IDNAME.get('TEX_IMAGE'):
            if not from_node.image:
                errors.append(
                    f"{context_msg}: Source Image Texture '{from_node.name}' for '{input_name}' has no image.")
            elif not hasattr(from_node.image, 'colorspace_settings'):
                errors.append(f"{context_msg}: Source Image '{from_node.image.name}' lacks colorspace settings.")
            elif from_node.image.colorspace_settings.name != expected_link_info['source_colorspace']:
                errors.append(
                    f"{context_msg}: Source Image Texture for '{input_name}' expected Color Space '{expected_link_info['source_colorspace']}', found '{from_node.image.colorspace_settings.name}'.")
        # else: errors.append(f"{context_msg}: Color space check requested for non-Image node.")

    return errors, from_node, from_socket


# --- Check Functions ---

def check_world_nodes(expected_world_config):
    """ Checks the world node setup """
    errors = []
    world = bpy.context.scene.world
    prefix = "World:"

    if not world:
        errors.append(f"{prefix} No World found in scene.")
        return errors
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
        if node_checks.get('env_texture_has_image') and not env_tex_node.image:
            errors.append(f"{prefix} Environment Texture node has no image loaded.")
        elif env_tex_node.image and 'env_texture_image_format' in node_checks:
            allowed_formats = node_checks['env_texture_image_format']
            if hasattr(env_tex_node.image, 'file_format') and env_tex_node.image.file_format not in allowed_formats:
                errors.append(
                    f"{prefix} Environment Texture image format '{env_tex_node.image.file_format}' not in expected {allowed_formats}.")
            # Note: file_format might not always be available depending on how image was loaded

    return errors


def check_material_nodes(mat_name, expected_mat_config):
    """Checks the node tree structure for the material."""
    errors = []
    mat = bpy.data.materials.get(mat_name)
    prefix = f"Material '{mat_name}':"

    if not mat:
        errors.append(f"{prefix} Material not found.")
        return errors
    if 'use_nodes' in expected_mat_config and mat.use_nodes != expected_mat_config['use_nodes']:
        errors.append(f"{prefix} Expected use_nodes={expected_mat_config['use_nodes']}, found {mat.use_nodes}.")
        if not mat.use_nodes:
            return errors
    if not mat.node_tree or not mat.node_tree.nodes:
        errors.append(f"{prefix} Has no node tree/nodes.")
        return errors

    nodes = mat.node_tree.nodes
    node_checks = expected_mat_config.get('node_checks', {})

    # Node Presence Checks
    pbsdf_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME.get('BSDF_PRINCIPLED'))
    mapping_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME.get('MAPPING'))
    tex_coord_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME.get('TEX_COORD'))
    img_tex_nodes = [n for n in nodes if n.bl_idname == NODE_TYPE_TO_BL_IDNAME.get('TEX_IMAGE')]

    if node_checks.get('principled_bsdf_exists') and not pbsdf_node:
        errors.append(f"{prefix} Principled BSDF node not found.")
    if node_checks.get('mapping_node_exists') and not mapping_node:
        errors.append(f"{prefix} Mapping node not found.")
    if node_checks.get('tex_coord_node_exists') and not tex_coord_node:
        errors.append(f"{prefix} Texture Coordinate node not found.")

    min_img_tex_count = node_checks.get('image_texture_min_count', 0)
    if len(img_tex_nodes) < min_img_tex_count:
        errors.append(
            f"{prefix} Expected at least {min_img_tex_count} Image Texture nodes, found {len(img_tex_nodes)}.")

    # If core nodes missing, maybe stop early
    if not pbsdf_node or not mapping_node or not tex_coord_node:
        errors.append(f"{prefix} Cannot proceed with link checks due to missing core nodes (PBSDF, Mapping, TexCoord).")
        return errors

    # --- Specific Node Settings & Links ---
    link_errors = []
    basecolor_tex_node = None
    roughness_tex_node = None

    # Check Mapping Node Scale
    if 'mapping_node_scale' in node_checks:
        scale_input = mapping_node.inputs.get('Scale')
        expected_scale_vec = node_checks['mapping_node_scale']
        # Mapping scale input is a Vector, use vector_compare
        if scale_input and not vector_compare(scale_input.default_value, expected_scale_vec, TOLERANCE_PROP):
            found_scale_rnd = tuple(round(s, 3) for s in scale_input.default_value)
            exp_scale_rnd = tuple(round(s, 3) for s in expected_scale_vec)
            link_errors.append(
                f"{prefix} Mapping node: Expected Scale default {exp_scale_rnd}, found {found_scale_rnd}.")
        elif not scale_input:
            link_errors.append(f"{prefix} Mapping node: 'Scale' input not found.")

    # Check Mapping Node Input Link (from Tex Coord UV)
    if 'mapping_vector_link' in node_checks:
        link_errs, source_node, _ = check_node_link_source(mapping_node.inputs.get('Vector'),
                                                           node_checks['mapping_vector_link'], f"{prefix} Mapping Node",
                                                           check_socket_name=True)
        link_errors.extend(link_errs)
        # Optionally verify the source node is the one we found earlier
        if source_node != tex_coord_node:
            link_errors.append(
                f"{prefix} Mapping Node 'Vector' input not linked from the expected Texture Coordinate node.")

    # Check links TO PBSDF and identify source TEX_IMAGE nodes
    if 'pbsdf_basecolor_link' in node_checks:
        link_errs, node, _ = check_node_link_source(pbsdf_node.inputs.get('Base Color'),
                                                    node_checks['pbsdf_basecolor_link'], f"{prefix} PBSDF")
        link_errors.extend(link_errs)
        if node and node.bl_idname == NODE_TYPE_TO_BL_IDNAME.get('TEX_IMAGE'):
            basecolor_tex_node = node  # Store for later check

    if 'pbsdf_roughness_link' in node_checks:
        link_errs, node, _ = check_node_link_source(pbsdf_node.inputs.get('Roughness'),
                                                    node_checks['pbsdf_roughness_link'], f"{prefix} PBSDF")
        link_errors.extend(link_errs)
        if node and node.bl_idname == NODE_TYPE_TO_BL_IDNAME.get('TEX_IMAGE'):
            roughness_tex_node = node  # Store for later check

    # Check Mapping node output links TO the identified texture nodes
    if basecolor_tex_node and 'basecolor_tex_vector_link' in node_checks:
        link_errs, source_node, _ = check_node_link_source(basecolor_tex_node.inputs.get('Vector'),
                                                           node_checks['basecolor_tex_vector_link'],
                                                           f"{prefix} BaseColor Texture Node")
        link_errors.extend(link_errs)
        if source_node != mapping_node:  # Check it comes from the correct Mapping node
            link_errors.append(
                f"{prefix} BaseColor Texture node 'Vector' input not linked from expected Mapping node ('{mapping_node.name}').")

    if roughness_tex_node and 'roughness_tex_vector_link' in node_checks:
        link_errs, source_node, _ = check_node_link_source(roughness_tex_node.inputs.get('Vector'),
                                                           node_checks['roughness_tex_vector_link'],
                                                           f"{prefix} Roughness Texture Node")
        link_errors.extend(link_errs)
        if source_node != mapping_node:
            link_errors.append(
                f"{prefix} Roughness Texture node 'Vector' input not linked from expected Mapping node ('{mapping_node.name}').")

    errors.extend(link_errors)
    return errors


def check_object_properties(obj_name, expected_props):
    """Checks object properties, including material assignment and mesh heuristic."""
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

    # --- Mesh Heuristic Checks ---
    if obj.type == 'MESH' and obj.data:
        if 'mesh_verts' in expected_props and len(obj.data.vertices) != expected_props['mesh_verts']:
            errors.append(
                f"Object '{obj_name}': Expected mesh vertices {expected_props['mesh_verts']}, found {len(obj.data.vertices)} (Heuristic check).")
        if 'mesh_faces' in expected_props and len(obj.data.polygons) != expected_props['mesh_faces']:
            errors.append(
                f"Object '{obj_name}': Expected mesh faces {expected_props['mesh_faces']}, found {len(obj.data.polygons)} (Heuristic check).")

    return errors


# --- Main Execution ---
def run_checks():
    print(f"--- Starting Scene Validation ({bpy.data.filepath}) ---")
    all_errors = []

    # Check World Settings
    print("\n--- Checking World Settings ---")
    # Need expected world config defined or passed if checking world
    if 'EXPECTED_WORLD' in globals():
        world_errors = check_world_nodes(EXPECTED_WORLD)
        if world_errors:
            all_errors.extend(world_errors)
        else:
            print(" -> World settings checks passed.")
    else:
        print(" -> Skipping World checks (EXPECTED_WORLD not defined).")

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
        # Pass the whole props dict for material settings + node checks
        errors = check_material_nodes(mat_name, props)
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
    result_file = os.path.join(result_dir, "tid_10_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


if __name__ == "__main__":
    run_checks()
