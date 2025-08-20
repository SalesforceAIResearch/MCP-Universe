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
TOLERANCE_PROP = 1e-4  # Property comparison (modifier width)

# Expected object data
EXPECTED_OBJECTS = {
    'BaseShape': {
        'type': 'MESH',  # Cube
        'location': mathutils.Vector((0.0, 0.0, 0.0)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),
        'parent': None,
        # --- Modifier Checks ---
        # Checks modifiers in order
        'modifiers': [
            {
                'type': 'SUBSURF',
                'levels': 3,  # Viewport levels
                'render_levels': 3,  # Render levels
            },
            {
                'type': 'BEVEL',
                'width': 0.07,
                'segments': 3,
                'limit_method': 'ANGLE',
            }
        ]
    },
    'Attachment': {
        'type': 'MESH',  # UV Sphere
        # Location is determined by parent vertex, so not checked statically
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),  # Should be default
        'scale': mathutils.Vector((0.3, 0.3, 0.3)),
        'parent': 'BaseShape',  # Name of the parent object
        'parent_type': 'VERTEX',
        # --- Vertex Parent Specific Check ---
        # Check if the parent vertex is the one closest to the target world pos
        'vertex_parent_check': {'target_world_pos': mathutils.Vector((1.0, 1.0, 1.0))}
    }
}

# Expected material data (Empty for this task)
EXPECTED_MATERIALS = {}

# Expected world settings (Empty for this task)
EXPECTED_WORLD = {}

# Expected scene settings (Empty for this task)
EXPECTED_SCENE_SETTINGS = {}

# Map short node type names used in config to Blender's internal bl_idname
# Not needed for this script, but kept for template consistency
NODE_TYPE_TO_BL_IDNAME = {
    'TEX_IMAGE': 'ShaderNodeTexImage',
    'NORMAL_MAP': 'ShaderNodeNormalMap',
    # ... other node types if needed ...
}


# --- Helper Functions ---
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


# --- Check Functions ---

def check_modifiers(obj, expected_modifiers, prefix):
    """ Checks the modifier stack on an object """
    errors = []
    modifiers = obj.modifiers
    if len(modifiers) != len(expected_modifiers):
        errors.append(f"{prefix} Expected {len(expected_modifiers)} modifiers, found {len(modifiers)}.")
        return errors  # Stop checking modifiers if count mismatches

    for i, expected_mod_info in enumerate(expected_modifiers):
        mod = modifiers[i]
        mod_prefix = f"{prefix} Modifier '{mod.name}' (index {i}):"

        # Check Type
        if 'type' in expected_mod_info and mod.type != expected_mod_info['type']:
            errors.append(f"{mod_prefix} Expected type '{expected_mod_info['type']}', found '{mod.type}'.")
            continue  # Skip checking props if type is wrong

        # Check specific properties based on type
        if mod.type == 'SUBSURF':
            if 'levels' in expected_mod_info and mod.levels != expected_mod_info['levels']:
                errors.append(
                    f"{mod_prefix} Expected viewport levels {expected_mod_info['levels']}, found {mod.levels}.")
            if 'render_levels' in expected_mod_info and mod.render_levels != expected_mod_info['render_levels']:
                errors.append(
                    f"{mod_prefix} Expected render levels {expected_mod_info['render_levels']}, found {mod.render_levels}.")
        elif mod.type == 'BEVEL':
            if 'width' in expected_mod_info and not math.isclose(mod.width, expected_mod_info['width'],
                                                                 abs_tol=TOLERANCE_PROP):
                errors.append(f"{mod_prefix} Expected width {expected_mod_info['width']:.3f}, found {mod.width:.3f}.")
            if 'segments' in expected_mod_info and mod.segments != expected_mod_info['segments']:
                errors.append(f"{mod_prefix} Expected segments {expected_mod_info['segments']}, found {mod.segments}.")
            if 'limit_method' in expected_mod_info and mod.limit_method != expected_mod_info['limit_method']:
                errors.append(
                    f"{mod_prefix} Expected limit method '{expected_mod_info['limit_method']}', found '{mod.limit_method}'.")
        # Add checks for other modifier types here if needed

    return errors


def check_vertex_parenting(obj, expected_parent_check, prefix):
    """ Checks vertex parenting, including finding the closest vertex """
    errors = []
    parent_obj = obj.parent

    if not parent_obj:
        errors.append(f"{prefix} Not parented.")
        return errors
    if obj.parent_type != 'VERTEX':
        errors.append(f"{prefix} Parent type is '{obj.parent_type}', expected 'VERTEX'.")
        return errors
    if not obj.parent_vertices or len(obj.parent_vertices) == 0:
        errors.append(f"{prefix} Vertex parent type set, but no parent vertex index found.")
        return errors

    parented_vert_index = obj.parent_vertices[0]  # For single vertex parent

    # Check if parent has mesh data and vertices
    if not parent_obj.data or not isinstance(parent_obj.data, bpy.types.Mesh):
        errors.append(f"{prefix} Parent object '{parent_obj.name}' has no mesh data.")
        return errors
    if not parent_obj.data.vertices:
        errors.append(f"{prefix} Parent object '{parent_obj.name}' mesh data has no vertices.")
        return errors
    if parented_vert_index >= len(parent_obj.data.vertices):
        errors.append(
            f"{prefix} Stored parent vertex index ({parented_vert_index}) is out of bounds for parent '{parent_obj.name}' ({len(parent_obj.data.vertices)} vertices).")
        return errors

    # Find the actual closest vertex on the parent mesh to the target position
    target_world_pos = expected_parent_check['target_world_pos']
    min_dist_sq = float('inf')
    closest_index = -1
    parent_matrix_world = parent_obj.matrix_world

    for i, vert in enumerate(parent_obj.data.vertices):
        world_co = parent_matrix_world @ vert.co  # Transform vertex local coord to world
        dist_sq = (world_co - target_world_pos).length_squared
        if dist_sq < min_dist_sq:
            min_dist_sq = dist_sq
            closest_index = i

    # Compare the stored parent vertex index with the calculated closest vertex index
    if closest_index == -1:
        errors.append(f"{prefix} Could not calculate closest vertex on parent '{parent_obj.name}'.")
    elif parented_vert_index != closest_index:
        # Get coords for better error message (optional)
        actual_vert_co = (parent_matrix_world @ parent_obj.data.vertices[parented_vert_index].co).to_tuple(3)
        closest_vert_co = (parent_matrix_world @ parent_obj.data.vertices[closest_index].co).to_tuple(3)
        target_pos_str = tuple(round(c, 3) for c in target_world_pos)
        errors.append(
            f"{prefix} Parented to vertex index {parented_vert_index} {actual_vert_co}, but vertex index {closest_index} {closest_vert_co} is closest to target {target_pos_str}.")

    return errors


def check_object_properties(obj_name, expected_props):
    """Checks object properties, including modifiers and vertex parenting."""
    errors = []
    obj = bpy.data.objects.get(obj_name)

    if not obj:
        errors.append(f"Object '{obj_name}' not found.")
        return errors

    prefix = f"Object '{obj_name}':"

    # --- General Checks ---
    if 'type' in expected_props and obj.type != expected_props['type']:
        errors.append(f"{prefix} Type mismatch.")
    # Check parent name before checking parent type or vertex parent
    parent_name_ok = True
    if 'parent' in expected_props:
        expected_parent_name = expected_props.get('parent')
        expected_parent_obj = bpy.data.objects.get(expected_parent_name) if expected_parent_name else None
        if obj.parent != expected_parent_obj:
            errors.append(
                f"{prefix} Parent mismatch (Expected: '{expected_parent_name}', Found: '{obj.parent.name if obj.parent else 'None'}').")
            parent_name_ok = False  # Don't check parent type/vertex if parent name wrong
    # Check parent type only if parent name is correct (or if None was expected and found)
    if parent_name_ok and 'parent_type' in expected_props and obj.parent_type != expected_props['parent_type']:
        errors.append(f"{prefix} Expected parent type '{expected_props['parent_type']}', found '{obj.parent_type}'.")

    # Transform checks (only if value specified in expected_props)
    if 'location' in expected_props and expected_props['location'] is not None and not vector_compare(obj.location,
                                                                                                      expected_props[
                                                                                                          'location'],
                                                                                                      TOLERANCE_FLOAT):
        errors.append(f"{prefix} Location mismatch.")
    if 'scale' in expected_props and expected_props['scale'] is not None and not vector_compare(obj.scale,
                                                                                                expected_props['scale'],
                                                                                                TOLERANCE_FLOAT):
        errors.append(f"{prefix} Scale mismatch.")
    if 'rotation_euler' in expected_props and expected_props['rotation_euler'] is not None and not euler_compare(
            obj.rotation_euler, expected_props['rotation_euler'], TOLERANCE_RAD):
        errors.append(f"{prefix} Rotation mismatch.")

    # --- Modifier Checks ---
    if 'modifiers' in expected_props:
        errors.extend(check_modifiers(obj, expected_props['modifiers'], prefix))

    # --- Vertex Parent Specific Check ---
    if 'vertex_parent_check' in expected_props:
        # Only proceed if parent type is correctly 'VERTEX' (checked above implicitly or explicitly)
        if obj.parent and obj.parent_type == 'VERTEX':
            errors.extend(check_vertex_parenting(obj, expected_props['vertex_parent_check'], prefix))
        elif obj.parent_type != 'VERTEX':
            errors.append(f"{prefix} Cannot perform vertex parent check because parent type is not 'VERTEX'.")
        elif not obj.parent:
            errors.append(f"{prefix} Cannot perform vertex parent check because object is not parented.")

    # --- Material Assignment Check (If needed in future) ---
    # if 'material' in expected_props: ...

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
    result_file = os.path.join(result_dir, "tid_16_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


if __name__ == "__main__":
    run_checks()
