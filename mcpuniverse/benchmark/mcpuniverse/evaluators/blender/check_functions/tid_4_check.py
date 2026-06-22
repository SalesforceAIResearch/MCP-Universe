# pylint: disable=import-error, missing-module-docstring, missing-function-docstring, line-too-long, too-many-branches, too-many-locals, too-many-statements
import os
import json
import math
from pathlib import Path

import bpy
import mathutils

# --- Configuration ---
# Tolerances
TOLERANCE_FLOAT = 1e-5  # General float comparison (location, scale, blend)
TOLERANCE_RAD = math.radians(0.1)  # Angle comparison (spot size)
TOLERANCE_PROP = 1e-4  # Properties like energy, light size, fstop

# Heuristic check for default Suzanne mesh
SUZANNE_VERTS = 507
SUZANNE_FACES = 500

# Expected object data based on the REVISED lighting/DOF task
EXPECTED_OBJECTS = {
    'Subject': {
        'type': 'MESH',
        'location': mathutils.Vector((0.0, 0.0, 0.0)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),
        'parent': None,
        'mesh_verts': SUZANNE_VERTS,  # Heuristic check
        'mesh_faces': SUZANNE_FACES,  # Heuristic check
    },
    'KeyLight': {
        'type': 'LIGHT',
        'location': mathutils.Vector((-3.0, -4.0, 3.0)),
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),
        'parent': None,
        'constraint': {'type': 'TRACK_TO', 'target': 'Subject'},
        # --- Light Specific ---
        'light_type': 'AREA',
        'light_shape': 'RECTANGLE',  # For Area light
        'light_size_x': 2.0,  # obj.data.size for RECTANGLE
        'light_size_y': 1.0,  # obj.data.size_y for RECTANGLE
        'light_energy': 150.0,
    },
    'FillLight': {
        'type': 'LIGHT',
        'location': mathutils.Vector((3.0, -2.0, 2.0)),
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),
        'parent': None,
        'constraint': {'type': 'TRACK_TO', 'target': 'Subject'},
        # --- Light Specific ---
        'light_type': 'AREA',
        'light_shape': 'DISK',  # For Area light
        'light_size': 1.5,  # obj.data.size for DISK (diameter)
        'light_energy': 50.0,
    },
    'RimLight': {
        'type': 'LIGHT',
        'location': mathutils.Vector((0.0, 5.0, 4.0)),
        'scale': mathutils.Vector((0.5, 0.5, 0.5)),
        'parent': None,
        'constraint': {'type': 'TRACK_TO', 'target': 'Subject'},
        # --- Light Specific ---
        'light_type': 'SPOT',
        'light_energy': 200.0,
        'spot_size_rad': math.radians(25.0),  # Expected value in Radians
        'spot_blend': 0.2,
    },
    'MainCamera': {
        'type': 'CAMERA',
        'location': mathutils.Vector((0.0, -6.0, 2.0)),
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),
        'parent': None,
        'constraint': {'type': 'TRACK_TO', 'target': 'Subject'},
        # --- Camera Specific (DOF) ---
        'dof_enabled': True,
        'dof_focus_target': 'DOF_Target',  # Check against object name
        'dof_fstop': 1.8,
    },
    'DOF_Target': {
        'type': 'EMPTY',
        'location': mathutils.Vector((0.0, 0.0, 0.5)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),
        'parent': None,
        'empty_type': 'SPHERE',
    }
}


# --- Helper Functions ---

def vector_compare(v1, v2, tolerance):
    """Compares two vectors component-wise within a given tolerance."""
    if v1 is None or v2 is None:
        return False
    # Use length for 3D vector comparison for simplicity
    return (v1 - v2).length < tolerance
    # Alt: component-wise
    # return (math.isclose(v1.x, v2.x, abs_tol=tolerance) and
    #         math.isclose(v1.y, v2.y, abs_tol=tolerance) and
    #         math.isclose(v1.z, v2.z, abs_tol=tolerance))


def euler_compare(e1, e2, tolerance_rad, check_order=False):
    """Compares two Euler angles component-wise within a given radian tolerance."""
    if e1 is None or e2 is None:
        return False
    if check_order and hasattr(e2, 'order') and e1.order != e2.order:
        return False
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

    # Check Location only if not primarily driven by a constraint we check later (like Track To)
    # Or if explicitly needed. Here we check for all except constrained lights/camera.
    # For constrained items, we verify the constraint exists and targets correctly.
    is_constrained_for_pos = 'constraint' in expected_props and expected_props['constraint']['type'] == 'TRACK_TO'
    if not is_constrained_for_pos and 'location' in expected_props and expected_props['location'] is not None:
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

    # Check Rotation only if not primarily driven by constraint (like Track To)
    if not is_constrained_for_pos and 'rotation_euler' in expected_props and expected_props[
        'rotation_euler'] is not None:
        rot_type = "Local" if obj.parent else "World"
        expected_euler = expected_props['rotation_euler']
        if not euler_compare(obj.rotation_euler, expected_euler, TOLERANCE_RAD):
            found_deg = tuple(round(math.degrees(a), 1) for a in obj.rotation_euler)
            expected_deg = tuple(round(math.degrees(a), 1) for a in expected_euler)
            errors.append(
                f"Object '{obj_name}': Expected {rot_type} rotation {expected_deg} deg, found {found_deg} deg (Order: {obj.rotation_euler.order}).")

    # --- Data Block Checks ---
    if obj.type in ['MESH', 'LIGHT', 'CAMERA'] and not obj.data:
        errors.append(f"Object '{obj_name}': Has no data block (expected {obj.type} data).")
        # Return early if data block required for subsequent checks is missing
        if obj.type in ['LIGHT', 'CAMERA']:
            return errors

    # --- Mesh Specific Checks ---
    if obj.type == 'MESH' and obj.data:
        if 'mesh_verts' in expected_props and len(obj.data.vertices) != expected_props['mesh_verts']:
            errors.append(
                f"Object '{obj_name}': Expected mesh vertices {expected_props['mesh_verts']}, found {len(obj.data.vertices)} (Heuristic check).")
        if 'mesh_faces' in expected_props and len(obj.data.polygons) != expected_props['mesh_faces']:
            errors.append(
                f"Object '{obj_name}': Expected mesh faces {expected_props['mesh_faces']}, found {len(obj.data.polygons)} (Heuristic check).")

    # --- Light Specific Checks ---
    if obj.type == 'LIGHT' and obj.data:
        light_data = obj.data
        if 'light_type' in expected_props and light_data.type != expected_props['light_type']:
            errors.append(
                f"Object '{obj_name}': Expected light type '{expected_props['light_type']}', found '{light_data.type}'.")
            # If type mismatch, don't check specific type properties
        else:
            # Check common props
            if 'light_energy' in expected_props and not math.isclose(light_data.energy, expected_props['light_energy'],
                                                                     abs_tol=TOLERANCE_PROP):
                errors.append(
                    f"Object '{obj_name}': Expected energy {expected_props['light_energy']}, found {light_data.energy:.2f}.")

            # Check Area specific
            if light_data.type == 'AREA':
                if 'light_shape' in expected_props and light_data.shape != expected_props['light_shape']:
                    errors.append(
                        f"Object '{obj_name}': Expected area shape '{expected_props['light_shape']}', found '{light_data.shape}'.")
                elif light_data.shape == 'RECTANGLE':  # Only check size_x/y if shape is RECTANGLE
                    if 'light_size_x' in expected_props and not math.isclose(light_data.size,
                                                                             expected_props['light_size_x'],
                                                                             abs_tol=TOLERANCE_PROP):
                        errors.append(
                            f"Object '{obj_name}': Expected Rectangle size X {expected_props['light_size_x']}, found {light_data.size:.4f}.")
                    if 'light_size_y' in expected_props and not math.isclose(light_data.size_y,
                                                                             expected_props['light_size_y'],
                                                                             abs_tol=TOLERANCE_PROP):
                        errors.append(
                            f"Object '{obj_name}': Expected Rectangle size Y {expected_props['light_size_y']}, found {light_data.size_y:.4f}.")
                elif light_data.shape == 'DISK':  # Only check size if shape is DISK
                    if 'light_size' in expected_props and not math.isclose(light_data.size,
                                                                           expected_props['light_size'],
                                                                           abs_tol=TOLERANCE_PROP):
                        errors.append(
                            f"Object '{obj_name}': Expected Disk size {expected_props['light_size']}, found {light_data.size:.4f}.")

            # Check Spot specific
            elif light_data.type == 'SPOT':
                if 'spot_size_rad' in expected_props and not math.isclose(light_data.spot_size,
                                                                          expected_props['spot_size_rad'],
                                                                          abs_tol=TOLERANCE_RAD):
                    found_deg = math.degrees(light_data.spot_size)
                    expected_deg = math.degrees(expected_props['spot_size_rad'])
                    errors.append(
                        f"Object '{obj_name}': Expected spot size ~{expected_deg:.1f} deg, found ~{found_deg:.1f} deg.")
                if 'spot_blend' in expected_props and not math.isclose(light_data.spot_blend,
                                                                       expected_props['spot_blend'],
                                                                       abs_tol=TOLERANCE_FLOAT):
                    errors.append(
                        f"Object '{obj_name}': Expected spot blend {expected_props['spot_blend']}, found {light_data.spot_blend:.4f}.")

    # --- Camera Specific Checks ---
    if obj.type == 'CAMERA' and obj.data:
        cam_data = obj.data
        if 'dof_enabled' in expected_props and cam_data.dof.use_dof != expected_props['dof_enabled']:
            errors.append(
                f"Object '{obj_name}': Expected DOF enabled state '{expected_props['dof_enabled']}', found '{cam_data.dof.use_dof}'.")

        # Check DOF Target only if DOF is expected to be enabled
        if expected_props.get('dof_enabled', False):
            if 'dof_focus_target' in expected_props:
                expected_target_name = expected_props['dof_focus_target']
                expected_target_obj = bpy.data.objects.get(expected_target_name)
                found_target_obj = cam_data.dof.focus_object
                if found_target_obj != expected_target_obj:
                    found_name = found_target_obj.name if found_target_obj else "None"
                    errors.append(
                        f"Object '{obj_name}': Expected DOF focus target '{expected_target_name}', found '{found_name}'.")

            if 'dof_fstop' in expected_props and not math.isclose(cam_data.dof.aperture_fstop,
                                                                  expected_props['dof_fstop'], abs_tol=TOLERANCE_PROP):
                errors.append(
                    f"Object '{obj_name}': Expected DOF F-Stop {expected_props['dof_fstop']}, found {cam_data.dof.aperture_fstop:.2f}.")

    # --- Empty Specific Checks ---
    if obj.type == 'EMPTY':
        if 'empty_type' in expected_props and obj.empty_display_type != expected_props['empty_type']:
            errors.append(
                f"Object '{obj_name}': Expected empty type '{expected_props['empty_type']}', found '{obj.empty_display_type}'.")

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
                    # Found constraint of correct type and target
                    # Add checks for specific constraint props if needed here
                    found_constraint_match = True
                    break  # Assume only one constraint of this type/target needed

            if not found_constraint_match:
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
    result_file = os.path.join(result_dir, "tid_4_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


if __name__ == "__main__":
    run_checks()
