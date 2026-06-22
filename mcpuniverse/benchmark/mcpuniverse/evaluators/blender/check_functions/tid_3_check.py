# pylint: disable=import-error, missing-module-docstring, missing-function-docstring, line-too-long, too-many-branches, too-many-locals, too-many-statements
import os
import json
import math
from pathlib import Path

import bpy
import mathutils

# --- Configuration ---
# Tolerances for checking float values
TOLERANCE_FLOAT = 1e-5  # For general comparisons like offset_factor
TOLERANCE_RAD = math.radians(0.1)  # For angle comparisons (approx 0.1 deg)
TOLERANCE_PROP = 1e-4  # For properties like size, extrude, bevel (adjust if needed)

# Expected object data based on the REVISED text/path task
EXPECTED_OBJECTS = {
    'Title': {
        'type': 'FONT',
        'location': mathutils.Vector((0.0, 0.0, 5.0)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),  # Default rotation
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),  # Default scale
        'parent': None,
        # --- Text Specific ---
        'text_content': 'Blender MCP',
        'font_size': 1.5,
        'extrude': 0.1,
        'bevel_depth': 0.02,
        'bevel_resolution': 2,  # Integer
    },
    'PathCircle': {
        'type': 'CURVE',
        'location': mathutils.Vector((0.0, 0.0, 0.0)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),  # Default rotation
        'scale': mathutils.Vector((3.0, 3.0, 3.0)),  # Scaled for radius
        'parent': None,
        # --- Curve Specific (checking first spline) ---
        'curve_type': 'BEZIER',
        'curve_cyclic': True,
    },
    'Tracer': {
        'type': 'MESH',  # Cone primitive
        # Location & Rotation are intentionally NOT checked as they are driven by the constraint
        'scale': mathutils.Vector((0.2, 0.2, 0.2)),
        'parent': None,
        # --- Constraint Specific ---
        'constraint': {
            'type': 'FOLLOW_PATH',
            'target': 'PathCircle',
            'use_curve_follow': True,  # Boolean
            'use_fixed_location': True,  # Boolean
            'offset_factor': 0.25,  # Float
        }
    }
}


# --- Helper Functions ---

def vector_compare(v1, v2, tolerance):
    """Compares two vectors component-wise within a given tolerance."""
    if v1 is None or v2 is None:
        return False
    return (math.isclose(v1.x, v2.x, abs_tol=tolerance) and
            math.isclose(v1.y, v2.y, abs_tol=tolerance) and
            math.isclose(v1.z, v2.z, abs_tol=tolerance))


def euler_compare(e1, e2, tolerance_rad, check_order=False):  # Disabled order check by default
    """Compares two Euler angles component-wise within a given radian tolerance."""
    if e1 is None or e2 is None:
        return False
    if check_order and hasattr(e2, 'order') and e1.order != e2.order:
        return False  # Strict order check if enabled
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

    # --- General Checks ---
    if 'type' in expected_props and obj.type != expected_props['type']:
        errors.append(f"Object '{obj_name}': Expected type '{expected_props['type']}', found '{obj.type}'.")

    expected_parent_name = expected_props.get('parent')
    expected_parent_obj = bpy.data.objects.get(expected_parent_name) if expected_parent_name else None
    if obj.parent != expected_parent_obj:
        found_parent_name = obj.parent.name if obj.parent else "None"
        expected_name_str = expected_parent_name if expected_parent_name else "None"
        errors.append(f"Object '{obj_name}': Expected parent '{expected_name_str}', found '{found_parent_name}'.")

    if 'location' in expected_props and expected_props['location'] is not None:
        loc_type = "Local" if obj.parent else "World"
        if not vector_compare(obj.location, expected_props['location'], TOLERANCE_FLOAT):
            expected_loc_str = tuple(round(c, 3) for c in expected_props['location'])
            found_loc_str = tuple(round(c, 3) for c in obj.location)
            errors.append(
                f"Object '{obj_name}': Expected {loc_type} location {expected_loc_str}, found {found_loc_str}.")

    if 'scale' in expected_props and expected_props['scale'] is not None:
        if not vector_compare(obj.scale, expected_props['scale'], TOLERANCE_FLOAT):
            found_scale_rounded = tuple(round(s, 3) for s in obj.scale)
            expected_scale_str = tuple(round(s, 3) for s in expected_props['scale'])
            errors.append(f"Object '{obj_name}': Expected scale {expected_scale_str}, found {found_scale_rounded}.")

    if 'rotation_euler' in expected_props and expected_props['rotation_euler'] is not None:
        rot_type = "Local" if obj.parent else "World"
        expected_euler = expected_props['rotation_euler']
        if not euler_compare(obj.rotation_euler, expected_euler, TOLERANCE_RAD):
            found_deg = tuple(round(math.degrees(a), 1) for a in obj.rotation_euler)
            expected_deg = tuple(round(math.degrees(a), 1) for a in expected_euler)
            errors.append(
                f"Object '{obj_name}': Expected {rot_type} rotation {expected_deg} deg, found {found_deg} deg (Order: {obj.rotation_euler.order}).")

    # --- Data Block Checks (Text, Curve) ---
    if obj.type in ['FONT', 'CURVE'] and not obj.data:
        errors.append(f"Object '{obj_name}': Has no data block (expected {obj.type} data).")
        return errors  # Cannot check data properties if data block is missing

    # --- Text Specific Checks ---
    if obj.type == 'FONT':
        if 'text_content' in expected_props and obj.data.body != expected_props['text_content']:
            errors.append(
                f"Object '{obj_name}': Expected text content '{expected_props['text_content']}', found '{obj.data.body}'.")
        if 'font_size' in expected_props and not math.isclose(obj.data.size, expected_props['font_size'],
                                                              abs_tol=TOLERANCE_PROP):
            errors.append(
                f"Object '{obj_name}': Expected font size {expected_props['font_size']}, found {obj.data.size:.4f}.")
        if 'extrude' in expected_props and not math.isclose(obj.data.extrude, expected_props['extrude'],
                                                            abs_tol=TOLERANCE_PROP):
            errors.append(
                f"Object '{obj_name}': Expected extrude {expected_props['extrude']}, found {obj.data.extrude:.4f}.")
        if 'bevel_depth' in expected_props and not math.isclose(obj.data.bevel_depth, expected_props['bevel_depth'],
                                                                abs_tol=TOLERANCE_PROP):
            errors.append(
                f"Object '{obj_name}': Expected bevel depth {expected_props['bevel_depth']}, found {obj.data.bevel_depth:.4f}.")
        if 'bevel_resolution' in expected_props and obj.data.bevel_resolution != expected_props['bevel_resolution']:
            errors.append(
                f"Object '{obj_name}': Expected bevel resolution {expected_props['bevel_resolution']}, found {obj.data.bevel_resolution}.")

    # --- Curve Specific Checks ---
    if obj.type == 'CURVE':
        if not obj.data.splines:
            errors.append(f"Object '{obj_name}': Curve data has no splines.")
        else:
            spline = obj.data.splines[0]  # Check the first spline
            if 'curve_type' in expected_props and spline.type != expected_props['curve_type']:
                errors.append(
                    f"Object '{obj_name}': Expected curve type '{expected_props['curve_type']}', found '{spline.type}'.")
            if 'curve_cyclic' in expected_props and spline.use_cyclic_u != expected_props['curve_cyclic']:
                errors.append(
                    f"Object '{obj_name}': Expected curve cyclic state '{expected_props['curve_cyclic']}', found '{spline.use_cyclic_u}'.")

    # --- Constraint Checks ---
    if 'constraint' in expected_props:
        found_constraint_match = False
        expected_constraint = expected_props['constraint']
        target_obj = bpy.data.objects.get(expected_constraint['target'])

        if not target_obj:
            errors.append(
                f"Object '{obj_name}': Constraint check failed - target object '{expected_constraint['target']}' not found.")
        else:
            for constraint in obj.constraints:
                if constraint.type == expected_constraint['type'] and hasattr(constraint,
                                                                              'target') and constraint.target == target_obj:
                    # Found constraint of correct type and target, now check properties
                    prop_mismatch = False
                    if 'use_curve_follow' in expected_constraint and constraint.use_curve_follow != expected_constraint[
                        'use_curve_follow']:
                        errors.append(
                            f"Object '{obj_name}', Constraint '{constraint.name}': Expected use_curve_follow={expected_constraint['use_curve_follow']}, found {constraint.use_curve_follow}.")
                        prop_mismatch = True
                    if 'use_fixed_location' in expected_constraint and constraint.use_fixed_location != \
                            expected_constraint['use_fixed_location']:
                        errors.append(
                            f"Object '{obj_name}', Constraint '{constraint.name}': Expected use_fixed_location={expected_constraint['use_fixed_location']}, found {constraint.use_fixed_location}.")
                        prop_mismatch = True
                    if 'offset_factor' in expected_constraint and not math.isclose(constraint.offset_factor,
                                                                                   expected_constraint['offset_factor'],
                                                                                   abs_tol=TOLERANCE_FLOAT):
                        errors.append(
                            f"Object '{obj_name}', Constraint '{constraint.name}': Expected offset_factor={expected_constraint['offset_factor']}, found {constraint.offset_factor:.4f}.")
                        prop_mismatch = True

                    if not prop_mismatch:
                        found_constraint_match = True
                        break  # Found fully matching constraint

            if not found_constraint_match:
                # Avoid double error if target wasn't found
                if target_obj:
                    errors.append(
                        f"Object '{obj_name}': No constraint matching all properties found (Type='{expected_constraint['type']}', Target='{expected_constraint['target']}').")

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
    result_file = os.path.join(result_dir, "tid_3_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


# Run the checks when the script is executed
if __name__ == "__main__":
    run_checks()
