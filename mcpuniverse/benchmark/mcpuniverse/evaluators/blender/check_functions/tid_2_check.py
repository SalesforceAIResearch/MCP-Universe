# pylint: disable=import-error, missing-module-docstring, missing-function-docstring, line-too-long, too-many-branches, too-many-locals
import os
import json
import math
from pathlib import Path

import bpy
import mathutils

# --- Configuration ---
# Tolerance for comparing floating point numbers (locations, scales)
TOLERANCE_FLOAT = 1e-5
# Tolerance for comparing rotation angles (in radians)
TOLERANCE_RAD = math.radians(0.1)  # Approx 0.1 degree tolerance

# Expected object data based on the REVISED task description
EXPECTED_OBJECTS = {
    'Star': {
        'type': 'MESH',
        'location': mathutils.Vector((0.0, 0.0, 0.0)),  # World location
        'scale': mathutils.Vector((3.0, 3.0, 3.0)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),  # Assuming default rotation order
        'parent': None,
    },
    'PlanetOrbitControl': {
        'type': 'EMPTY',
        'empty_type': 'PLAIN_AXES',
        'location': mathutils.Vector((5.0, 0.0, 0.0)),  # Local location relative to Star
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),
        # Local rotation relative to Star (Z=30deg)
        'rotation_euler': mathutils.Euler((0.0, 0.0, math.radians(30.0)), 'XYZ'),
        'parent': 'Star',
    },
    'Planet': {
        'type': 'MESH',
        'location': mathutils.Vector((4.0, 0.0, 0.0)),  # Local location relative to PlanetOrbitControl
        'scale': mathutils.Vector((0.5, 0.5, 0.5)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),  # Local rotation should be zero
        'parent': 'PlanetOrbitControl',
    },
    'Moon': {
        'type': 'MESH',
        'location': mathutils.Vector((1.0, 0.0, 0.0)),  # Local location relative to Planet
        'scale': mathutils.Vector((0.1, 0.1, 0.1)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),  # Local rotation should be zero
        'parent': 'Planet',
    },
    'Satellite': {
        'type': 'MESH',  # Cube
        'location': None,  # Location is driven by constraint, no need to check specific value unless intended
        'scale': mathutils.Vector((0.05, 0.05, 0.05)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),  # Assuming default rotation
        'parent': None,
        'constraint': {'type': 'COPY_LOCATION', 'target': 'Moon'}
    }
}


# --- Helper Functions ---

def vector_compare(v1, v2, tolerance):
    """Compares two vectors within a given tolerance."""
    if v1 is None or v2 is None:
        return False
    return (v1 - v2).length < tolerance


def euler_compare(e1, e2, tolerance_rad, check_order=True):
    """Compares two Euler angles component-wise within a given radian tolerance."""
    if e1 is None or e2 is None:
        return False
    # Optional: Check if rotation order matches if specified in expected
    if check_order and hasattr(e2, 'order') and e1.order != e2.order:
        # Log a warning or error if order matters and differs? For now, just compare values.
        # print(f"Warning: Euler order mismatch {e1.order} vs {e2.order}")
        pass  # Or return False if order must match strictly
    # Compare X, Y, Z components
    return (math.isclose(e1.x, e2.x, abs_tol=tolerance_rad) and
            math.isclose(e1.y, e2.y, abs_tol=tolerance_rad) and
            math.isclose(e1.z, e2.z, abs_tol=tolerance_rad))


def check_object_properties(obj_name, expected_props):
    """Checks properties based on the expected configuration."""
    errors = []
    obj = bpy.data.objects.get(obj_name)

    if not obj:
        errors.append(f"Object '{obj_name}' not found.")
        return errors

    # Check Type
    if 'type' in expected_props and obj.type != expected_props['type']:
        errors.append(f"Object '{obj_name}': Expected type '{expected_props['type']}', found '{obj.type}'.")

    # Check Parent
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

    # Check Scale
    if 'scale' in expected_props and expected_props['scale'] is not None:
        if not vector_compare(obj.scale, expected_props['scale'], TOLERANCE_FLOAT):
            found_scale_rounded = tuple(round(s, 3) for s in obj.scale)
            expected_scale_str = tuple(round(s, 3) for s in expected_props['scale'])
            errors.append(f"Object '{obj_name}': Expected scale {expected_scale_str}, found {found_scale_rounded}.")

    # Check Rotation (Euler)
    if 'rotation_euler' in expected_props and expected_props['rotation_euler'] is not None:
        rot_type = "Local" if obj.parent else "World"
        expected_euler = expected_props['rotation_euler']
        if not euler_compare(obj.rotation_euler, expected_euler, TOLERANCE_RAD):
            found_deg = tuple(round(math.degrees(a), 1) for a in obj.rotation_euler)
            expected_deg = tuple(round(math.degrees(a), 1) for a in expected_euler)
            errors.append(
                f"Object '{obj_name}': Expected {rot_type} rotation {expected_deg} deg, found {found_deg} deg (Order: {obj.rotation_euler.order}).")

    # Check Empty Type
    if obj.type == 'EMPTY' and 'empty_type' in expected_props:
        if obj.empty_display_type != expected_props['empty_type']:
            errors.append(
                f"Object '{obj_name}': Expected empty type '{expected_props['empty_type']}', found '{obj.empty_display_type}'.")

    # Check Constraints
    if 'constraint' in expected_props:
        found_constraint = False
        expected_constraint = expected_props['constraint']
        target_obj = bpy.data.objects.get(expected_constraint['target'])
        if not target_obj:
            errors.append(
                f"Object '{obj_name}': Constraint check failed - target object '{expected_constraint['target']}' not found.")
        else:
            for constraint in obj.constraints:
                if constraint.type == expected_constraint['type']:
                    if hasattr(constraint, 'target') and constraint.target == target_obj:
                        # Optional: Check constraint space if needed (World->World is default for Copy Location)
                        # if constraint.type == 'COPY_LOCATION':
                        #     if constraint.target_space != 'WORLD' or constraint.owner_space != 'WORLD':
                        #         errors.append(f"...")
                        found_constraint = True
                        break
            if not found_constraint:
                errors.append(
                    f"Object '{obj_name}': Expected constraint '{expected_constraint['type']}' targeting '{expected_constraint['target']}' not found or target mismatch.")

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

    result = {}
    if not all_errors:
        print("Validation Successful! All checks passed.")
        # Consider exiting with success code 0 for automation
        # import sys; sys.exit(0)
        result = {
            "pass": True,
            "reason": ""
        }
    else:
        print("Validation Failed. Errors found:")
        for error in all_errors:
            print(f"- {error}")
        # Consider exiting with error code 1 for automation
        # import sys; sys.exit(1)
        result = {
            "pass": False,
            "reason": "; ".join(all_errors)
        }

    # Save results to JSON file
    parent_dir = str(Path(__file__).parent.parent)
    result_dir = f"{parent_dir}/evaluated_results"
    os.makedirs(result_dir, exist_ok=True)
    result_file = os.path.join(result_dir, "tid_2_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


if __name__ == "__main__":
    run_checks()
