"""
Core logic for downloading and transforming Deep Research benchmarks to the
benchmark task JSON format. Supports gaia-benchmark/GAIA, cais/hle, and
smolagents/browse_comp.
"""

import base64
import hashlib
import json
import urllib.request
from datetime import datetime
from pathlib import Path

from datasets import load_dataset


def build_task_config(
    question,
    correct_answer,
    tools,
    output_format=True,
    evaluator_op="deepresearch.hle_llm_as_a_judge",
):
    """
    Build a common task configuration structure.

    Args:
        question: The question text
        correct_answer: The correct answer text
        tools: List of tool names to use
        output_format: Whether to include output_format in the config
        evaluator_op: The evaluator operation to use

    Returns:
        dict: Task configuration
    """
    if tools is None:
        tools = ["serper-search", "jina-scrape-llm-summary"]
    result = {
        "category": "general",
        "question": question,
        "output_format": {
            "answer": "[Your answer]"
        },
        "use_specified_server": True,
        "mcp_servers": [{"name": tool} for tool in tools],
        "evaluators": [
            {
                "func": "raw",
                "op": evaluator_op,
                "op_args": {
                    "question": question,
                    "correct_answer": correct_answer
                }
            }
        ]
    }
    if not output_format:
        result.pop("output_format")
    return result


def get_output_dir(base_name, special_name=None, use_date=False):
    """
    Create and return output directory path.

    Args:
        base_name: Base name for the directory
        special_name: Optional special name to include
        use_date: Whether to append date to directory name

    Returns:
        Path: Output directory path
    """
    dir_name = base_name

    if special_name:
        dir_name = f"{base_name}_{special_name}"

    if use_date:
        today_str = datetime.now().strftime("%Y_%m_%d")
        dir_name = f"{dir_name}_{today_str}"

    output_dir = Path(f"mcpuniverse/benchmark/deepresearch/task_configs/{dir_name}")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def save_task_json(task_config, filename):
    """
    Save task configuration to JSON file.

    Args:
        task_config: Task configuration dict
        filename: Path to save the file
    """
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(task_config, f, indent=4, ensure_ascii=False)


def derive_key(password: str, length: int) -> bytes:
    """
    Derive a fixed-length key from the password using SHA256.

    Args:
        password: The password (canary string) to derive the key from
        length: The desired key length in bytes

    Returns:
        bytes: The derived key of the specified length
    """
    hasher = hashlib.sha256()
    hasher.update(password.encode())
    key = hasher.digest()
    return key * (length // len(key)) + key[: length % len(key)]


def decode_with_canary(encrypted_text, canary):
    """
    Decrypt base64-encoded ciphertext with XOR using a canary-derived key.

    Args:
        encrypted_text: The base64-encoded encrypted text
        canary: The canary string (password) used for decryption

    Returns:
        str: Decrypted text
    """
    if not encrypted_text or not canary:
        return encrypted_text

    try:
        encrypted = base64.b64decode(encrypted_text)
        key = derive_key(canary, len(encrypted))
        decrypted = bytes(a ^ b for a, b in zip(encrypted, key))
        return decrypted.decode('utf-8')
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Warning: Failed to decode with canary: {e}")
        return encrypted_text


def get_webtinker_task_ids():
    """
    Fetch the dev.json file from WebThinker repository and extract all task_ids.

    Returns:
        set or None: Set of task_id strings, or None on failure
    """
    dev_json_url = (
        "https://raw.githubusercontent.com/RUC-NLPIR/WebThinker/main/data/GAIA/dev.json"
    )

    try:
        print(f"Fetching task_ids from WebThinker dev.json: {dev_json_url}")
        with urllib.request.urlopen(dev_json_url) as response:
            dev_data = json.loads(response.read().decode('utf-8'))

        task_ids = {entry.get("task_id") for entry in dev_data if entry.get("task_id")}
        print(f"Found {len(task_ids)} unique task_ids in WebThinker dev.json")
        return task_ids
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Warning: Failed to fetch WebThinker dev.json: {e}")
        print("Proceeding without task_id filtering")
        return None


def process_gaia_dataset(tools=None, special_name=None, output_format=True):
    """Process GAIA dataset (validation split)."""
    split = "validation"
    print(f"Downloading GAIA {split} dataset from Hugging Face...")

    try:
        print(f"Loading GAIA {split} dataset...")
        ds = load_dataset("gaia-benchmark/GAIA", "2023_all", split=split)
        print(f"Successfully loaded {len(ds)} {split} examples")
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Error loading dataset: {e}")
        print("Make sure you have accepted the dataset terms on Hugging Face:")
        print("https://huggingface.co/datasets/gaia-benchmark/GAIA")
        print("You may need to login: huggingface-cli login")
        return

    webtinker_task_ids = get_webtinker_task_ids()
    if webtinker_task_ids is not None:
        initial_count = len(ds)
        ds = ds.filter(lambda example: example.get("task_id") in webtinker_task_ids)
        print(
            f"Filtered to {len(ds)} GAIA {split} examples with task_ids from WebThinker "
            f"dev.json (out of {initial_count} text-only examples)"
        )
    else:
        print(f"Using all {len(ds)} GAIA {split} examples (text-only) without task_id filtering")

    output_dir = get_output_dir(base_name="gaia_val_text_only", special_name=special_name, use_date=False)
    start_index = 1

    print(f"Starting task numbering from {start_index:04d}")
    print(f"Transforming {len(ds)} GAIA {split} examples...")

    transformed_count = 0
    effective_tools = tools if tools is not None else ["serper-search", "jina-scrape-llm-summary"]
    for idx, item in enumerate(ds):
        try:
            question = item.get("Question", "")
            correct_answer = item.get("Final answer", "")
            task_config = build_task_config(
                question, correct_answer, effective_tools, output_format=output_format
            )
            task_number = start_index + idx
            filename = output_dir / (
                f"gaia_{split}_{special_name}_{task_number:04d}.json"
                if special_name
                else f"gaia_{split}_{task_number:04d}.json"
            )
            save_task_json(task_config, filename)
            transformed_count += 1
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Error transforming item {idx} (task_id: {item.get('task_id', 'unknown')}): {e}")

    print("\nGAIA transformation complete!")
    print(f"Successfully transformed {transformed_count} out of {len(ds)} examples")
    print(f"Files saved to: {output_dir}")


def process_hle_dataset(tools=None, special_name=None, output_format=True):
    """Process cais/hle dataset - test split, non-multi-modal only."""
    print("Downloading cais/hle test dataset from Hugging Face...")

    try:
        print("Loading cais/hle test dataset...")
        ds = load_dataset("cais/hle", split="test")
        print(f"Successfully loaded {len(ds)} test examples")

        print("Filtering for non-multi-modal entries (no images)...")
        ds_filtered = ds.filter(lambda example: not example.get("image"))
        print(f"Found {len(ds_filtered)} non-multi-modal examples (out of {len(ds)} total)")

    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Error loading dataset: {e}")
        print("Make sure you have accepted the dataset terms on Hugging Face:")
        print("https://huggingface.co/datasets/cais/hle")
        print("You may need to login: huggingface-cli login")
        return

    output_dir = get_output_dir(base_name="hle_text_only", special_name=special_name, use_date=False)
    start_index = 1

    print(f"Starting task numbering from {start_index:04d}")
    print(f"Transforming {len(ds_filtered)} cais/hle test examples (non-multi-modal)...")

    transformed_count = 0
    effective_tools = tools if tools is not None else ["serper-search", "jina-scrape-llm-summary"]
    for idx, item in enumerate(ds_filtered):
        try:
            question = item.get("question", item.get("prompt", ""))
            correct_answer = item.get("answer", item.get("ground_truth", ""))
            task_config = build_task_config(
                question, correct_answer, effective_tools, output_format=output_format
            )
            task_number = start_index + idx
            filename = output_dir / (
                f"hle_test_{special_name}_{task_number:04d}.json"
                if special_name
                else f"hle_test_{task_number:04d}.json"
            )
            save_task_json(task_config, filename)
            transformed_count += 1
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(
                f"Error transforming item {idx} "
                f"(task_id: {item.get('task_id', item.get('id', 'unknown'))}): {e}"
            )

    print("\ncais/hle transformation complete!")
    print(f"Successfully transformed {transformed_count} out of {len(ds_filtered)} examples")
    print(f"Files saved to: {output_dir}")


def process_browse_comp_dataset(tools=None, special_name=None, output_format=True):
    """Process smolagents/browse_comp dataset - test split, with canary decryption."""
    print("Downloading smolagents/browse_comp test dataset from Hugging Face...")

    try:
        print("Loading smolagents/browse_comp test dataset...")
        ds = load_dataset("smolagents/browse_comp", split="test")
        print(f"Successfully loaded {len(ds)} test examples")
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Error loading dataset: {e}")
        print("Make sure you have accepted the dataset terms on Hugging Face:")
        print("https://huggingface.co/datasets/smolagents/browse_comp")
        print("You may need to login: huggingface-cli login")
        return

    output_dir = get_output_dir(base_name="browsecomp", special_name=special_name, use_date=False)
    start_index = 1

    print(f"Starting task numbering from {start_index:04d}")
    print(f"Transforming {len(ds)} smolagents/browse_comp test examples (with canary decryption)...")

    transformed_count = 0
    for idx, item in enumerate(ds):
        try:
            canary = item.get("canary", "")
            if not canary:
                print(f"Warning: Item {idx} has no canary string, skipping decryption")
                continue

            decoded_item = item.copy()
            decoded_item["problem"] = decode_with_canary(item.get("problem", ""), canary)
            decoded_item["answer"] = decode_with_canary(item.get("answer", ""), canary)

            question = decoded_item.get("problem", "")
            correct_answer = decoded_item.get("answer", "")
            effective_tools = tools if tools is not None else ["serper-search-scrape"]
            task_config = build_task_config(
                question, correct_answer, effective_tools, output_format=output_format
            )
            task_number = start_index + idx
            filename = output_dir / (
                f"browse_comp_test_{special_name}_{task_number:04d}.json"
                if special_name
                else f"browse_comp_test_{task_number:04d}.json"
            )
            save_task_json(task_config, filename)
            transformed_count += 1
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(
                f"Error transforming item {idx} "
                f"(task_id: {item.get('task_id', item.get('id', 'unknown'))}): {e}"
            )

    print("\nsmolagents/browse_comp transformation complete!")
    print(f"Successfully transformed {transformed_count} out of {len(ds)} examples")
    print(f"Files saved to: {output_dir}")
