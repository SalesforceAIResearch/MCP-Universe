import os
import json
from pathlib import Path

import bpy
import mathutils

# --- Configuration ---
# Tolerance for comparing floating point numbers (locations, scales, dimensions)
TOLERANCE = 1e-5

# Expected object data
EXPECTED_OBJECTS = {
    'Floor': {
        'type': 'MESH',
        'location': None,  # Location wasn't specified, only scale
        'scale': mathutils.Vector((5.0, 5.0, 5.0)),
    },
    'Pillar': {
        'type': 'MESH',
        'location': mathutils.Vector((-2.0, -2.0, 2.0)),
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),  # Assuming default scale
        'dimensions': mathutils.Vector((1.0, 1.0, 4.0)),  # Radius 0.5 -> Diameter 1.0, Depth 4.0
        # Note: Checking exact vertex count *at creation* is tricky.
        # A default Blender cylinder with 16 'vertices' (sides)
        # usually has 32 total vertices (top/bottom rings).
        # We'll check for 32 vertices assuming default caps were used.
        # Adjust if different caps were intended.
        'expected_verts': 32,
    },
    'Ball': {
        'type': 'MESH',
        'location': mathutils.Vector((2.0, 2.0, 5.0)),
        'scale': mathutils.Vector((1.0, 1.0, 1.0)),  # Assuming default scale
        # UV Sphere: 32 segments, 16 rings
        # Vertices = (segments * (rings - 1)) + 2 poles = (32 * (16 - 1)) + 2 = 482
        # Faces (polygons) = segments * rings = 32 * 16 = 512
        'expected_verts': 482,
        'expected_faces': 512,
        'constraint': {'type': 'TRACK_TO', 'target': 'ControlTarget'}
    },
    'ControlTarget': {
        'type': 'EMPTY',
        'location': mathutils.Vector((0.0, 0.0, 3.0)),
        'empty_type': 'ARROWS',
    },
    'Camera': {
        'type': 'CAMERA',
        'location': mathutils.Vector((0.0, -8.0, 3.0)),
        # Check if it's looking at Pillar via a constraint
        'constraint': {'type': 'TRACK_TO', 'target': 'Pillar'}
    }
}


# --- Helper Functions ---

def vector_compare(v1, v2, tolerance):
    """Compares two vectors within a given tolerance."""
    return (v1 - v2).length < tolerance


def check_object_properties(obj_name, expected_props):
    """Checks existence, type, location, scale, dimensions, etc."""
    errors = []
    obj = bpy.data.objects.get(obj_name)

    if not obj:
        errors.append(f"Object '{obj_name}' not found.")
        return errors  # Cannot perform further checks

    # Check Type
    if obj.type != expected_props['type']:
        errors.append(f"Object '{obj_name}': Expected type '{expected_props['type']}', found '{obj.type}'.")
        # Don't return yet, maybe other checks are still relevant

    # Check Location
    if 'location' in expected_props and expected_props['location'] is not None:
        if not vector_compare(obj.location, expected_props['location'], TOLERANCE):
            errors.append(
                f"Object '{obj_name}': Expected location {expected_props['location']}, found {obj.location.to_tuple(3)}.")

    # Check Scale
    if 'scale' in expected_props and expected_props['scale'] is not None:
        if not vector_compare(obj.scale, expected_props['scale'], TOLERANCE):
            # Round scale for clearer error messages
            found_scale_rounded = tuple(round(s, 3) for s in obj.scale)
            errors.append(
                f"Object '{obj_name}': Expected scale {expected_props['scale'].to_tuple(3)}, found {found_scale_rounded}.")

    # Check Dimensions (only makes sense for MESH and assumes scale is (1,1,1))
    if 'dimensions' in expected_props and expected_props['dimensions'] is not None:
        # Ensure scale is close to 1 before checking dimensions directly
        if vector_compare(obj.scale, mathutils.Vector((1.0, 1.0, 1.0)), TOLERANCE):
            if not vector_compare(obj.dimensions, expected_props['dimensions'], TOLERANCE):
                found_dims_rounded = tuple(round(d, 3) for d in obj.dimensions)
                errors.append(
                    f"Object '{obj_name}': Expected dimensions {expected_props['dimensions'].to_tuple(3)}, found {found_dims_rounded}.")
        else:
            errors.append(
                f"Object '{obj_name}': Cannot accurately check dimensions because scale is not (1,1,1). Found scale: {obj.scale.to_tuple(3)}")

    # Check Mesh Vertices/Faces (only for MESH)
    if obj.type == 'MESH':
        if 'expected_verts' in expected_props:
            if len(obj.data.vertices) != expected_props['expected_verts']:
                errors.append(
                    f"Object '{obj_name}': Expected {expected_props['expected_verts']} vertices, found {len(obj.data.vertices)}.")
        if 'expected_faces' in expected_props:
            if len(obj.data.polygons) != expected_props['expected_faces']:
                errors.append(
                    f"Object '{obj_name}': Expected {expected_props['expected_faces']} faces, found {len(obj.data.polygons)}.")

    # Check Empty Type (only for EMPTY)
    if obj.type == 'EMPTY':
        if 'empty_type' in expected_props:
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
                f"Object '{obj_name}': Constraint check failed because target object '{expected_constraint['target']}' not found.")
        else:
            for constraint in obj.constraints:
                if constraint.type == expected_constraint['type']:
                    if hasattr(constraint, 'target') and constraint.target == target_obj:
                        found_constraint = True
                        break  # Found the correct constraint
            if not found_constraint:
                errors.append(
                    f"Object '{obj_name}': Expected constraint '{expected_constraint['type']}' targeting '{expected_constraint['target']}' not found or incorrect.")

    return errors


# --- Main Execution ---
def run_checks():
    print("--- Starting Blender Scene Validation ---")
    all_errors = []

    # Check each defined object
    for obj_name, props in EXPECTED_OBJECTS.items():
        print(f"Checking '{obj_name}'...")
        errors = check_object_properties(obj_name, props)
        if errors:
            all_errors.extend(errors)
        else:
            print(f" -> '{obj_name}' checks passed.")

    # Final Report
    print("\n--- Validation Summary ---")

    # Prepare the result dictionary
    result = {}
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
    result_file = os.path.join(result_dir, "tid_1_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


# Run the checks when the script is executed
if __name__ == "__main__":
    run_checks()
