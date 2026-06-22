# pylint: disable=import-error, missing-module-docstring, missing-function-docstring, line-too-long, too-many-branches, too-many-locals, too-many-statements
import os
import json
import math
from pathlib import Path

import bpy

# --- Configuration ---
# Tolerances
TOLERANCE_FLOAT = 1e-5  # For comparing float values like threshold
TOLERANCE_PROP = 1e-4  # General property tolerance

# Expected scene settings
EXPECTED_SCENE_SETTINGS = {
    'render_engine': 'CYCLES',
    'compositor_use_nodes': True,  # Check scene.use_nodes
}

# Expected View Layer settings (checks the active view layer)
EXPECTED_VIEW_LAYER_SETTINGS = {
    'use_pass_denoising_data': True,
    'use_pass_cryptomatte_object': True,
    'cryptomatte_levels': 2,  # Check only if cryptomatte_object is True
}

# Expected Compositor node setup
# Note: Node names can vary, checks rely more on type and connections
EXPECTED_COMPOSITOR_NODES = {
    'node_checks': {
        'render_layers_exists': True,
        'composite_node_exists': True,
        'glare_node_exists': True,
        # --- Link Checks ---
        # Check connection FROM Render Layers 'Image' TO Glare 'Image'
        'link_renderlayers_to_glare': {
            'from_node_type': 'R_LAYERS',  # CompositorNodeRLayers
            'from_socket_name': 'Image',
            'to_node_type': 'GLARE',  # ShaderNodeGlare (used in compositor too)
            'to_socket_name': 'Image'
        },
        # Check connection FROM Glare 'Image' TO Composite 'Image'
        'link_glare_to_composite': {
            'from_node_type': 'GLARE',
            'from_socket_name': 'Image',
            'to_node_type': 'COMPOSITE',  # CompositorNodeComposite
            'to_socket_name': 'Image'
        },
        # --- Glare Node Settings ---
        'glare_node_config': {
            'glare_type': 'FOG_GLOW',
            'threshold': 1.1,
        }
    }
}

# --- No Object, Material, or World checks needed for this task ---
EXPECTED_OBJECTS = {}
EXPECTED_MATERIALS = {}
EXPECTED_WORLD = {}

# Map short node type names used in config to Blender's internal bl_idname
NODE_TYPE_TO_BL_IDNAME = {
    # Compositor Nodes
    'R_LAYERS': 'CompositorNodeRLayers',
    'COMPOSITE': 'CompositorNodeComposite',
    'GLARE': 'CompositorNodeGlare',  # Often uses ShaderNodeGlare type identifier
}


# --- Helper Functions ---

def find_node_by_type(nodes, node_type_bl_idname):
    """Finds the first node of a specific type (by bl_idname) in a node collection."""
    if not node_type_bl_idname:
        return None
    for node in nodes:
        # Handle potential differences in how Glare node is identified
        if node_type_bl_idname == 'CompositorNodeGlare' and node.bl_idname == 'ShaderNodeGlare':
            return node
        if node.bl_idname == node_type_bl_idname:
            return node
    return None


def check_specific_link(nodes, from_type_short, from_sock_name, to_type_short, to_sock_name, context_msg):
    """Checks if a specific link exists between two node types."""
    errors = []
    prefix = context_msg

    from_bl_idname = NODE_TYPE_TO_BL_IDNAME.get(from_type_short)
    to_bl_idname = NODE_TYPE_TO_BL_IDNAME.get(to_type_short)

    if not from_bl_idname or not to_bl_idname:
        errors.append(f"{prefix} Unknown node type(s) in link check: '{from_type_short}' or '{to_type_short}'.")
        return errors, None, None  # Cannot proceed

    from_node = find_node_by_type(nodes, from_bl_idname)
    to_node = find_node_by_type(nodes, to_bl_idname)

    if not from_node:
        errors.append(f"{prefix} Source node type '{from_type_short}' not found.")
    if not to_node:
        errors.append(f"{prefix} Destination node type '{to_type_short}' not found.")
    if not from_node or not to_node:
        return errors, from_node, to_node  # Cannot check link if nodes missing

    from_socket = from_node.outputs.get(from_sock_name)
    to_socket = to_node.inputs.get(to_sock_name)

    if not from_socket:
        errors.append(f"{prefix} Output socket '{from_sock_name}' not found on node '{from_node.name}'.")
    if not to_socket:
        errors.append(f"{prefix} Input socket '{to_sock_name}' not found on node '{to_node.name}'.")
    if not from_socket or not to_socket:
        return errors, from_node, to_node

    # Check if the 'to_socket' is linked and if any link comes from the correct source socket
    link_found = False
    if to_socket.is_linked:
        for link in to_socket.links:
            if link.from_node == from_node and link.from_socket == from_socket:
                link_found = True
                break

    if not link_found:
        errors.append(
            f"{prefix} Expected link FROM '{from_node.name}'.'{from_sock_name}' TO '{to_node.name}'.'{to_sock_name}' not found.")

    return errors, from_node, to_node


# --- Check Functions ---

def check_scene_settings(expected_settings):
    """ Checks Scene settings like render engine and compositor usage """
    errors = []
    scene = bpy.context.scene
    prefix = "Scene Settings:"

    if 'render_engine' in expected_settings and scene.render.engine != expected_settings['render_engine']:
        errors.append(
            f"{prefix} Expected render engine '{expected_settings['render_engine']}', found '{scene.render.engine}'.")

    if 'compositor_use_nodes' in expected_settings and scene.use_nodes != expected_settings['compositor_use_nodes']:
        errors.append(
            f"{prefix} Expected Compositor Use Nodes: {expected_settings['compositor_use_nodes']}, found: {scene.use_nodes}.")

    return errors


def check_view_layer_settings(view_layer, expected_settings):
    """ Checks settings for a specific View Layer """
    errors = []
    if not view_layer:
        errors.append("View Layer Check: No active view layer found.")
        return errors

    prefix = f"View Layer '{view_layer.name}':"

    if 'use_pass_denoising_data' in expected_settings and view_layer.cycles.denoising_store_passes != expected_settings[
        'use_pass_denoising_data']:
        errors.append(
            f"{prefix} Expected Denoising Data pass enabled: {expected_settings['use_pass_denoising_data']}, found: {view_layer.cycles.denoising_store_passes}.")

    if 'use_pass_cryptomatte_object' in expected_settings:
        if view_layer.use_pass_cryptomatte_object != expected_settings['use_pass_cryptomatte_object']:
            errors.append(
                f"{prefix} Expected Cryptomatte Object pass enabled: {expected_settings['use_pass_cryptomatte_object']}, found: {view_layer.use_pass_cryptomatte_object}.")
        # Only check levels if cryptomatte object pass is expected to be True
        elif expected_settings['use_pass_cryptomatte_object'] and 'cryptomatte_levels' in expected_settings:
            if view_layer.pass_cryptomatte_depth != expected_settings['cryptomatte_levels']:
                errors.append(
                    f"{prefix} Expected Cryptomatte Levels: {expected_settings['cryptomatte_levels']}, found: {view_layer.pass_cryptomatte_depth}.")

    return errors


def check_compositor_nodes(node_tree, expected_node_checks):
    """ Checks the Compositor node tree structure and properties. """
    errors = []
    prefix = "Compositor Nodes:"

    if not node_tree or not node_tree.nodes:
        errors.append(f"{prefix} No compositor node tree or nodes found (ensure 'Use Nodes' is enabled).")
        return errors

    nodes = node_tree.nodes

    # --- Node Presence ---
    rl_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME.get('R_LAYERS'))
    comp_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME.get('COMPOSITE'))
    glare_node = find_node_by_type(nodes, NODE_TYPE_TO_BL_IDNAME.get('GLARE'))

    if expected_node_checks.get('render_layers_exists') and not rl_node:
        errors.append(f"{prefix} Render Layers node not found.")
    if expected_node_checks.get('composite_node_exists') and not comp_node:
        errors.append(f"{prefix} Composite node not found.")
    if expected_node_checks.get('glare_node_exists') and not glare_node:
        errors.append(f"{prefix} Glare node not found.")

    # If essential nodes for links are missing, return early
    if not rl_node or not comp_node or not glare_node:
        errors.append(
            f"{prefix} Cannot perform link checks due to missing essential nodes (Render Layers, Composite, or Glare).")
        return errors

    # --- Link Checks ---
    link_errors = []
    if 'link_renderlayers_to_glare' in expected_node_checks:
        link_cfg = expected_node_checks['link_renderlayers_to_glare']
        errs, _, _ = check_specific_link(nodes, link_cfg['from_node_type'], link_cfg['from_socket_name'],
                                         link_cfg['to_node_type'], link_cfg['to_socket_name'], prefix)
        link_errors.extend(errs)

    if 'link_glare_to_composite' in expected_node_checks:
        link_cfg = expected_node_checks['link_glare_to_composite']
        errs, _, _ = check_specific_link(nodes, link_cfg['from_node_type'], link_cfg['from_socket_name'],
                                         link_cfg['to_node_type'], link_cfg['to_socket_name'], prefix)
        link_errors.extend(errs)

    errors.extend(link_errors)  # Add link errors now

    # --- Glare Node Config Check ---
    if glare_node and 'glare_node_config' in expected_node_checks:  # Check if glare node exists before accessing props
        glare_config = expected_node_checks['glare_node_config']
        glare_prefix = f"{prefix} Glare Node:"

        if 'glare_type' in glare_config and glare_node.glare_type != glare_config['glare_type']:
            errors.append(
                f"{glare_prefix} Expected glare_type '{glare_config['glare_type']}', found '{glare_node.glare_type}'.")

        if 'threshold' in glare_config:
            # Threshold is directly on the node in newer Blender, check inputs for older versions if needed
            if hasattr(glare_node, 'threshold'):
                if not math.isclose(glare_node.threshold, glare_config['threshold'], abs_tol=TOLERANCE_FLOAT):
                    errors.append(
                        f"{glare_prefix} Expected threshold {glare_config['threshold']:.3f}, found {glare_node.threshold:.3f}.")
            # Fallback/alternative check via input socket default value if direct property isn't there
            elif glare_node.inputs.get('Threshold'):
                thresh_input = glare_node.inputs['Threshold']
                if not thresh_input.is_linked and not math.isclose(thresh_input.default_value,
                                                                   glare_config['threshold'], abs_tol=TOLERANCE_FLOAT):
                    errors.append(
                        f"{glare_prefix} Expected threshold {glare_config['threshold']:.3f} (input default), found {thresh_input.default_value:.3f}.")
                elif thresh_input.is_linked:
                    errors.append(f"{glare_prefix} Threshold input is linked, cannot check default value.")
            else:
                errors.append(f"{glare_prefix} Could not find 'threshold' property or 'Threshold' input.")

    return errors


# --- Main Execution ---
def run_checks():
    print(f"--- Starting Scene Validation ({bpy.data.filepath}) ---")
    all_errors = []
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer  # Get active view layer
    node_tree = scene.node_tree if scene.use_nodes else None  # Get compositor node tree if enabled

    # Check Scene Settings
    print("\n--- Checking Scene Settings ---")
    scene_errors = check_scene_settings(EXPECTED_SCENE_SETTINGS)
    if scene_errors:
        all_errors.extend(scene_errors)
    else:
        print(" -> Scene settings checks passed.")

    # Check View Layer Settings
    print("\n--- Checking View Layer Settings ---")
    vl_errors = check_view_layer_settings(view_layer, EXPECTED_VIEW_LAYER_SETTINGS)
    if vl_errors:
        all_errors.extend(vl_errors)
    else:
        print(" -> View Layer settings checks passed.")

    # Check Compositor Nodes (only if use_nodes is True/Expected)
    if scene.use_nodes:
        print("\n--- Checking Compositor Nodes ---")
        comp_errors = check_compositor_nodes(node_tree, EXPECTED_COMPOSITOR_NODES['node_checks'])
        if comp_errors:
            all_errors.extend(comp_errors)
        else:
            print(" -> Compositor node checks passed.")
    elif EXPECTED_SCENE_SETTINGS.get('compositor_use_nodes'):
        all_errors.append(
            "Compositor Check: Expected 'Use Nodes' to be enabled in Scene settings, but it was disabled.")
    else:
        print("\n--- Skipping Compositor Checks ('Use Nodes' is disabled) ---")

    print("\n--- Validation Summary ---")
    if not all_errors:
        print("Validation Successful! All relevant checks passed.")
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
    result_file = os.path.join(result_dir, "tid_15_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


if __name__ == "__main__":
    run_checks()
