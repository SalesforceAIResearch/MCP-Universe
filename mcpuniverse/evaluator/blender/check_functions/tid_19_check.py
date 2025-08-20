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
TOLERANCE_PROP = 1e-4  # Property comparison (ortho scale, distance, fstop)

# Expected object data
EXPECTED_OBJECTS = {
    'Camera': {  # Assuming default Camera name
        'type': 'CAMERA',
        'location': mathutils.Vector((0.0, -10.0, 1.0)),
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),  # Check if scale is default
        'parent': None,
        'camera_data_checks': {  # Camera specific data checks
            'lens_type': 'ORTHO',
            'ortho_scale': 8.1,  # Check only if type is ORTHO
            'dof_enabled': True,
            'dof_focus_object': None,  # Explicitly check that *no* object is set
            'dof_focus_distance': 10.1,
            'dof_fstop': 2.8,
        }
    },
    'FocusPoint': {  # The empty object (not used for DOF focus in the end)
        'type': 'EMPTY',
        'location': mathutils.Vector((0.0, 0.0, 1.1)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),
        'parent': None,
        # No specific empty type required, don't check 'empty_type'
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


def euler_compare(e1, e2, tolerance_rad, check_order=False):
    if e1 is None or e2 is None:
        return False
    if check_order and hasattr(e2, 'order') and e1.order != e2.order:
        return False
    # Use quaternion comparison for more robust angle checks, especially near gimbal lock
    q1 = e1.to_quaternion()
    q2 = e2.to_quaternion()
    # Angle difference between quaternions
    dot_product = abs(q1.dot(q2))
    # Clamp dot product to avoid domain errors with acos
    dot_product = min(max(dot_product, -1.0), 1.0)
    angle_diff_rad = 2 * math.acos(dot_product)
    return angle_diff_rad < tolerance_rad


# --- Check Functions ---

def check_object_properties(obj_name, expected_props):
    """Checks object properties, including camera data settings."""
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

    # --- Camera Specific Checks ---
    if 'camera_data_checks' in expected_props:
        if obj.type != 'CAMERA':
            errors.append(f"{prefix} Expected CAMERA type for camera data checks, found '{obj.type}'.")
        elif not obj.data:
            errors.append(f"{prefix} Camera object has no camera data block.")
        else:
            cam_data = obj.data
            cam_checks = expected_props['camera_data_checks']
            prefix_cam = f"{prefix} Camera Data:"

            # Check Lens Type
            if 'lens_type' in cam_checks and cam_data.type != cam_checks['lens_type']:
                errors.append(f"{prefix_cam} Expected Lens Type '{cam_checks['lens_type']}', found '{cam_data.type}'.")
            # Check Ortho Scale only if type is Ortho
            elif cam_data.type == 'ORTHO' and 'ortho_scale' in cam_checks:
                expected_scale = cam_checks['ortho_scale']
                if not math.isclose(cam_data.ortho_scale, expected_scale, abs_tol=TOLERANCE_PROP):
                    errors.append(
                        f"{prefix_cam} Expected Orthographic Scale {expected_scale}, found {cam_data.ortho_scale:.3f}.")

            # Check DOF Enabled
            if 'dof_enabled' in cam_checks and cam_data.dof.use_dof != cam_checks['dof_enabled']:
                errors.append(
                    f"{prefix_cam} Expected DOF enabled state '{cam_checks['dof_enabled']}', found '{cam_data.dof.use_dof}'.")

            # Check DOF settings only if DOF is expected to be enabled
            if cam_checks.get('dof_enabled', False):
                # Check DOF Focus Object (should be None)
                if 'dof_focus_object' in cam_checks:
                    # This check explicitly expects None
                    expected_target_obj = None
                    found_target_obj = cam_data.dof.focus_object
                    if found_target_obj != expected_target_obj:
                        found_name = found_target_obj.name if found_target_obj else "None"
                        errors.append(f"{prefix_cam} Expected DOF focus object to be 'None', found '{found_name}'.")

                # Check DOF Focus Distance
                if 'dof_focus_distance' in cam_checks:
                    expected_dist = cam_checks['dof_focus_distance']
                    if not math.isclose(cam_data.dof.focus_distance, expected_dist, abs_tol=TOLERANCE_PROP):
                        errors.append(
                            f"{prefix_cam} Expected DOF Focus Distance {expected_dist:.2f}, found {cam_data.dof.focus_distance:.2f}.")

                # Check DOF F-Stop
                if 'dof_fstop' in cam_checks:
                    expected_fstop = cam_checks['dof_fstop']
                    if not math.isclose(cam_data.dof.aperture_fstop, expected_fstop, abs_tol=TOLERANCE_PROP):
                        errors.append(
                            f"{prefix_cam} Expected DOF F-Stop {expected_fstop:.2f}, found {cam_data.dof.aperture_fstop:.2f}.")

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
    result_file = os.path.join(result_dir, "tid_19_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


if __name__ == "__main__":
    run_checks()
