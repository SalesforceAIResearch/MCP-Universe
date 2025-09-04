"""
Evaluation functions for Blender tasks.

This module provides evaluation functions for validating Blender scene files
and their content against expected specifications.
"""
# pylint: disable=broad-exception-caught, too-many-return-statements, unused-argument
import os
import json
import subprocess
from pathlib import Path
from typing import Tuple
from mcpuniverse.evaluator.functions import compare_func

PARENT_DIR = str(Path(__file__).parent)


##################################################################################
# Utility Functions for Blender
##################################################################################

async def blender__check_file_exists(path: str) -> bool:
    """
    Check whether the specified Blender file exists.
    
    Args:
        path: Relative path to the Blender file within the blend_files directory
        
    Returns:
        bool: True if the file exists, False otherwise
    """
    file_path = os.path.join(PARENT_DIR, "blend_files", path)
    return os.path.exists(file_path)


async def blender__check_file_content(path: str, task_id: str) -> Tuple[bool, str]:
    """
    Validate the content of a Blender file against expected specifications.
    
    Args:
        path: Relative path to the Blender file within the blend_files directory
        task_id: Identifier for the task being validated
        
    Returns:
        Tuple[bool, str]: (success_status, error_message)
            - success_status: True if validation passes, False otherwise
            - error_message: Description of validation errors, empty string if successful
    """
    blend_file_path = os.path.join(PARENT_DIR, "blend_files", path)
    check_script_path = os.path.join(PARENT_DIR, "check_functions", f"tid_{task_id}_check.py")

    if not os.path.exists(blend_file_path):
        return False, f"Blender file not found: {blend_file_path}"

    if not os.path.exists(check_script_path):
        return False, f"Validation script not found: {check_script_path}"

    blender_executable = os.environ.get('BLENDER_APP_PATH')
    if not blender_executable:
        return False, "BLENDER_APP_PATH environment variable not set"

    cmd = [
        blender_executable,
        "--background",
        blend_file_path,
        "--python",
        check_script_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)

        if result.returncode != 0:
            return False, f"Blender validation script failed: {result.stderr}"

        result_file_path = os.path.join(
            PARENT_DIR, "evaluated_results", f"tid_{task_id}_results.json"
        )

        if not os.path.exists(result_file_path):
            return False, "Validation results file not generated"

        with open(result_file_path, "r", encoding="utf-8") as f:
            validation_result = json.load(f)

        return (
            validation_result.get("pass", False),
            validation_result.get("reason", "Unknown error")
        )

    except subprocess.TimeoutExpired:
        return False, "Blender validation script timed out"
    except json.JSONDecodeError as e:
        return False, f"Failed to parse validation results: {str(e)}"
    except Exception as e:
        return False, f"Unexpected error during validation: {str(e)}"


async def blender__remove_files(blender_path: str, result_path: str) -> None:
    """
    Remove Blender blend files and associated result files.
    
    Args:
        blender_path: Path to the Blender file relative to blend_files directory
        result_path: Path to the result file relative to evaluated_results directory
    
    Note:
        This function silently handles file removal failures to ensure cleanup
        operations don't interrupt the evaluation workflow.
    """
    blend_files_dir = os.path.join(PARENT_DIR, "blend_files")
    if os.path.exists(blend_files_dir):
        for filename in os.listdir(blend_files_dir):
            # Check if "blend" is in the filename (case-insensitive)
            if "blend" in filename.lower():
                file_to_remove = os.path.join(blend_files_dir, filename)
                if os.path.isfile(file_to_remove): # Ensure it's a file before attempting to remove
                    try:
                        os.remove(file_to_remove)
                    except OSError:
                        # Silently handle file removal failures to avoid interrupting workflow
                        pass

    result_file_path = os.path.join(PARENT_DIR, "evaluated_results", result_path)
    if os.path.exists(result_file_path):
        try:
            os.remove(result_file_path)
        except OSError:
            # Silently handle file removal failures to avoid interrupting workflow
            pass

##################################################################################
# Evaluation Functions
##################################################################################

@compare_func(name="blender.check_file")
async def blender_check_file(x: dict, *args, **kwargs) -> Tuple[bool, str]:
    """
    Evaluate whether the specified Blender file exists.
    
    Args:
        x: Input data dictionary (unused in this function)
        *args: Variable arguments containing operation arguments
        **kwargs: Additional keyword arguments
        
    Returns:
        Tuple[bool, str]: (success_status, error_message)
            - success_status: True if file exists, False otherwise
            - error_message: Description of the error, empty string if successful
    """
    _, op_args = args
    path = op_args["path"]
    task_id = op_args["task_id"]

    file_exists = await blender__check_file_exists(path)

    if file_exists:
        return True, ""

    return False, f"Blender file for task {task_id} does not exist"


@compare_func(name="blender.check_file_content")
async def blender_check_file_content(x: dict, *args, **kwargs) -> Tuple[bool, str]:
    """
    Evaluate whether the Blender file content meets the specified requirements.
    
    Args:
        x: Input data dictionary (unused in this function)
        *args: Variable arguments containing operation arguments
        **kwargs: Additional keyword arguments
        
    Returns:
        Tuple[bool, str]: (success_status, error_message)
            - success_status: True if content validation passes, False otherwise
            - error_message: Description of validation errors, empty string if successful
    """
    _, op_args = args
    path = op_args["path"]
    task_id = op_args["task_id"]

    # First check if the file exists
    file_exists = await blender__check_file_exists(path)
    if not file_exists:
        return False, f"Blender file for task {task_id} does not exist"

    # Validate the file content
    content_valid, error_message = await blender__check_file_content(path, task_id)

    # Clean up temporary files
    await blender__remove_files(path, f"tid_{task_id}_results.json")

    if not content_valid:
        return False, error_message

    return True, ""
