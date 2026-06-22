# pylint: disable=import-error, missing-module-docstring, missing-function-docstring, line-too-long, too-many-branches, too-many-locals, too-many-statements
import os
import json
import math
from pathlib import Path

import bpy
import mathutils

# --- Configuration ---
TOLERANCE_FLOAT = 1e-5  # General float comparison (location, scale)
TOLERANCE_RAD = math.radians(0.1)  # Angle comparison
TOLERANCE_DIM = 1e-4  # Dimension/origin comparison

# Expected object data based on the REVISED hierarchy/origin task
EXPECTED_OBJECTS = {
    'Foundation': {
        'type': 'MESH',  # Cube
        'location': mathutils.Vector((0.0, 0.0, 0.0)),
    },
    'TowerBase': {
        'type': 'MESH',  # Cylinder
        'location': mathutils.Vector((0.0, 0.0, 4.0)),
        'parent': 'Foundation',
        'vertices': 16,
        # Base dimensions R=0.8 -> D=1.6, Depth=4.0
        'expected_dimensions': mathutils.Vector((1.6, 1.6, 4.0)),
    },
    'MidSection': {
        'type': 'MESH',  # Cylinder
        'location': mathutils.Vector((0.0, 0.0, 8.0)),
        'parent': 'TowerBase',
        # Base dimensions R=0.7 -> D=1.4, Depth=3.0
        'expected_dimensions': mathutils.Vector((1.4, 1.4, 3.0)),
        'vertices': 32,
    },
    'Spire': {
        'type': 'MESH',  # Cylinder
        'location': mathutils.Vector((0.0, 0.0, 14.0)),
        'parent': 'MidSection',
        # Base dimensions R=0.1 -> D=0.2, Depth=2.0
        'expected_dimensions': mathutils.Vector((0.2, 0.2, 2.0)),
        'vertices': 64,
    },
    'Beacon': {
        'type': 'EMPTY',
        'empty_type': 'CONE',
        'location': mathutils.Vector((0.0, 0.0, 16.0)),
        'parent': 'Spire',
    }
}


# --- Helper Functions ---

def vector_compare(v1, v2, tolerance, ignore_axis=None):
    """Compares two vectors component-wise within a given tolerance, optionally ignoring an axis."""
    if v1 is None or v2 is None:
        return False
    close_x = (ignore_axis == 'x') or math.isclose(v1.x, v2.x, abs_tol=tolerance)
    close_y = (ignore_axis == 'y') or math.isclose(v1.y, v2.y, abs_tol=tolerance)
    close_z = (ignore_axis == 'z') or math.isclose(v1.z, v2.z, abs_tol=tolerance)
    return close_x and close_y and close_z


def euler_compare(e1, e2, tolerance_rad, check_order=False):
    """Compares two Euler angles component-wise within a given radian tolerance."""
    if e1 is None or e2 is None:
        return False
    if check_order and hasattr(e2, 'order') and e1.order != e2.order:
        return False
    return (math.isclose(e1.x, e2.x, abs_tol=tolerance_rad) and
            math.isclose(e1.y, e2.y, abs_tol=tolerance_rad) and
            math.isclose(e1.z, e2.z, abs_tol=tolerance_rad))


def calculate_mesh_bbox_center_local(mesh_data):
    """Calculates the center of the bounding box of mesh vertices in local coords."""
    if not mesh_data or not mesh_data.vertices:
        return None, "No mesh data or vertices"

    verts = [v.co for v in mesh_data.vertices]
    if not verts:
        return None, "Vertex list is empty"

    min_v = mathutils.Vector((min(v.x for v in verts), min(v.y for v in verts), min(v.z for v in verts)))
    max_v = mathutils.Vector((max(v.x for v in verts), max(v.y for v in verts), max(v.z for v in verts)))

    center = (min_v + max_v) / 2.0
    return center, None


def check_object_properties(obj_name, expected_props):
    """Checks properties, including hierarchy, local transforms, and origin placement."""
    errors = []
    obj = bpy.data.objects.get(obj_name)

    if not obj:
        errors.append(f"Object '{obj_name}' not found.")
        return errors

    # --- General Checks ---
    if 'type' in expected_props and obj.type != expected_props['type']:
        errors.append(f"Object '{obj_name}': Expected type '{expected_props['type']}', found '{obj.type}'.")

    expected_parent_name = expected_props.get('parent')
    expected_parent_obj = bpy.data.objects.get(expected_parent_name) if expected_parent_name else None
    if obj.parent != expected_parent_obj:
        found_parent_name = obj.parent.name if obj.parent else "None"
        expected_name_str = expected_parent_name if expected_parent_name else "None"
        errors.append(f"Object '{obj_name}': Expected parent '{expected_name_str}', found '{found_parent_name}'.")

    # Check Location (obj.location is LOCAL if parented, WORLD if not parented)
    if 'location' in expected_props and expected_props['location'] is not None:
        loc_type = "Local" if obj.parent else "World"
        if not vector_compare(obj.location, expected_props['location'], TOLERANCE_FLOAT):
            expected_loc_str = tuple(round(c, 3) for c in expected_props['location'])
            found_loc_str = tuple(round(c, 3) for c in obj.location)
            errors.append(
                f"Object '{obj_name}': Expected {loc_type} location {expected_loc_str}, found {found_loc_str}.")

    # Check Scale (obj.scale is LOCAL if parented, WORLD if not parented)
    if 'scale' in expected_props and expected_props['scale'] is not None:
        scale_type = "Local" if obj.parent else "World"
        if not vector_compare(obj.scale, expected_props['scale'], TOLERANCE_FLOAT):
            found_scale_rounded = tuple(round(s, 3) for s in obj.scale)
            expected_scale_str = tuple(round(s, 3) for s in expected_props['scale'])
            errors.append(
                f"Object '{obj_name}': Expected {scale_type} scale {expected_scale_str}, found {found_scale_rounded}.")

    # Check Rotation (obj.rotation_euler is LOCAL if parented, WORLD if not parented)
    if 'rotation_euler' in expected_props and expected_props['rotation_euler'] is not None:
        rot_type = "Local" if obj.parent else "World"
        expected_euler = expected_props['rotation_euler']
        if not euler_compare(obj.rotation_euler, expected_euler, TOLERANCE_RAD):
            found_deg = tuple(round(math.degrees(a), 1) for a in obj.rotation_euler)
            expected_deg = tuple(round(math.degrees(a), 1) for a in expected_euler)
            errors.append(
                f"Object '{obj_name}': Expected {rot_type} rotation {expected_deg} deg, found {found_deg} deg (Order: {obj.rotation_euler.order}).")

    # --- Data Block Checks ---
    if obj.type in ['MESH'] and not obj.data:
        errors.append(f"Object '{obj_name}': Has no mesh data block.")

    # --- Vertices Count Check ---
    if 'vertices' in expected_props and obj.type == 'MESH':
        if not obj.data:
            errors.append(f"Object '{obj_name}': Cannot check vertices count without mesh data.")
        else:
            num_verts = len(obj.data.vertices)
            expected_verts = expected_props['vertices']
            if num_verts != expected_verts:
                errors.append(f"Object '{obj_name}': Expected {expected_verts} vertices, found {num_verts}.")

    # --- Dimension Check (Based on obj.dimensions, which includes object scale) ---
    if 'expected_dimensions' in expected_props:
        expected_dims = expected_props['expected_dimensions']
        if not vector_compare(obj.dimensions, expected_dims, TOLERANCE_DIM):
            found_dims_rnd = tuple(round(d, 3) for d in obj.dimensions)
            exp_dims_rnd = tuple(round(d, 3) for d in expected_dims)
            errors.append(f"Object '{obj_name}': Expected dimensions {exp_dims_rnd}, found {found_dims_rnd}.")

    # --- Origin Check (Relative to Mesh BBox) ---
    if 'origin_check' in expected_props and obj.type == 'MESH':
        if not obj.data:
            errors.append(f"Object '{obj_name}': Cannot perform origin check without mesh data.")
        else:
            bbox_center, err_msg = calculate_mesh_bbox_center_local(obj.data)
            if err_msg:
                errors.append(f"Object '{obj_name}': Origin check failed - {err_msg}.")
            else:
                # We expect the origin (0,0,0) to be at the bottom-center.
                # This means the bbox center should be at Z = height/2.
                # Check X and Y center are near 0, Z center is near expected_bbox_center_z_local
                expected_z = expected_props['origin_check']['expected_bbox_center_z_local']

                # Compare X, Y (should be near 0) and Z (should be near expected Z)
                if not (math.isclose(bbox_center.x, 0.0, abs_tol=TOLERANCE_DIM) and \
                        math.isclose(bbox_center.y, 0.0, abs_tol=TOLERANCE_DIM) and \
                        math.isclose(bbox_center.z, expected_z, abs_tol=TOLERANCE_DIM)):
                    found_center_rnd = tuple(round(c, 3) for c in bbox_center)
                    exp_center_str = f"(~0, ~0, {expected_z:.3f})"  # Describe target location
                    errors.append(
                        f"Object '{obj_name}': Origin check failed. Expected mesh bbox center {exp_center_str}, found {found_center_rnd} in local coordinates. (Check Edit Mode origin placement).")

    # --- Empty Specific Checks ---
    if obj.type == 'EMPTY':
        if 'empty_type' in expected_props and obj.empty_display_type != expected_props['empty_type']:
            errors.append(
                f"Object '{obj_name}': Expected empty type '{expected_props['empty_type']}', found '{obj.empty_display_type}'.")

    return errors


# --- Main Execution ---
def run_checks():
    print(f"--- Starting Scene Validation ({bpy.data.filepath}) ---")
    all_errors = []

    for obj_name, props in EXPECTED_OBJECTS.items():
        print(f"Checking '{obj_name}'...")
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
    result_file = os.path.join(result_dir, "tid_5_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


if __name__ == "__main__":
    run_checks()
