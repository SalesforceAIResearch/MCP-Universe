"""
Custom evaluator functions for MCPMark Filesystem tasks.

These functions adapt verification logic from mcpmark/tasks/filesystem/*/verify.py
into the MCP-Universe evaluator framework.

Argument conventions (per Evaluator.evaluate):
- compare_fn(x, value, op_args, context=...) is invoked as:
  - x: result from func-chain (first positional arg)
  - value: config.value (args[0])
  - op_args: config.op_args (args[1])
  - context: keyword-only in kwargs
"""
# pylint: disable=line-too-long,too-many-lines,import-outside-toplevel,duplicate-code

from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple
from mcpuniverse.evaluator.functions import compare_func


##################################################################################
# Desktop - Music Report
##################################################################################

@compare_func(name="mcpmark.filesystem.desktop.verify_music_report")
async def verify_music_report(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Music Report task.

    Adapted from: mcpmark/tasks/filesystem/desktop/music_report/verify.py

    Checks:
    - music_analysis_report.txt file exists in music/ folder
    - File has exactly 25 lines
    - Lines 1-20 contain songs with correct format (songname:popularity_score)
    - Songs are ranked by popularity score in descending order
    - All expected song names are present
    - Popularity scores match expected values
    - Lines 21-25 contain top 5 song names (no scores)
    - No extra content in the file
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.desktop.music_report.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# Desktop - Project Management
##################################################################################

@compare_func(name="mcpmark.filesystem.desktop.verify_project_management")
async def verify_project_management(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Project Management File Reorganization task.

    Adapted from: mcpmark/tasks/filesystem/desktop/project_management/verify.py

    Checks:
    - organized_projects directory exists
    - All required subdirectories exist
    - Python files moved to experiments/ml_projects
    - CSV files moved to experiments/data_analysis
    - Learning markdown files moved to learning/resources
    - Entertainment markdown files moved to personal/entertainment
    - Music collection markdown files moved to personal/collections
    - progress_tracking directory is empty
    - project_structure.md file exists
    - File counts are correct in each directory
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.desktop.project_management.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# Desktop - Timeline Extraction
##################################################################################

@compare_func(name="mcpmark.filesystem.desktop.verify_timeline_extraction")
async def verify_timeline_extraction(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Timeline Extraction task.

    Adapted from: mcpmark/tasks/filesystem/desktop/timeline_extraction/verify.py

    Checks:
    - timeline.txt file exists in main directory
    - File is readable
    - File has exactly 43 lines
    - Each line contains both file path and date (YYYY-MM-DD format)
    - All dates are in valid YYYY-MM-DD format
    - Dates are in chronological order
    - All expected entries from answer.txt are present
    - No duplicate entries
    - All referenced file paths exist
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.desktop.timeline_extraction.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# Desktop Template - Budget Computation
##################################################################################

@compare_func(name="mcpmark.filesystem.desktop_template.verify_budget_computation")
async def verify_budget_computation(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Budget Computation task.

    Adapted from: mcpmark/tasks/filesystem/desktop_template/budget_computation/verify.py

    Checks:
    - total_budget.txt file exists
    - File has proper format (file_path;price lines + total)
    - File contains exactly 15 expense entries + 1 total line
    - All expected file paths are present with correct counts
    - All individual prices match expected values
    - Total price is $95,624.46
    - Total matches the sum of individual expenses
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.desktop_template.budget_computation.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# Desktop Template - Contact Information
##################################################################################

@compare_func(name="mcpmark.filesystem.desktop_template.verify_contact_information")
async def verify_contact_information(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Contact Information Compilation task.

    Adapted from: mcpmark/tasks/filesystem/desktop_template/contact_information/verify.py

    Checks:
    - contact_info.csv file exists in main directory
    - answer.txt file exists in main directory
    - Files are in correct locations
    - CSV has correct structure (Name, Email, Phone columns)
    - CSV contains all 15 required entries with accurate data
    - All required names are present
    - answer.txt contains the correct answer about Charlie Davis (dentist)
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.desktop_template.contact_information.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# Desktop Template - File Arrangement
##################################################################################

@compare_func(name="mcpmark.filesystem.desktop_template.verify_file_arrangement")
async def verify_file_arrangement(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Desktop File Organization task.

    Adapted from: mcpmark/tasks/filesystem/desktop_template/file_arrangement/verify.py

    Checks:
    - All required folders exist (work, life, archives, temp, others)
    - Work folder contains 5 required files
    - Life folder contains 7 required files
    - Archives folder contains 4 required files
    - Temp folder contains 2 required files
    - Others folder exists
    - All 18 required files are in their correct designated folders
    - No duplicate required files across folders
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.desktop_template.file_arrangement.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# File Context - Duplicates Searching
##################################################################################

@compare_func(name="mcpmark.filesystem.file_context.verify_duplicates_searching")
async def verify_duplicates_searching(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the File Duplicates Detection and Organization task.

    Adapted from: mcpmark/tasks/filesystem/file_context/duplicates_searching/verify.py

    Checks:
    - duplicates directory exists
    - All 14 duplicate files moved to duplicates directory
    - All 6 unique files remain in original location
    - No duplicate files remain in original location
    - Content integrity verified (duplicate files have identical content)
    - Duplicates directory contains exactly 14 files
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.file_context.duplicates_searching.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# File Context - File Merging
##################################################################################

@compare_func(name="mcpmark.filesystem.file_context.verify_file_merging")
async def verify_file_merging(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the File Merging task.

    Adapted from: mcpmark/tasks/filesystem/file_context/file_merging/verify.py

    Checks:
    - merged_content.txt file exists
    - Correct 10 files selected (smallest files excluding file_12.txt)
    - Files are in alphabetical order
    - Each file section has proper filename header
    - All file contents preserved correctly
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.file_context.file_merging.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# File Context - File Splitting
##################################################################################

@compare_func(name="mcpmark.filesystem.file_context.verify_file_splitting")
async def verify_file_splitting(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the File Splitting task.

    Adapted from: mcpmark/tasks/filesystem/file_context/file_splitting/verify.py

    Checks:
    - split directory exists
    - All 10 split files exist with correct names (split_01.txt to split_10.txt)
    - All split files have equal character counts
    - Concatenated split files equal the original large_file.txt
    - No extra files in split directory
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.file_context.file_splitting.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# File Context - Pattern Matching
##################################################################################

@compare_func(name="mcpmark.filesystem.file_context.verify_pattern_matching")
async def verify_pattern_matching(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Pattern Matching task (find files with common substring).

    Adapted from: mcpmark/tasks/filesystem/file_context/pattern_matching/verify.py

    Checks:
    - answer.txt file exists
    - Answer format is correct (filename.txt,start_position)
    - All files mentioned in answer exist
    - All matches are at least 30 characters long
    - All matches are correct (verified against large_file.txt)
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.file_context.pattern_matching.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# File Context - Uppercase
##################################################################################

@compare_func(name="mcpmark.filesystem.file_context.verify_uppercase")
async def verify_uppercase(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Uppercase Conversion task.

    Adapted from: mcpmark/tasks/filesystem/file_context/uppercase/verify.py

    Checks:
    - uppercase directory exists
    - All 10 uppercase files exist (file_01.txt to file_10.txt)
    - All uppercase files contain correct uppercase content
    - answer.txt file exists in uppercase directory
    - Answer format is correct (filename:word_count)
    - All 10 files are included in answer
    - Word counts are correct
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.file_context.uppercase.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# File Property - Size Classification
##################################################################################

@compare_func(name="mcpmark.filesystem.file_property.verify_size_classification")
async def verify_size_classification(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the File Size Classification task.

    Adapted from: mcpmark/tasks/filesystem/file_property/size_classification/verify.py

    Checks:
    - Three directories exist: small_files, medium_files, large_files
    - All files are correctly classified by size
    - Small files: < 300 bytes
    - Medium files: 300-700 bytes (inclusive)
    - Large files: > 700 bytes
    - No files remain in root directory
    - Total file count is correct
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.file_property.size_classification.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# File Property - Time Classification
##################################################################################

@compare_func(name="mcpmark.filesystem.file_property.verify_time_classification")
async def verify_time_classification(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the File Organization by Creation Time task.

    Adapted from: mcpmark/tasks/filesystem/file_property/time_classification/verify.py

    Checks:
    - Correct directory structure exists (month/day)
    - Files are in correct month/day directories
    - metadata_analyse.txt files exist in each directory
    - Metadata content is correct (filename, month, day, year)
    - No files remain in root directory
    - Total file count is correct
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.file_property.time_classification.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# Folder Structure - Structure Analysis
##################################################################################

@compare_func(name="mcpmark.filesystem.folder_structure.verify_structure_analysis")
async def verify_structure_analysis(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Directory Structure Analysis task.

    Adapted from: mcpmark/tasks/filesystem/folder_structure/structure_analysis/verify.py

    Checks:
    - structure_analysis.txt file exists
    - File statistics are correct (69 files, 51 folders, ~58097 bytes)
    - Depth analysis is correct (depth = 7)
    - Deepest path exists
    - File type classification is correct (68 txt, 1 py)
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.folder_structure.structure_analysis.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# Folder Structure - Structure Mirror
##################################################################################

@compare_func(name="mcpmark.filesystem.folder_structure.verify_structure_mirror")
async def verify_structure_mirror(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Directory Structure Mirroring with Smart Placeholders task.

    Adapted from: mcpmark/tasks/filesystem/folder_structure/structure_mirror/verify.py

    Checks:
    - No file contents were copied
    - Mirror directory structure is complete
    - All expected directories exist
    - placeholder.txt files exist in correct directories
    - Placeholder content is correct
    - No unexpected directories exist
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.folder_structure.structure_mirror.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# Legal Document - Dispute Review
##################################################################################

@compare_func(name="mcpmark.filesystem.legal_document.verify_dispute_review")
async def verify_dispute_review(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Legal Document Dispute Review task.

    Adapted from: mcpmark/tasks/filesystem/legal_document/dispute_review/verify.py

    Checks:
    - dispute_review.txt file exists
    - Output format is correct (X.X:number)
    - Expected entries present with correct counts
    - Clause counts: 1.1:3, 1.3:3, 4.6:5 or 6, 4.16:5, 6.8:4
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.legal_document.dispute_review.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# Legal Document - Individual Comments
##################################################################################

@compare_func(name="mcpmark.filesystem.legal_document.verify_individual_comments")
async def verify_individual_comments(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Legal Document Individual Comments task.

    Adapted from: mcpmark/tasks/filesystem/legal_document/individual_comments/verify.py

    Checks:
    - individual_comment.csv file exists
    - CSV format is correct (7 columns)
    - CSV content matches expected data
    - 4 people with comment counts for 6 clauses
    - All data values are valid non-negative integers
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.legal_document.individual_comments.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# Legal Document - Solution Tracing
##################################################################################

@compare_func(name="mcpmark.filesystem.legal_document.verify_solution_tracing")
async def verify_solution_tracing(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Legal Document Solution Tracing task.

    Adapted from: mcpmark/tasks/filesystem/legal_document/solution_tracing/verify.py

    Checks:
    - tracing.csv file exists
    - CSV format is correct (5 columns)
    - CSV content matches expected data
    - Version numbers and author names are correct
    - All data values are accurate
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.legal_document.solution_tracing.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# Papers - Author Folders
##################################################################################

@compare_func(name="mcpmark.filesystem.papers.verify_author_folders")
async def verify_author_folders(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Paper Organization Task: Author-Based Paper Categorization.

    Adapted from: mcpmark/tasks/filesystem/papers/author_folders/verify.py

    Checks:
    - frequent_authors and 2025_authors directories exist
    - Authors with ≥4 papers have folders in frequent_authors
    - Authors with ≥3 papers in 2025 have folders in 2025_authors
    - Original HTML files remain intact
    - Author folder names follow correct naming convention (lowercase with underscores)
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.papers.author_folders.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# Papers - Find Math Paper
##################################################################################

@compare_func(name="mcpmark.filesystem.papers.verify_find_math_paper")
async def verify_find_math_paper(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Find Math Paper task.

    Adapted from: mcpmark/tasks/filesystem/papers/find_math_paper/verify.py

    Checks:
    - answer.html file exists
    - Original file (2407.01284.html) has been renamed
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.papers.find_math_paper.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# Papers - Organize Legacy Papers
##################################################################################

@compare_func(name="mcpmark.filesystem.papers.verify_organize_legacy_papers")
async def verify_organize_legacy_papers(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Papers Collection Cleanup and Organization task.

    Adapted from: mcpmark/tasks/filesystem/papers/organize_legacy_papers/verify.py

    Checks:
    - BibTeX file and 2024+ papers remain in original directory
    - Pre-2024 papers moved to organized/ directory by year
    - INDEX.md files exist in each year directory with correct format
    - Authors are correctly extracted (max 3 authors, use "et al." for >3)
    - SUMMARY.md file exists with correct content
    - Entries are sorted correctly
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.papers.organize_legacy_papers.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# Student Database - Duplicate Name
##################################################################################

@compare_func(name="mcpmark.filesystem.student_database.verify_duplicate_name")
async def verify_duplicate_name(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Student Database Task: Find Duplicate Names.

    Adapted from: mcpmark/tasks/filesystem/student_database/duplicate_name/verify.py

    Checks:
    - namesake.txt file exists
    - File format is correct (name, count, ids for each duplicate)
    - Exactly 16 duplicate names found
    - All student IDs match expected results
    - All counts are correct (2 for each duplicate name)
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.student_database.duplicate_name.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# Student Database - English Talent
##################################################################################

@compare_func(name="mcpmark.filesystem.student_database.verify_english_talent")
async def verify_english_talent(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Student Database Task: English Talent Recruitment.

    Adapted from: mcpmark/tasks/filesystem/student_database/english_talent/verify.py

    Checks:
    - qualified_students.txt file exists
    - File format is correct (name, id, email for each student)
    - Exactly 19 qualified students found
    - All expected students are present with correct details
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.student_database.english_talent.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# Student Database - Grade-Based Score
##################################################################################

@compare_func(name="mcpmark.filesystem.student_database.verify_gradebased_score")
async def verify_gradebased_score(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Student Database Grade-Based Score Analysis task.

    Adapted from: mcpmark/tasks/filesystem/student_database/gradebased_score/verify.py

    Checks:
    - grade_summary.txt file exists
    - File is readable
    - All three subjects (Chinese, Math, English) are present
    - Grade statistics are correct (A/B/C/D/F counts, pass/fail counts)
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.student_database.gradebased_score.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# ThreeStudio - Code Locating
##################################################################################

@compare_func(name="mcpmark.filesystem.threestudio.verify_code_locating")
async def verify_code_locating(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the ThreeStudio Task 1: Find Zero123 Guidance Implementation.

    Adapted from: mcpmark/tasks/filesystem/threestudio/code_locating/verify.py

    Checks:
    - answer.txt file exists
    - Answer format is correct (relative path, forward slashes)
    - File path structure is correct
    - Identified file actually exists
    - File contains Zero123 guidance implementation
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.threestudio.code_locating.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# ThreeStudio - Output Analysis
##################################################################################

@compare_func(name="mcpmark.filesystem.threestudio.verify_output_analysis")
async def verify_output_analysis(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the ThreeStudio Task 2: Analyze Zero123 Guidance Output Structure.

    Adapted from: mcpmark/tasks/filesystem/threestudio/output_analysis/verify.py

    Checks:
    - answer.txt file exists
    - All four required strings found (loss_sds, grad_norm, min_step, max_step)
    - Line numbers contain (323 or 324) and (327 or 328)
    - File path is threestudio/models/guidance/zero123_guidance.py
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.threestudio.output_analysis.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# ThreeStudio - Requirements Completion
##################################################################################

@compare_func(name="mcpmark.filesystem.threestudio.verify_requirements_completion")
async def verify_requirements_completion(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the ThreeStudio Task 3: Restore Zero123 Dependencies in Requirements.txt.

    Adapted from: mcpmark/tasks/filesystem/threestudio/requirements_completion/verify.py

    Checks:
    - requirements.txt file exists and is readable
    - All required dependencies present (einops, kornia, taming, openai, clip)
    - Specific dependency entries are correct
    - File format is valid
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.threestudio.requirements_completion.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# VoteNet - Dataset Comparison
##################################################################################

@compare_func(name="mcpmark.filesystem.votenet.verify_dataset_comparison")
async def verify_dataset_comparison(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the Votenet Dataset Comparison task.

    Adapted from: mcpmark/tasks/filesystem/votenet/dataset_comparison/verify.py

    Checks:
    - analysis.txt file exists in correct location
    - File format is correct (category blocks with counts)
    - All 10 required SUN RGB-D categories are present
    - Category counts match expected values
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.votenet.dataset_comparison.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# VoteNet - Debugging
##################################################################################

@compare_func(name="mcpmark.filesystem.votenet.verify_debugging")
async def verify_debugging(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the VoteNet Task: Debug Backbone Module.

    Adapted from: mcpmark/tasks/filesystem/votenet/debugging/verify.py

    Checks:
    - answer.txt file exists with correct file path
    - File path contains models/backbone_module.py
    - Bug has been fixed (mlp parameter changed from [256,256,256] to [512,256,256] or [256+256,256,256])
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.votenet.debugging.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg


##################################################################################
# VoteNet - Requirements Writing
##################################################################################

@compare_func(name="mcpmark.filesystem.votenet.verify_requirements_writing")
async def verify_requirements_writing(_x: dict, *_args, **kwargs) -> Tuple[bool, str]:
    """
    Verify the VoteNet Task: Create Requirements.txt File.

    Adapted from: mcpmark/tasks/filesystem/votenet/requirements_writing/verify.py

    Checks:
    - requirements.txt file exists and is readable
    - All required dependencies present (matplotlib, opencv, plyfile, trimesh, pointnet2, networkx)
    - File format is valid
    - No duplicate entries
    """
    from mcpuniverse.evaluator.mcpmark.filesystem.votenet.requirements_writing.verify import verify

    # Get the test directory from context or environment
    context = kwargs.get("context")
    if context:
        test_root = context.get_env("FILESYSTEM_TEST_DIR")
    else:
        test_root = os.environ.get("FILESYSTEM_TEST_DIR")

    if not test_root:
        return False, "FILESYSTEM_TEST_DIR not set. Run prepare function 'download_filesystem_environment' first."

    test_dir = Path(test_root)

    # Call the verify function
    passed, error_msg = verify(test_dir)
    return passed, error_msg
