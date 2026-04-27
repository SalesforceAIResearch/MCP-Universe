Move deepresearch to mcpuniverse/benchmark/deepresearch/

**Status (implemented):** The suite lives at `mcpuniverse/benchmark/deepresearch/`. The HLE judge is `hle_judge.py` there; `mcpuniverse/evaluator/__init__.py` imports it for `deepresearch.hle_llm_as_a_judge` registration; `mcpuniverse/evaluator/deepresearch/` has been removed. Historical steps below are kept for reference.

Goal





From: mcpuniverse/benchmark/configs/deepresearch/ (treat as the “bundle”: README, prepare_deep_research_data.py, data_utils.py, configs/{browsecomp,gaia,hle}/*.yaml, and generated/ignored task JSON dirs such as browsecomp/, hle_text_only/, gaia_val_text_only/, task_yamls/ if present).



To: mcpuniverse/benchmark/deepresearch/ (same internal layout; only the parent directory changes: sibling of configs/, not inside it).



This matches the destination you selected: mcpuniverse/benchmark/deepresearch.

Move evaluator deepresearch into the same bundle

Locked in (your choice): implement the HLE judge as mcpuniverse/benchmark/deepresearch/hle_judge.py (not a nested evaluator/ subpackage under the bundle) and import it from mcpuniverse/evaluator/init.py for compare_func registration. Do not keep mcpuniverse/evaluator/deepresearch/ after the move.

Current code: mcpuniverse/evaluator/deepresearch/functions.py defines the HLE LLM-as-judge (@compare_func(name="deepresearch.hle_llm_as_a_judge")).





Target: Colocate with the bundle as hle_judge.py (single module next to data_utils.py, prepare_deep_research_data.py, etc.).



Do not change the string passed to @compare_func: it must remain deepresearch.hle_llm_as_a_judge. Task JSON and data_utils.py reference that registered op name, not a Python import path.



Registration: mcpuniverse/evaluator/init.py currently has from .deepresearch.functions import * so the decorator runs and registers the function at import mcpuniverse.evaluator. After the move, replace with:





from mcpuniverse.benchmark.deepresearch.hle_judge import *



No import cycle: The new module only needs compare_func from mcpuniverse/evaluator/functions.py (a submodule, not a circular import through evaluator's __init__ during decoration).



Remove the old package mcpuniverse/evaluator/deepresearch/ after the file lives under benchmark/deepresearch/. A repo search shows no other from mcpuniverse.evaluator.deepresearch usage; the only import is evaluator/__init__.py.



Optional docstring fix: The current file header still says "Yahoo finance" — that can be corrected in the same pass.

Steps





Move the tree (preserve git history with git mv):





mcpuniverse/benchmark/configs/deepresearch → mcpuniverse/benchmark/deepresearch



Global path prefix (repo-root style paths in YAML and docs): replace





mcpuniverse/benchmark/configs/deepresearch → mcpuniverse/benchmark/deepresearch



Touched in practice:





The three large agent configs under deepresearch/configs/{hle,browsecomp,gaia}/*.yaml (task lists; bulk replace is fine).



mcpuniverse/benchmark/deepresearch/data_utils.py get_output_dir base.



mcpuniverse/benchmark/deepresearch/prepare_deep_research_data.py: update module docstring and from mcpuniverse.benchmark.deepresearch.data_utils import ....



Python module name: use **mcpuniverse.benchmark.deepresearch** (not mcpuniverse.benchmark.configs.deepresearch). The runnable entrypoint becomes:





python -m mcpuniverse.benchmark.deepresearch.prepare_deep_research_data



Evaluator (HLE judge) move (see Move evaluator deepresearch into the same bundle):





Move mcpuniverse/evaluator/deepresearch/functions.py to mcpuniverse/benchmark/deepresearch/hle_judge.py.



Update mcpuniverse/evaluator/init.py to from mcpuniverse.benchmark.deepresearch.hle_judge import * so import mcpuniverse.evaluator still registers deepresearch.hle_llm_as_a_judge.



Remove mcpuniverse/evaluator/deepresearch/.



Packaging: extend [pyproject.toml](pyproject.toml) [tool.setuptools.package-data]  so assets under the new path ship (they were previously covered by benchmark/configs/). Add a line for deep research, e.g. benchmark/deepresearch/**/ or benchmark/deepresearch/* (match the setuptools pattern style already used; use recursive ** if the project relies on nested YAML/JSON in wheels).



**.gitignore**: repoint the three browsecomp / gaia_val_text_only / hle_text_only lines from mcpuniverse/benchmark/configs/deepresearch/... to mcpuniverse/benchmark/deepresearch/....



Docs and scripts (same prefix replacement as step 2):





README.md runbook links to the deep research README.



mcpuniverse/benchmark/deepresearch/README.md (all commands and “File layout” can stay structurally the same; optionally add one line that the top-level path is mcpuniverse/benchmark/deepresearch/).



tests/benchmark/test_deepresearch_paralell_config.sh default TASK_FOLDER and the comment (e.g. mcpuniverse/benchmark/deepresearch/task_yamls/...).



Verification (after implementation):





Grep to ensure no stale configs/deepresearch, benchmark.configs.deepresearch, or evaluator/deepresearch references remain in tracked sources.



python -c "import mcpuniverse.evaluator" and python -c "import mcpuniverse.benchmark.deepresearch.prepare_deep_research_data".



If you have CI for benchmarks, re-run the deep research test that loads a YAML and one task.

Data flow (unchanged behavior)

flowchart LR
  Yaml["Agent YAML in deepresearch/configs"]
  TaskJson["Task JSON paths in YAML"]
  Runner["BenchmarkRunner"]
  HleJudge["HLE compare_func in benchmark/deepresearch"]
  Yaml --> Runner
  TaskJson --> Runner
  TaskJson -->|"op deepresearch.hle_llm_as_a_judge"| HleJudge

Task JSON paths stay repo-root absolute under mcpuniverse/benchmark/deepresearch/...; only the configs segment in the path is removed. The evaluator op name deepresearch.hle_llm_as_a_judge is unchanged; only the Python module that implements and registers it moves under mcpuniverse/benchmark/deepresearch/ and is pulled in from mcpuniverse/evaluator/init.py so import mcpuniverse.evaluator still registers the function.

Note on local or generated data

If you already generated task JSON into the old path on disk, either regenerate with the updated prepare script or move those directories manually so they match the new mcpuniverse/benchmark/deepresearch/... layout.
