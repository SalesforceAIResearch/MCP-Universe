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
TOLERANCE_RAD = math.radians(0.1)  # Angle comparison
TOLERANCE_PROP = 1e-4  # Property comparison
TOLERANCE_COLOR = 1e-3  # Color comparison

# Expected Collections
EXPECTED_COLLECTIONS = {
    'Group_Red': {'exists': True},
    'Group_Blue': {'exists': True},
    'Collection': {'exists': True},  # Default scene collection
}

# Expected object data
EXPECTED_OBJECTS = {
    'Obj_A': {
        'type': 'MESH',  # Cube
        'location': mathutils.Vector((0.0, 0.0, 0.0)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),
        'parent': None,
        'collection_membership': {
            'include': ['Group_Red'],  # Must be in this collection
            'exclude': ['Collection']  # Must NOT be in this collection
        }
    },
    'Obj_B': {
        'type': 'MESH',  # UV Sphere
        'location': mathutils.Vector((0.0, 0.0, 0.0)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),
        'parent': None,
        'collection_membership': {
            'include': ['Group_Blue'],
            'exclude': ['Collection']
        },
        'custom_properties': {
            'AssetID': {
                'value': 12345,
                'type': int,
                'tooltip': 'Sphere Asset Identifier'
            }
            # Add more custom props here if needed
        }
    },
    'Obj_C': {
        'type': 'MESH',  # Cone
        'location': mathutils.Vector((0.0, 0.0, 0.0)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),
        'parent': None,
        'collection_membership': {
            'include': ['Group_Red'],
            'exclude': ['Collection']
        }
    }
}

# --- No Material, World, or Scene checks needed for this task ---
EXPECTED_MATERIALS = {}
EXPECTED_WORLD = {}
EXPECTED_SCENE_SETTINGS = {}


# --- Helper Functions ---
# Assume vector_compare and euler_compare are defined as in previous examples
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


def euler_compare(e1, e2, tolerance_rad):
    if e1 is None or e2 is None:
        return False
    q1 = e1.to_quaternion()
    q2 = e2.to_quaternion()
    dot_product = min(max(abs(q1.dot(q2)), -1.0), 1.0)
    angle_diff_rad = 2 * math.acos(dot_product)
    return angle_diff_rad < tolerance_rad


# --- Check Functions ---

def check_collections(expected_collections):
    """ Checks if the specified collections exist """
    errors = []
    prefix = "Collections Check:"
    for coll_name, expected_info in expected_collections.items():
        collection = bpy.data.collections.get(coll_name)
        if expected_info.get('exists', False) and not collection:
            errors.append(f"{prefix} Expected collection '{coll_name}' not found.")
        elif not expected_info.get('exists', True) and collection:  # Check if expected NOT to exist
            errors.append(f"{prefix} Collection '{coll_name}' exists but was not expected.")
        # Add more checks here if needed (e.g., check if collection is linked to scene)
    return errors


def check_object_properties(obj_name, expected_props):
    """Checks object properties, including collection membership and custom props."""
    errors = []
    obj = bpy.data.objects.get(obj_name)

    if not obj:
        errors.append(f"Object '{obj_name}' not found.")
        return errors

    prefix = f"Object '{obj_name}':"

    # --- General Checks ---
    if 'type' in expected_props and obj.type != expected_props['type']:
        errors.append(f"{prefix} Type mismatch.")
    if 'parent' in expected_props:
        expected_parent_name = expected_props.get('parent')
        expected_parent_obj = bpy.data.objects.get(expected_parent_name) if expected_parent_name else None
        if obj.parent != expected_parent_obj:
            errors.append(f"{prefix} Parent mismatch.")
    if 'location' in expected_props and not vector_compare(obj.location, expected_props['location'], TOLERANCE_FLOAT):
        errors.append(f"{prefix} Location mismatch.")
    if 'scale' in expected_props and not vector_compare(obj.scale, expected_props['scale'], TOLERANCE_FLOAT):
        errors.append(f"{prefix} Scale mismatch.")
    if 'rotation_euler' in expected_props and not euler_compare(obj.rotation_euler, expected_props['rotation_euler'],
                                                                TOLERANCE_RAD):
        errors.append(f"{prefix} Rotation mismatch.")

    # --- Collection Membership Check ---
    if 'collection_membership' in expected_props:
        expected_membership = expected_props['collection_membership']
        current_coll_names = [c.name for c in obj.users_collection]

        # Check includes
        if 'include' in expected_membership:
            for expected_coll_name in expected_membership['include']:
                if expected_coll_name not in current_coll_names:
                    errors.append(
                        f"{prefix} Expected to be in collection '{expected_coll_name}', but not found. Found in: {current_coll_names}")

        # Check excludes
        if 'exclude' in expected_membership:
            for expected_coll_name in expected_membership['exclude']:
                if expected_coll_name in current_coll_names:
                    errors.append(
                        f"{prefix} Expected NOT to be in collection '{expected_coll_name}', but it was found. Found in: {current_coll_names}")

    # --- Custom Property Check ---
    if 'custom_properties' in expected_props:
        expected_custom_props = expected_props['custom_properties']
        prop_prefix = f"{prefix} Custom Property"

        for prop_name, expected_info in expected_custom_props.items():
            # Check existence
            if prop_name not in obj:  # Use 'in' operator for custom props
                errors.append(f"{prop_prefix} '{prop_name}': Not found.")
                continue  # Skip other checks if prop doesn't exist

            prop_value = obj[prop_name]

            # Check type
            if 'type' in expected_info and not isinstance(prop_value, expected_info['type']):
                errors.append(
                    f"{prop_prefix} '{prop_name}': Expected type {expected_info['type'].__name__}, found {type(prop_value).__name__}.")
                # Don't compare value if type is wrong, might cause error
                continue

            # Check value
            if 'value' in expected_info:
                expected_value = expected_info['value']
                value_match = False
                if isinstance(expected_value, float):
                    value_match = math.isclose(prop_value, expected_value, abs_tol=TOLERANCE_FLOAT)
                else:  # Assume direct comparison works for int, string, bool etc.
                    value_match = prop_value == expected_value
                if not value_match:
                    errors.append(f"{prop_prefix} '{prop_name}': Expected value {expected_value}, found {prop_value}.")

            # Check tooltip (using _RNA_UI, may be fragile)
            if 'tooltip' in expected_info:
                tooltip = None
                # Attempt to access tooltip via _RNA_UI dictionary
                if '_RNA_UI' in obj and prop_name in obj['_RNA_UI']:
                    tooltip = obj['_RNA_UI'][prop_name].get('description')  # Use .get() for safety

                if tooltip != expected_info['tooltip']:
                    errors.append(
                        f"{prop_prefix} '{prop_name}': Expected tooltip '{expected_info['tooltip']}', found '{tooltip}'.")

    return errors


# --- Main Execution ---
def run_checks():
    print(f"--- Starting Scene Validation ({bpy.data.filepath}) ---")
    all_errors = []

    # Check Collections
    print("\n--- Checking Collections ---")
    coll_errors = check_collections(EXPECTED_COLLECTIONS)
    if coll_errors:
        all_errors.extend(coll_errors)
    else:
        print(" -> Collections existence checks passed.")

    # Check Objects (includes collection membership and custom properties)
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
    result_file = os.path.join(result_dir, "tid_20_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


if __name__ == "__main__":
    run_checks()
