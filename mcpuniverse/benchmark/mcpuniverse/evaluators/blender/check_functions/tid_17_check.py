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
TOLERANCE_PROP = 1e-4  # Property comparison (mass, friction)

# Expected scene settings
EXPECTED_SCENE_SETTINGS = {
    'render_engine': 'CYCLES',
    'cycles_device': 'CPU',
}

# Expected object data with Rigid Body checks
EXPECTED_OBJECTS = {
    'Ground': {
        'type': 'MESH',  # Plane
        'location': mathutils.Vector((0.0, 0.0, 0.0)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),
        'scale': mathutils.Vector((10.0, 10.0, 10.0)),  # Uniform scale
        'parent': None,
        'rigidbody_checks': {
            'enabled': True,
            'type': 'PASSIVE',
            'collision_shape': 'MESH',
        }
    },
    'Ball': {
        'type': 'MESH',  # UV Sphere
        'location': mathutils.Vector((0.0, 0.0, 5.0)),
        'rotation_euler': mathutils.Euler((0.0, 0.0, 0.0), 'XYZ'),
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),  # Default scale
        'parent': None,
        'rigidbody_checks': {
            'enabled': True,
            'type': 'ACTIVE',
            'collision_shape': 'SPHERE',
            'mass': 2.1,
            'friction': 0.7,
        }
    },
    'Block': {
        'type': 'MESH',  # Cube
        'location': mathutils.Vector((1.0, 0.0, 8.0)),
        'rotation_euler': mathutils.Euler((math.radians(30.0), 0.0, 0.0), 'XYZ'),  # Rotated on X
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),  # Default scale
        'parent': None,
        'rigidbody_checks': {
            'enabled': True,
            'type': 'ACTIVE',
            'collision_shape': 'BOX',
            'mass': 5.1,
            'use_deactivation': True,
            'use_start_deactivated': True,
        }
    }
}

# Expected material data (Empty for this task)
EXPECTED_MATERIALS = {}

# Expected world settings (Empty for this task)
EXPECTED_WORLD = {}


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
    # Allow some flexibility in comparing Euler angles, maybe check quaternion distance if needed
    # For simple axis-aligned rotations, component check is usually okay
    # Consider potential gimbal lock issues if comparing complex rotations
    # Simple component check:
    return (math.isclose(e1.x, e2.x, abs_tol=tolerance_rad) and
            math.isclose(e1.y, e2.y, abs_tol=tolerance_rad) and
            math.isclose(e1.z, e2.z, abs_tol=tolerance_rad))


# --- Check Functions ---

def check_scene_settings(expected_settings):
    """ Checks Scene settings like render engine and device """
    errors = []
    scene = bpy.context.scene
    prefix = "Scene Settings:"

    if 'render_engine' in expected_settings and scene.render.engine != expected_settings['render_engine']:
        errors.append(
            f"{prefix} Expected render engine '{expected_settings['render_engine']}', found '{scene.render.engine}'.")
        # If engine is wrong, don't check engine-specific device settings
        return errors

    # Check Cycles device only if engine is Cycles
    if scene.render.engine == 'CYCLES':
        if 'cycles_device' in expected_settings and scene.cycles.device != expected_settings['cycles_device']:
            errors.append(
                f"{prefix} Expected Cycles device '{expected_settings['cycles_device']}', found '{scene.cycles.device}'.")

    return errors


def check_rigidbody_properties(obj, expected_rb_checks, prefix):
    """ Checks the Rigid Body properties of an object """
    errors = []
    rb = obj.rigid_body

    # Check basic rigid body properties
    if 'type' in expected_rb_checks and rb.type != expected_rb_checks['type']:
        errors.append(f"{prefix} Expected RB Type '{expected_rb_checks['type']}', found '{rb.type}'.")

    if 'collision_shape' in expected_rb_checks and rb.collision_shape != expected_rb_checks['collision_shape']:
        errors.append(
            f"{prefix} Expected RB Collision Shape '{expected_rb_checks['collision_shape']}', found '{rb.collision_shape}'.")

    # Check properties often relevant for ACTIVE type
    if rb.type == 'ACTIVE':
        if 'mass' in expected_rb_checks and not math.isclose(rb.mass, expected_rb_checks['mass'],
                                                             abs_tol=TOLERANCE_PROP):
            errors.append(f"{prefix} Expected RB Mass {expected_rb_checks['mass']:.2f}, found {rb.mass:.2f}.")
        if 'friction' in expected_rb_checks and not math.isclose(rb.friction, expected_rb_checks['friction'],
                                                                 abs_tol=TOLERANCE_PROP):
            errors.append(
                f"{prefix} Expected RB Friction {expected_rb_checks['friction']:.2f}, found {rb.friction:.2f}.")
        if 'use_deactivation' in expected_rb_checks and rb.use_deactivation != expected_rb_checks['use_deactivation']:
            errors.append(
                f"{prefix} Expected RB Deactivation Enabled: {expected_rb_checks['use_deactivation']}, found: {rb.use_deactivation}.")
        # Only check start deactivated if deactivation itself is enabled
        if rb.use_deactivation and 'use_start_deactivated' in expected_rb_checks and rb.use_start_deactivated != \
                expected_rb_checks['use_start_deactivated']:
            errors.append(
                f"{prefix} Expected RB Start Deactivated: {expected_rb_checks['use_start_deactivated']}, found: {rb.use_start_deactivated}.")

    # Add checks for other properties (Sensitivity, Bounciness, etc.) if needed

    return errors


def check_object_properties(obj_name, expected_props):
    """Checks object properties, including rigid body settings."""
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

    # --- Rigid Body Checks ---
    if 'rigidbody_checks' in expected_props:
        expected_rb_checks = expected_props['rigidbody_checks']
        if expected_rb_checks.get('enabled', False):  # Check if RB is expected
            if not obj.rigid_body:
                errors.append(f"{prefix} Rigid Body physics is not enabled.")
            else:
                # If RB exists, check its properties
                errors.extend(check_rigidbody_properties(obj, expected_rb_checks, prefix))
        elif obj.rigid_body:  # Check if RB is NOT expected but exists
            errors.append(f"{prefix} Rigid Body physics is enabled but was not expected.")

    # --- Material Assignment Check (If needed) ---
    if 'material' in expected_props:
        expected_mat_info = expected_props['material']
        slot_index = expected_mat_info['slot']
        expected_mat_name = expected_mat_info['name']
        if len(obj.material_slots) <= slot_index:
            errors.append(f"{prefix} No material slot {slot_index}.")
        elif not obj.material_slots[slot_index].material:
            errors.append(f"{prefix} Slot {slot_index} is empty.")
        elif obj.material_slots[slot_index].material.name != expected_mat_name:
            errors.append(
                f"{prefix} Slot {slot_index} expected '{expected_mat_name}', found '{obj.material_slots[slot_index].material.name}'.")

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

    # Check Objects (includes rigid body checks)
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
    result_file = os.path.join(result_dir, "tid_17_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


if __name__ == "__main__":
    run_checks()
