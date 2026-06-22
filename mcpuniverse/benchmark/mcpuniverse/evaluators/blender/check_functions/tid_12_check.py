# pylint: disable=import-error, missing-module-docstring, missing-function-docstring, line-too-long, too-many-branches, too-many-locals, too-many-statements
import math
import os
import json
from pathlib import Path

import bpy
import mathutils


# Helper for float comparison
def compare_float(val1, val2, tolerance=1e-5):
    return abs(val1 - val2) < tolerance


# Helper for color comparison (ignores alpha if expected_color has 3 components)
def compare_color(actual_color, expected_color, tolerance=1e-5):
    if len(expected_color) == 3:  # RGB comparison
        if len(actual_color) < 3:
            return False
        for i in range(3):
            if not compare_float(actual_color[i], expected_color[i], tolerance):
                return False
        return True
    elif len(expected_color) == 4:  # RGBA comparison
        if len(actual_color) != 4:
            return False
        for i in range(4):
            if not compare_float(actual_color[i], expected_color[i], tolerance):
                return False
        return True
    return False


def run_scene_checks():
    errors = []
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    world = scene.world

    # --- 1. Render Engine and Device ---
    expected_engine = 'CYCLES'
    if scene.render.engine != expected_engine:
        errors.append(f"Render Engine: Expected '{expected_engine}', found '{scene.render.engine}'.")
    else:
        # Only check Cycles device if engine is Cycles
        expected_cycles_device = 'CPU'
        if scene.cycles.device != expected_cycles_device:
            errors.append(f"Cycles Device: Expected '{expected_cycles_device}', found '{scene.cycles.device}'.")

    # --- 2. Sampling Settings (Cycles) ---
    if scene.render.engine == 'CYCLES':
        # Viewport Denoising
        if not scene.cycles.use_preview_denoising:
            errors.append("Viewport Denoising: Expected True, found False.")
        expected_vp_denoiser = 'OPENIMAGEDENOISE'
        if scene.cycles.preview_denoiser != expected_vp_denoiser:
            errors.append(
                f"Viewport Denoiser: Expected '{expected_vp_denoiser}', found '{scene.cycles.preview_denoiser}'.")

        # Render Denoising
        if not scene.cycles.use_denoising:
            errors.append("Render Denoising: Expected True, found False.")
        expected_render_denoiser = 'OPENIMAGEDENOISE'
        if scene.cycles.denoiser != expected_render_denoiser:
            errors.append(f"Render Denoiser: Expected '{expected_render_denoiser}', found '{scene.cycles.denoiser}'.")

        # Samples
        expected_render_samples = 512
        if scene.cycles.samples != expected_render_samples:
            errors.append(f"Render Samples: Expected {expected_render_samples}, found {scene.cycles.samples}.")

        expected_viewport_samples = 128
        if scene.cycles.preview_samples != expected_viewport_samples:
            errors.append(
                f"Viewport Samples: Expected {expected_viewport_samples}, found {scene.cycles.preview_samples}.")
    else:
        errors.append("Skipping Cycles sampling checks as render engine is not Cycles.")

    # --- 3. Output Resolution ---
    expected_res_x = 1350
    if scene.render.resolution_x != expected_res_x:
        errors.append(f"Resolution X: Expected {expected_res_x}, found {scene.render.resolution_x}.")

    expected_res_y = 1080
    if scene.render.resolution_y != expected_res_y:
        errors.append(f"Resolution Y: Expected {expected_res_y}, found {scene.render.resolution_y}.")

    expected_res_scale = 85
    if scene.render.resolution_percentage != expected_res_scale:
        errors.append(f"Resolution Scale: Expected {expected_res_scale}%, found {scene.render.resolution_percentage}%.")

    # --- 4. Color Management ---
    expected_view_transform = 'Filmic'
    if scene.view_settings.view_transform != expected_view_transform:
        errors.append(
            f"View Transform: Expected '{expected_view_transform}', found '{scene.view_settings.view_transform}'.")

    expected_look = 'Filmic - High Contrast'  # Blender often prepends the transform name
    if scene.view_settings.look != expected_look:
        # Fallback if "Filmic - " is not prepended by user's Blender version/config for some reason
        if scene.view_settings.look == 'High Contrast' and scene.view_settings.view_transform == 'Filmic':
            pass  # This is acceptable
        else:
            errors.append(
                f"Look: Expected '{expected_look}' (or 'High Contrast' under Filmic), found '{scene.view_settings.look}'.")

    expected_gamma = 1.2
    if not compare_float(scene.view_settings.gamma, expected_gamma):
        errors.append(f"Gamma: Expected {expected_gamma}, found {scene.view_settings.gamma:.3f}.")

    # --- 5. Render Layers Properties (View Layer Passes) ---
    if not view_layer.use_pass_z:
        errors.append("Z Pass: Expected True, found False.")
    if not view_layer.use_pass_mist:
        errors.append("Mist Pass: Expected True, found False.")
    if not view_layer.use_pass_normal:
        errors.append("Normal Pass: Expected True, found False.")

    # --- 6. World Settings ---
    if not world:
        errors.append("World Settings: No World found in the scene.")
    else:
        # Background Color
        expected_bg_color = (0.8, 0.8, 0.8)
        if world.use_nodes:
            bg_node = None
            if world.node_tree:  # Ensure node_tree exists
                for node in world.node_tree.nodes:
                    if node.type == 'BACKGROUND':
                        bg_node = node
                        break
            if bg_node and "Color" in bg_node.inputs:
                actual_color = bg_node.inputs["Color"].default_value
                if compare_color(actual_color, expected_bg_color):
                    pass
                else:
                    errors.append(
                        f"World Background Color (Node): Expected {expected_bg_color}, found ({actual_color[0]:.3f}, {actual_color[1]:.3f}, {actual_color[2]:.3f}).")
            else:
                errors.append(
                    "World Background Color: World uses nodes, but no Background node with 'Color' input found or node_tree is missing.")
        else:  # Check simple world color if not using nodes
            actual_color = world.color
            if compare_color(actual_color, expected_bg_color):
                pass
            else:
                errors.append(
                    f"World Background Color (Non-Node): Expected {expected_bg_color}, found ({actual_color[0]:.3f}, {actual_color[1]:.3f}, {actual_color[2]:.3f}).")

    # --- 7. Output Properties (File Format) ---
    expected_file_format = 'OPEN_EXR_MULTILAYER'
    if scene.render.image_settings.file_format != expected_file_format:
        errors.append(
            f"File Format: Expected '{expected_file_format}', found '{scene.render.image_settings.file_format}'.")
    else:
        # Only check EXR specific settings if format is OPEN_EXR_MULTILAYER
        expected_exr_codec = 'ZIP'  # ZIPS (single line) or ZIP (multi-line zlib)
        if scene.render.image_settings.exr_codec != expected_exr_codec:
            errors.append(
                f"OpenEXR Codec: Expected '{expected_exr_codec}' (Zlib), found '{scene.render.image_settings.exr_codec}'.")

        expected_color_depth = '32'  # 32-bit float
        if scene.render.image_settings.color_depth != expected_color_depth:
            errors.append(
                f"Output Color Depth (OpenEXR): Expected '{expected_color_depth}' (32-bit float), found '{scene.render.image_settings.color_depth}'.")

    # --- Final Report ---
    print("\n--- Scene Settings Validation Summary ---")
    if not errors:
        print("Validation Successful! All checks passed.")
        result = {
            "pass": True,
            "reason": ""
        }
    else:
        print("Validation Failed. Errors found:")
        for error in errors:
            print(f"- {error}")
        result = {
            "pass": False,
            "reason": "; ".join(errors)
        }

    # Save results to JSON file
    parent_dir = str(Path(__file__).parent.parent)
    result_dir = f"{parent_dir}/evaluated_results"
    os.makedirs(result_dir, exist_ok=True)
    result_file = os.path.join(result_dir, "tid_12_results.json")

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f)

    print(f"Results saved to {result_file}")
    print("--- Validation Finished ---")


if __name__ == "__main__":
    run_scene_checks()
