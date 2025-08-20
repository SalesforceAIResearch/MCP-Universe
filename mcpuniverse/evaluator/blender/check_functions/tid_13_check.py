# pylint: disable=import-error, missing-module-docstring, missing-function-docstring, line-too-long, too-many-branches, too-many-locals, too-many-statements
import os
import json
import math
from pathlib import Path

import bpy

# --- Configuration ---
# Tolerances
TOLERANCE_FLOAT = 1e-5  # For general float comparison (e.g., compression level)
# TOLERANCE_PROP = 1e-4 # Less critical here, use FLOAT

# Expected scene settings for Output, Color Management, and Metadata
EXPECTED_SCENE_SETTINGS = {
    # Output Format & Settings
    'image_format': 'OPEN_EXR_MULTILAYER',
    'image_exr_codec': 'DWAA',  # Conditional Check: Only if format is EXR
    'image_dwa_compression_level': 3.0,  # Conditional Check: Only if codec is DWAA
    'image_color_depth': '16',  # 'Float (Half)'

    # Color Management Settings
    'view_transform': 'Filmic',
    'look': 'Medium High Contrast',  # Depends on view_transform being Filmic

    # Metadata Stamp Settings
    'use_stamp_note': True,
    'stamp_note_text': 'Benchmark Test Run',  # Conditional Check: Only if use_stamp_note is True
}

# Expected object data (Empty for this task)
EXPECTED_OBJECTS = {}

# Expected material data (Empty for this task)
EXPECTED_MATERIALS = {}

# Expected world settings (Empty for this task)
EXPECTED_WORLD = {}


# --- Check Functions ---

def check_scene_settings(expected_settings):
    """ Checks Render Output, Color Management, and Metadata settings """
    errors = []
    scene = bpy.context.scene
    render = scene.render
    image_settings = render.image_settings
    view_settings = scene.view_settings
    prefix = "Scene Settings:"

    # 1. Output Format & Settings
    format_ok = False
    if 'image_format' in expected_settings:
        if image_settings.file_format != expected_settings['image_format']:
            errors.append(
                f"{prefix} Expected Output Format '{expected_settings['image_format']}', found '{image_settings.file_format}'.")
        else:
            format_ok = True  # Format matches, proceed to codec/depth checks

    # Only check EXR specific settings if format is correct (or assumed EXR variant)
    is_exr_format = image_settings.file_format in ['OPEN_EXR', 'OPEN_EXR_MULTILAYER']
    if format_ok and is_exr_format:
        codec_ok = False
        if 'image_exr_codec' in expected_settings:
            if image_settings.exr_codec != expected_settings['image_exr_codec']:
                errors.append(
                    f"{prefix} Expected EXR Codec '{expected_settings['image_exr_codec']}', found '{image_settings.exr_codec}'.")
            else:
                codec_ok = True

        # Only check DWA level if codec is DWAA
        if codec_ok and image_settings.exr_codec == 'DWAA':
            if 'image_dwa_compression_level' in expected_settings:
                expected_level = expected_settings['image_dwa_compression_level']
                if not math.isclose(image_settings.compression, expected_level, abs_tol=TOLERANCE_FLOAT):
                    errors.append(
                        f"{prefix} Expected DWA Compression Level {expected_level}, found {image_settings.compression:.2f}.")

        # Check Color Depth (relevant for EXR)
        if 'image_color_depth' in expected_settings:
            if image_settings.color_depth != expected_settings['image_color_depth']:
                errors.append(
                    f"{prefix} Expected Color Depth '{expected_settings['image_color_depth']}' (Float Half), found '{image_settings.color_depth}'.")

    elif 'image_exr_codec' in expected_settings or 'image_color_depth' in expected_settings:
        # Log if we expected to check EXR settings but format didn't match
        if not is_exr_format:
            errors.append(
                f"{prefix} Cannot check EXR Codec/Depth, Output Format is not EXR ('{image_settings.file_format}').")

    # 2. Color Management Settings
    if 'view_transform' in expected_settings:
        if view_settings.view_transform != expected_settings['view_transform']:
            errors.append(
                f"{prefix} Expected View Transform '{expected_settings['view_transform']}', found '{view_settings.view_transform}'.")
        # Only check Look if View Transform matches (as Looks are dependent)
        elif view_settings.view_transform == expected_settings['view_transform'] and 'look' in expected_settings:
            if view_settings.look != expected_settings['look']:
                errors.append(f"{prefix} Expected Look '{expected_settings['look']}', found '{view_settings.look}'.")

    # 3. Metadata Stamp Settings
    if 'use_stamp_note' in expected_settings:
        if render.use_stamp_note != expected_settings['use_stamp_note']:
            errors.append(
                f"{prefix} Expected Use Stamp Note: {expected_settings['use_stamp_note']}, found: {render.use_stamp_note}.")
        # Only check text if stamp note is expected to be enabled
        elif expected_settings['use_stamp_note'] and 'stamp_note_text' in expected_settings:
            if render.stamp_note_text != expected_settings['stamp_note_text']:
                errors.append(
                    f"{prefix} Expected Stamp Note Text '{expected_settings['stamp_note_text']}', found '{render.stamp_note_text}'.")

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
    result_file = os.path.join(result_dir, "tid_13_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


if __name__ == "__main__":
    run_checks()
