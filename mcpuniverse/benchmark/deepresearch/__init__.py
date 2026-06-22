"""
Deep research benchmark suite (W&D paper reproduction).

This bundle provides:
- Data preparation utilities for GAIA, HLE, and BrowseComp datasets
- Agent configurations with parallel tool calling
- HLE LLM-as-a-judge evaluator (registered in mcpuniverse.evaluator)

Task files are generated under task_configs/ subdirectory.
Evaluator functions are registered via mcpuniverse.evaluator.__init__.py import.
"""
