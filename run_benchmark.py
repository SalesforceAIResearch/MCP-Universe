#!/usr/bin/env python3
"""
Benchmark entry point with support for running individual tasks, categories, or all tasks.
"""
import argparse
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from mcpuniverse.tracer.collectors import FileCollector
from mcpuniverse.benchmark.runner import BenchmarkRunner
from mcpuniverse.callbacks.handlers.vprint import get_vprint_callbacks
from mcpuniverse.benchmark.report import BenchmarkReport


BENCHMARK_TASKS = {
    "3d_design": [
        "test/3d_design/blender_task_0001.json",
        "test/3d_design/blender_task_0002.json",
        "test/3d_design/blender_task_0003.json",
        "test/3d_design/blender_task_0004.json",
        "test/3d_design/blender_task_0005.json",
        "test/3d_design/blender_task_0006.json",
        "test/3d_design/blender_task_0007.json",
        "test/3d_design/blender_task_0008.json",
        "test/3d_design/blender_task_0009.json",
        "test/3d_design/blender_task_0010.json",
        "test/3d_design/blender_task_0011.json",
        "test/3d_design/blender_task_0012.json",
        "test/3d_design/blender_task_0013.json",
        "test/3d_design/blender_task_0014.json",
        "test/3d_design/blender_task_0015.json",
        "test/3d_design/blender_task_0016.json",
        "test/3d_design/blender_task_0017.json",
        "test/3d_design/blender_task_0019.json",
        "test/3d_design/blender_task_0020.json",
    ],
    "browser_automation": [
        "test/browser_automation/playwright_paper_task_0001.json",
        "test/browser_automation/playwright_paper_task_0002.json",
        "test/browser_automation/playwright_paper_task_0003.json",
        "test/browser_automation/playwright_paper_task_0004.json",
        "test/browser_automation/playwright_paper_task_0005.json",
        "test/browser_automation/playwright_paper_task_0006.json",
        "test/browser_automation/playwright_paper_task_0007.json",
        "test/browser_automation/playwright_paper_task_0008.json",
        "test/browser_automation/playwright_sports_task_0001.json",
        "test/browser_automation/playwright_sports_task_0002.json",
        "test/browser_automation/playwright_sports_task_0003.json",
        "test/browser_automation/playwright_sports_task_0004.json",
        "test/browser_automation/playwright_sports_task_0005.json",
        "test/browser_automation/playwright_sports_task_0006.json",
        "test/browser_automation/playwright_sports_task_0007.json",
        "test/browser_automation/playwright_sports_task_0008.json",
        "test/browser_automation/playwright_huggingface_task_0001.json",
        "test/browser_automation/playwright_huggingface_task_0002.json",
        "test/browser_automation/playwright_huggingface_task_0003.json",
        "test/browser_automation/playwright_huggingface_task_0004.json",
        "test/browser_automation/playwright_huggingface_task_0005.json",
        "test/browser_automation/playwright_huggingface_task_0006.json",
        "test/browser_automation/playwright_huggingface_task_0007.json",
        "test/browser_automation/playwright_google_map_task_0001.json",
        "test/browser_automation/playwright_google_map_task_0002.json",
        "test/browser_automation/playwright_google_map_task_0003.json",
        "test/browser_automation/playwright_google_map_task_0004.json",
        "test/browser_automation/playwright_google_map_task_0005.json",
        "test/browser_automation/playwright_google_map_task_0006.json",
        "test/browser_automation/playwright_google_map_task_0007.json",
        "test/browser_automation/playwright_booking_task_0001.json",
        "test/browser_automation/playwright_booking_task_0002.json",
        "test/browser_automation/playwright_booking_task_0003.json",
        "test/browser_automation/playwright_booking_task_0004.json",
        "test/multi_server/multi-server_task_playwright_notion_0001.json",
        "test/multi_server/multi-server_task_playwright_notion_0002.json",
        "test/multi_server/multi-server_task_playwright_notion_0003.json",
        "test/multi_server/multi-server_task_playwright_notion_0004.json",
        "test/multi_server/multi-server_task_playwright_notion_0005.json",
    ],
    "financial_analysis": [
        "test/financial_analysis/yfinance_task_0001.json",
        "test/financial_analysis/yfinance_task_0002.json",
        "test/financial_analysis/yfinance_task_0003.json",
        "test/financial_analysis/yfinance_task_0004.json",
        "test/financial_analysis/yfinance_task_0005.json",
        "test/financial_analysis/yfinance_task_0006.json",
        "test/financial_analysis/yfinance_task_0007.json",
        "test/financial_analysis/yfinance_task_0008.json",
        "test/financial_analysis/yfinance_task_0009.json",
        "test/financial_analysis/yfinance_task_0010.json",
        "test/financial_analysis/yfinance_task_0011.json",
        "test/financial_analysis/yfinance_task_0012.json",
        "test/financial_analysis/yfinance_task_0013.json",
        "test/financial_analysis/yfinance_task_0014.json",
        "test/financial_analysis/yfinance_task_0015.json",
        "test/financial_analysis/yfinance_task_0016.json",
        "test/financial_analysis/yfinance_task_0017.json",
        "test/financial_analysis/yfinance_task_0018.json",
        "test/financial_analysis/yfinance_task_0019.json",
        "test/financial_analysis/yfinance_task_0020.json",
        "test/financial_analysis/yfinance_task_0021.json",
        "test/financial_analysis/yfinance_task_0022.json",
        "test/financial_analysis/yfinance_task_0023.json",
        "test/financial_analysis/yfinance_task_0024.json",
        "test/financial_analysis/yfinance_task_0025.json",
        "test/financial_analysis/yfinance_task_0026.json",
        "test/financial_analysis/yfinance_task_0027.json",
        "test/financial_analysis/yfinance_task_0028.json",
        "test/financial_analysis/yfinance_task_0029.json",
        "test/financial_analysis/yfinance_task_0030.json",
        "test/financial_analysis/yfinance_task_0031.json",
        "test/financial_analysis/yfinance_task_0032.json",
        "test/financial_analysis/yfinance_task_0033.json",
        "test/financial_analysis/yfinance_task_0034.json",
        "test/financial_analysis/yfinance_task_0035.json",
        "test/financial_analysis/yfinance_task_0036.json",
        "test/financial_analysis/yfinance_task_0037.json",
        "test/financial_analysis/yfinance_task_0038.json",
        "test/financial_analysis/yfinance_task_0039.json",
        "test/financial_analysis/yfinance_task_0040.json",
    ],
    "location_navigation": [
        "test/location_navigation/google_maps_task_0001.json",
        "test/location_navigation/google_maps_task_0002.json",
        "test/location_navigation/google_maps_task_0003.json",
        "test/location_navigation/google_maps_task_0004.json",
        "test/location_navigation/google_maps_task_0005.json",
        "test/location_navigation/google_maps_task_0006.json",
        "test/location_navigation/google_maps_task_0007.json",
        "test/location_navigation/google_maps_task_0008.json",
        "test/location_navigation/google_maps_task_0009.json",
        "test/location_navigation/google_maps_task_0010.json",
        "test/location_navigation/google_maps_task_0011.json",
        "test/location_navigation/google_maps_task_0012.json",
        "test/location_navigation/google_maps_task_0013.json",
        "test/location_navigation/google_maps_task_0014.json",
        "test/location_navigation/google_maps_task_0015.json",
        "test/location_navigation/google_maps_task_0016.json",
        "test/location_navigation/google_maps_task_0017.json",
        "test/location_navigation/google_maps_task_0018.json",
        "test/location_navigation/google_maps_task_0019.json",
        "test/location_navigation/google_maps_task_0020.json",
        "test/location_navigation/google_maps_task_0021.json",
        "test/location_navigation/google_maps_task_0022.json",
        "test/location_navigation/google_maps_task_0023.json",
        "test/location_navigation/google_maps_task_0024.json",
        "test/location_navigation/google_maps_task_0025.json",
        "test/location_navigation/google_maps_task_0026.json",
        "test/location_navigation/google_maps_task_0027.json",
        "test/location_navigation/google_maps_task_0028.json",
        "test/location_navigation/google_maps_task_0029.json",
        "test/location_navigation/google_maps_task_0030.json",
        "test/location_navigation/google_maps_task_0031.json",
        "test/location_navigation/google_maps_task_0032.json",
        "test/location_navigation/google_maps_task_0033.json",
        "test/location_navigation/google_maps_task_0034.json",
        "test/location_navigation/google_maps_task_0035.json",
        "test/multi_server/multi-server_task_playwright_google_map_0001.json",
        "test/multi_server/multi-server_task_playwright_google_map_0002.json",
        "test/multi_server/multi-server_task_playwright_google_map_0003.json",
        "test/multi_server/multi-server_task_playwright_google_map_0004.json",
        "test/multi_server/multi-server_task_playwright_google_map_0005.json",
        "test/multi_server/multi-server_task_weather_google_map_0001.json",
        "test/multi_server/multi-server_task_weather_google_map_0002.json",
        "test/multi_server/multi-server_task_weather_google_map_0003.json",
        "test/multi_server/multi-server_task_weather_google_map_0004.json",
        "test/multi_server/multi-server_task_weather_google_map_0005.json",
    ],
    "multi_server": [
        "test/multi_server/multi-server_task_weather_google_map_0001.json",
        "test/multi_server/multi-server_task_weather_google_map_0002.json",
        "test/multi_server/multi-server_task_weather_google_map_0003.json",
        "test/multi_server/multi-server_task_weather_google_map_0004.json",
        "test/multi_server/multi-server_task_weather_google_map_0005.json",
        "test/multi_server/multi-server_task_playwright_google_map_0001.json",
        "test/multi_server/multi-server_task_playwright_google_map_0002.json",
        "test/multi_server/multi-server_task_playwright_google_map_0003.json",
        "test/multi_server/multi-server_task_playwright_google_map_0004.json",
        "test/multi_server/multi-server_task_playwright_google_map_0005.json",
        "test/multi_server/multi-server_task_playwright_notion_0001.json",
        "test/multi_server/multi-server_task_playwright_notion_0002.json",
        "test/multi_server/multi-server_task_playwright_notion_0003.json",
        "test/multi_server/multi-server_task_playwright_notion_0004.json",
        "test/multi_server/multi-server_task_playwright_notion_0005.json",
        "test/multi_server/multi-server_task_google_search_notion_0001.json",
        "test/multi_server/multi-server_task_google_search_notion_0002.json",
        "test/multi_server/multi-server_task_google_search_notion_0003.json",
        "test/multi_server/multi-server_task_google_search_notion_0004.json",
        "test/multi_server/multi-server_task_google_search_notion_0005.json",
        "test/multi_server/multi-server_task_playwright_github_0001.json",
        "test/multi_server/multi-server_task_playwright_github_0002.json",
        "test/multi_server/multi-server_task_playwright_github_0003.json",
        "test/multi_server/multi-server_task_playwright_github_0004.json",
        "test/multi_server/multi-server_task_playwright_github_0005.json",
    ],
    "repository_management": [
        "test/repository_management/github_task_0001.json",
        "test/repository_management/github_task_0002.json",
        "test/repository_management/github_task_0003.json",
        "test/repository_management/github_task_0004.json",
        "test/repository_management/github_task_0005.json",
        "test/repository_management/github_task_0006.json",
        "test/repository_management/github_task_0007.json",
        "test/repository_management/github_task_0008.json",
        "test/repository_management/github_task_0009.json",
        "test/repository_management/github_task_0010.json",
        "test/repository_management/github_task_0011.json",
        "test/repository_management/github_task_0012.json",
        "test/repository_management/github_task_0014.json",
        "test/repository_management/github_task_0015.json",
        "test/repository_management/github_task_0016.json",
        "test/repository_management/github_task_0017.json",
        "test/repository_management/github_task_0018.json",
        "test/repository_management/github_task_0019.json",
        "test/repository_management/github_task_0021.json",
        "test/repository_management/github_task_0022.json",
        "test/repository_management/github_task_0023.json",
        "test/repository_management/github_task_0024.json",
        "test/repository_management/github_task_0025.json",
        "test/repository_management/github_task_0026.json",
        "test/repository_management/github_task_0027.json",
        "test/repository_management/github_task_0028.json",
        "test/repository_management/github_task_0029.json",
        "test/repository_management/github_task_0030.json",
        "test/multi_server/multi-server_task_playwright_github_0001.json",
        "test/multi_server/multi-server_task_playwright_github_0002.json",
        "test/multi_server/multi-server_task_playwright_github_0003.json",
        "test/multi_server/multi-server_task_playwright_github_0004.json",
        "test/multi_server/multi-server_task_playwright_github_0005.json",
    ],
    "web_search": [
        "test/web_search/info_search_task_0001.json",
        "test/web_search/info_search_task_0002.json",
        "test/web_search/info_search_task_0003.json",
        "test/web_search/info_search_task_0004.json",
        "test/web_search/info_search_task_0005.json",
        "test/web_search/info_search_task_0006.json",
        "test/web_search/info_search_task_0007.json",
        "test/web_search/info_search_task_0008.json",
        "test/web_search/info_search_task_0009.json",
        "test/web_search/info_search_task_0010.json",
        "test/web_search/info_search_task_0011.json",
        "test/web_search/info_search_task_0012.json",
        "test/web_search/info_search_task_0013.json",
        "test/web_search/info_search_task_0014.json",
        "test/web_search/info_search_task_0015.json",
        "test/web_search/info_search_task_0016.json",
        "test/web_search/info_search_task_0017.json",
        "test/web_search/info_search_task_0018.json",
        "test/web_search/info_search_task_0019.json",
        "test/web_search/info_search_task_0020.json",
        "test/web_search/info_search_task_0021.json",
        "test/web_search/info_search_task_0022.json",
        "test/web_search/info_search_task_0023.json",
        "test/web_search/info_search_task_0024.json",
        "test/web_search/info_search_task_0025.json",
        "test/web_search/info_search_task_0026.json",
        "test/web_search/info_search_task_0027.json",
        "test/web_search/info_search_task_0028.json",
        "test/web_search/info_search_task_0029.json",
        "test/web_search/info_search_task_0030.json",
        "test/web_search/info_search_task_0031.json",
        "test/web_search/info_search_task_0032.json",
        "test/web_search/info_search_task_0033.json",
        "test/web_search/info_search_task_0034.json",
        "test/web_search/info_search_task_0035.json",
        "test/web_search/info_search_task_0036.json",
        "test/web_search/info_search_task_0037.json",
        "test/web_search/info_search_task_0038.json",
        "test/web_search/info_search_task_0039.json",
        "test/web_search/info_search_task_0040.json",
        "test/web_search/info_search_task_0041.json",
        "test/web_search/info_search_task_0042.json",
        "test/web_search/info_search_task_0043.json",
        "test/web_search/info_search_task_0044.json",
        "test/web_search/info_search_task_0045.json",
        "test/web_search/info_search_task_0046.json",
        "test/web_search/info_search_task_0047.json",
        "test/web_search/info_search_task_0048.json",
        "test/web_search/info_search_task_0049.json",
        "test/web_search/info_search_task_0050.json",
        "test/multi_server/multi-server_task_google_search_notion_0001.json",
        "test/multi_server/multi-server_task_google_search_notion_0002.json",
        "test/multi_server/multi-server_task_google_search_notion_0003.json",
        "test/multi_server/multi-server_task_google_search_notion_0004.json",
        "test/multi_server/multi-server_task_google_search_notion_0005.json",
    ],
}


def generate_yaml_config(
    tasks: List[str], 
    config_file: Optional[str] = None,
    model_name: Optional[str] = None,
    base_url: Optional[str] = None,
    agent_type: Optional[str] = None,
    token: Optional[str] = None,
    max_iterations: Optional[int] = None
) -> str:
    """
    Generate YAML configuration for the benchmark.
    
    Args:
        tasks: List of task file paths
        config_file: Optional path to a base configuration file to extend
        model_name: Optional model name to use
        base_url: Optional base URL for the LLM API
        agent_type: Optional agent type (react, function_call, etc.)
        token: Optional API token (api_key in config)
        max_iterations: Optional maximum iterations for agent
    
    Returns:
        YAML configuration as a string
    """
    if config_file and os.path.exists(config_file):
        # Load existing config and update tasks
        with open(config_file, 'r', encoding='utf-8') as f:
            content = f.read()
        # This is a simple approach - you may need to parse YAML properly
        return content
    
    # Generate default configuration
    # Use provided values or defaults
    if not model_name or not base_url or not agent_type:
        raise ValueError("model_name, base_url, and agent_type must be specified if no config_file is provided.")
    
    final_max_iterations = max_iterations if max_iterations is not None else 20
    
    yaml_template = f"""
kind: llm
spec:
  name: llm-1
  type: openai
  config:
    model_name: {model_name}
    base_url: {base_url}
    api_key: {token}


---
kind: agent
spec:
  name: mcpu-agent
  type: {agent_type}
  config:
    llm: llm-1
    instruction: You are a helpful AI assistant that follows the user's instructions carefully. You are an expert in using tools to assist with various tasks. When answering in numbers in financial tasks, always use demical format without percentage signsxs.
    max_iterations: {final_max_iterations}
    summarize_tool_response: false

---
kind: benchmark
spec:
  description: Benchmark run
  agent: mcpu-agent
  tasks:
{chr(10).join(f'    - {task}' for task in tasks)}
"""
    return yaml_template


def get_tasks_to_run(args) -> Dict[str, List[str]]:
    """
    Determine which tasks to run based on command line arguments.
    
    Returns:
        Dictionary mapping category names to list of task paths
    """
    tasks_by_category = {}
    
    if args.run_all:
        tasks_by_category = BENCHMARK_TASKS.copy()
    elif args.run_category:
        category = args.run_category
        if category not in BENCHMARK_TASKS:
            print(f"Error: Category '{category}' not found.")
            print(f"Available categories: {', '.join(BENCHMARK_TASKS.keys())}")
            sys.exit(1)
        tasks_by_category[category] = BENCHMARK_TASKS[category]
    elif args.run_instance:
        task_path = args.run_instance
        # Find which category this task belongs to
        found = False
        for category, tasks in BENCHMARK_TASKS.items():
            if task_path in tasks:
                tasks_by_category[category] = [task_path]
                found = True
                break
        
        if not found:
            # Task might be specified directly, use it as-is
            tasks_by_category["custom"] = [task_path]
    
    return tasks_by_category


async def run_task(
    task_path: str, 
    config_file: Optional[str], 
    log_dir: str,
    model_name: Optional[str] = None,
    base_url: Optional[str] = None,
    agent_type: Optional[str] = None,
    token: Optional[str] = None,
    max_iterations: Optional[int] = None
) -> Dict:
    """
    Run a single task and return its results.
    
    Args:
        task_path: Path to the task JSON file
        config_file: Optional configuration file path
        log_dir: Directory to store logs
        model_name: Optional model name to use
        base_url: Optional base URL for the LLM API
        agent_type: Optional agent type (react, function_call, etc.)
        token: Optional API token (api_key in config)
        max_iterations: Optional maximum iterations for agent
    
    Returns:
        Dictionary with task results
    """
    # Generate YAML config
    yaml_content = generate_yaml_config(
        [task_path], config_file, model_name, base_url, agent_type, token, max_iterations
    )
    
    # Create temporary file for YAML config
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as temp_file:
        temp_file.write(yaml_content)
        temp_file_path = temp_file.name
    
    try:
        # Create log directory
        os.makedirs(log_dir, exist_ok=True)
        
        # Setup trace collector
        task_name = Path(task_path).stem
        log_file = os.path.join(log_dir, f"{task_name}.log")
        trace_collector = FileCollector(log_file=log_file)
        
        # Run benchmark
        benchmark = BenchmarkRunner(temp_file_path)
        results = await benchmark.run(
            trace_collector=trace_collector,
            callbacks=get_vprint_callbacks()
        )
        
        # Generate report
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_name = f"{task_name}_{timestamp}_report.md"
        report = BenchmarkReport(benchmark, trace_collector, log_dir, report_name)
        report.dump()
        
        if not results or len(results) == 0:
            print(f"Warning: No results returned for task {task_path}")
            task_result = {
                "task": task_path,
                "task_name": task_name,
                "status": "no_results",
                "passed": False,
                "score": 0.0,
                "passed_evals": 0,
                "total_evals": 0,
                "evaluation_results": [],
                "log_file": log_file
            }
            
            # Save individual task result to JSON
            task_result_file = os.path.join(log_dir, f"{task_name}_result.json")
            with open(task_result_file, 'w', encoding='utf-8') as f:
                json.dump(task_result, f, indent=2, ensure_ascii=False)
            
            task_result["result_file"] = task_result_file
            return task_result
        
        # Extract evaluation results
        task_results = results[0].task_results
        task_key = list(task_results.keys())[0] if task_results else None
        
        if task_key:
            eval_results = task_results[task_key].get('evaluation_results', [])
            
            # Calculate score: passed_evals / total_evals
            total_evals = len(eval_results)
            passed_evals = sum(1 for result in eval_results if result.passed)
            score = passed_evals / total_evals if total_evals > 0 else 0.0
            
            # A task is only considered "passed" if score is exactly 1.0
            passed = (score == 1.0)
            
            # Convert evaluation results to serializable format
            eval_data = []
            for i, eval_result in enumerate(eval_results, 1):
                eval_data.append({
                    "eval_id": i,
                    "func": eval_result.config.func,
                    "op": eval_result.config.op,
                    "op_args": eval_result.config.op_args,
                    "value": eval_result.config.value,
                    "passed": eval_result.passed,
                    "reason": getattr(eval_result, 'reason', ''),
                    "message": getattr(eval_result, 'message', ''),
                    "error": getattr(eval_result, 'error', '')
                })
            
            task_result = {
                "task": task_path,
                "task_name": task_name,
                "status": "completed",
                "passed": passed,
                "score": score,
                "passed_evals": passed_evals,
                "total_evals": total_evals,
                "evaluation_results": eval_data,
                "log_file": log_file,
                "report_file": os.path.join(log_dir, report_name)
            }
            
            # Save individual task result to JSON
            task_result_file = os.path.join(log_dir, f"{task_name}_result.json")
            with open(task_result_file, 'w', encoding='utf-8') as f:
                json.dump(task_result, f, indent=2, ensure_ascii=False)
            
            task_result["result_file"] = task_result_file
            return task_result
        else:
            task_result = {
                "task": task_path,
                "task_name": task_name,
                "status": "no_task_results",
                "passed": False,
                "score": 0.0,
                "passed_evals": 0,
                "total_evals": 0,
                "evaluation_results": [],
                "log_file": log_file
            }
            
            # Save individual task result to JSON
            task_result_file = os.path.join(log_dir, f"{task_name}_result.json")
            with open(task_result_file, 'w', encoding='utf-8') as f:
                json.dump(task_result, f, indent=2, ensure_ascii=False)
            
            task_result["result_file"] = task_result_file
            return task_result
    
    except Exception as e:
        print(f"Error running task {task_path}: {e}")
        import traceback
        traceback.print_exc()
        
        task_name = Path(task_path).stem
        log_file = os.path.join(log_dir, f"{task_name}.log")
        
        task_result = {
            "task": task_path,
            "task_name": task_name,
            "status": "error",
            "passed": False,
            "score": 0.0,
            "passed_evals": 0,
            "total_evals": 0,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "evaluation_results": [],
            "log_file": log_file
        }
        
        # Save individual task result to JSON
        try:
            task_result_file = os.path.join(log_dir, f"{task_name}_result.json")
            with open(task_result_file, 'w', encoding='utf-8') as f:
                json.dump(task_result, f, indent=2, ensure_ascii=False)
            task_result["result_file"] = task_result_file
        except Exception as save_error:
            print(f"Warning: Failed to save task result JSON: {save_error}")
        
        return task_result
    
    finally:
        # Cleanup temporary file
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)


async def run_category(
    category: str, 
    tasks: List[str], 
    config_file: Optional[str], 
    log_dir: str,
    model_name: Optional[str] = None,
    base_url: Optional[str] = None,
    agent_type: Optional[str] = None,
    token: Optional[str] = None,
    max_iterations: Optional[int] = None
) -> Tuple[Dict, List[Dict], List[Dict]]:
    """
    Run all tasks in a category and collect results.
    
    Args:
        category: Category name
        tasks: List of task paths in this category
        config_file: Optional configuration file path
        log_dir: Directory to store logs
        model_name: Optional model name to use
        base_url: Optional base URL for the LLM API
        agent_type: Optional agent type (react, function_call, etc.)
        token: Optional API token (api_key in config)
        max_iterations: Optional maximum iterations for agent
    
    Returns:
        Tuple of (category_summary, passed_tasks_detail, failed_tasks_detail)
    """
    print(f"\n{'='*80}")
    print(f"Running category: {category}")
    print(f"{'='*80}\n")
    
    category_log_dir = os.path.join(log_dir, category)
    os.makedirs(category_log_dir, exist_ok=True)
    
    task_results = []
    
    for i, task in enumerate(tasks, 1):
        print(f"\n[{i}/{len(tasks)}] Running task: {task}")
        result = await run_task(
            task, config_file, category_log_dir, model_name, base_url, agent_type, token, max_iterations
        )
        task_results.append(result)
        
        # Print result summary
        status_symbol = "✓" if result.get("passed", False) else "✗"
        print(f"{status_symbol} Task completed: {result['status']}")
    
    # Calculate category statistics
    total_tasks = len(task_results)
    passed_task_list = [r for r in task_results if r.get("passed", False)]
    failed_task_list = [r for r in task_results if not r.get("passed", False)]
    
    passed_tasks = len(passed_task_list)
    failed_tasks = len(failed_task_list)
    pass_rate = (passed_tasks / total_tasks * 100) if total_tasks > 0 else 0
    
    # Create detailed lists with logs and scores for top-level summary
    passed_tasks_detail = [{
        "task": r["task"],
        "task_name": r.get("task_name", Path(r["task"]).stem),
        "score": r.get("score", 0.0),
        "log_file": r.get("log_file", ""),
        "result_file": r.get("result_file", ""),
        "report_file": r.get("report_file", "")
    } for r in passed_task_list]
    
    failed_tasks_detail = [{
        "task": r["task"],
        "task_name": r.get("task_name", Path(r["task"]).stem),
        "score": r.get("score", 0.0),
        "status": r.get("status", "unknown"),
        "passed_evals": r.get("passed_evals", 0),
        "total_evals": r.get("total_evals", 0),
        "log_file": r.get("log_file", ""),
        "result_file": r.get("result_file", ""),
        "report_file": r.get("report_file", ""),
        "error": r.get("error", ""),
        "evaluation_results": r.get("evaluation_results", [])
    } for r in failed_task_list]
    
    # Create cleaned task list for category (without redundant fields)
    cleaned_tasks = [{
        "task": r["task"],
        "task_name": r.get("task_name", Path(r["task"]).stem),
        "status": r.get("status", "unknown"),
        "passed": r.get("passed", False),
        "score": r.get("score", 0.0),
        "passed_evals": r.get("passed_evals", 0),
        "total_evals": r.get("total_evals", 0),
        "error": r.get("error", "")
    } for r in task_results]
    
    category_summary = {
        "category": category,
        "total_tasks": total_tasks,
        "passed_tasks": passed_tasks,
        "failed_tasks": failed_tasks,
        "pass_rate": pass_rate,
        "tasks": cleaned_tasks
    }
    
    print(f"\n{'='*80}")
    print(f"Category '{category}' Summary:")
    print(f"  Total: {total_tasks}, Passed: {passed_tasks}, Failed: {failed_tasks}")
    print(f"  Pass Rate: {pass_rate:.2f}%")
    print(f"{'='*80}\n")
    
    return category_summary, passed_tasks_detail, failed_tasks_detail


async def main():
    """Main entry point for the benchmark runner."""
    parser = argparse.ArgumentParser(
        description="MCP-Universe Benchmark Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run a single task
  python run_benchmark.py --run-instance test/3d_design/blender_task_0001.json

  # Run all tasks in a category
  python run_benchmark.py --run-category financial_analysis

  # Run all tasks in all categories
  python run_benchmark.py --run-all

  # Specify custom configuration and output
  python run_benchmark.py --run-category web_search --config my_config.yaml --log-dir ./results --evaluation-report summary.json
        """
    )
    
    # Mutually exclusive group for run modes
    run_mode = parser.add_mutually_exclusive_group(required=True)
    run_mode.add_argument(
        '--run-instance',
        type=str,
        help='Run a single task by specifying the task file path (e.g., test/3d_design/blender_task_0001.json)'
    )
    run_mode.add_argument(
        '--run-category',
        type=str,
        help='Run all tasks in a specific category (e.g., financial_analysis, web_search)'
    )
    run_mode.add_argument(
        '--run-all',
        action='store_true',
        help='Run all tasks across all categories'
    )
    
    # Optional arguments
    parser.add_argument(
        '--config',
        type=str,
        help='Path to YAML configuration file (optional, will use default if not specified)'
    )
    parser.add_argument(
        '--log-dir',
        type=str,
        default='log',
        help='Directory to store log files and reports (default: log)'
    )
    parser.add_argument(
        '--evaluation-report',
        type=str,
        default='evaluation_summary.json',
        help='Path to save the evaluation summary JSON file (default: evaluation_summary.json)'
    )
    parser.add_argument(
        '--model-name',
        type=str,
        help='Model name to use for the LLM (e.g., gpt-4, qwen3-coder-plus)'
    )
    parser.add_argument(
        '--base-url',
        type=str,
        help='Base URL for the LLM API (e.g., https://api.openai.com/v1)'
    )
    parser.add_argument(
        '--agent-type',
        type=str,
        choices=['react', 'function_call'],
        help='Agent type to use (react or function_call)'
    )
    parser.add_argument(
        '--token',
        type=str,
        default='token-abc123',
        help='API token to use for authentication (default: token-abc123)'
    )
    parser.add_argument(
        '--max-iterations',
        type=int,
        default=20,
        help='Maximum number of iterations for the agent (default: 20)'
    )
    
    args = parser.parse_args()
    
    # Get tasks to run
    tasks_by_category = get_tasks_to_run(args)
    
    if not tasks_by_category:
        print("Error: No tasks to run.")
        sys.exit(1)
    
    # Run benchmarks
    all_category_results = []
    all_passed_tasks = []
    all_failed_tasks = []
    
    for category, tasks in tasks_by_category.items():
        category_result, passed_details, failed_details = await run_category(
            category,
            tasks,
            args.config,
            args.log_dir,
            args.model_name,
            args.base_url,
            args.agent_type,
            args.token,
            args.max_iterations
        )
        all_category_results.append(category_result)
        all_passed_tasks.extend(passed_details)
        all_failed_tasks.extend(failed_details)
    
    # Calculate overall statistics
    total_tasks = sum(r['total_tasks'] for r in all_category_results)
    total_passed = sum(r['passed_tasks'] for r in all_category_results)
    total_failed = sum(r['failed_tasks'] for r in all_category_results)
    overall_pass_rate = (total_passed / total_tasks * 100) if total_tasks > 0 else 0
    
    # Determine run mode details
    run_mode = "all" if args.run_all else ("category" if args.run_category else "instance")
    
    # Create final summary
    summary = {
        "timestamp": datetime.now().isoformat(),
        "run_mode": run_mode,
        "total_categories": len(all_category_results),
        "total_tasks": total_tasks,
        "passed_tasks": total_passed,
        "failed_tasks": total_failed,
        "overall_pass_rate": overall_pass_rate,
        "passed_tasks_detail": all_passed_tasks,
        "failed_tasks_detail": all_failed_tasks,
        "categories": all_category_results
    }
    
    # For category mode, add the category name at the top level
    if run_mode == "category" and len(all_category_results) == 1:
        summary["category"] = all_category_results[0]["category"]
    
    # Save summary to JSON
    report_path = args.evaluation_report
    os.makedirs(os.path.dirname(report_path) if os.path.dirname(report_path) else '.', exist_ok=True)
    
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    # Print final summary
    print('=' * 80)
    print("OVERALL SUMMARY")
    print('=' * 80)
    print(f"Total Categories: {len(all_category_results)}")
    print(f"Total Tasks: {total_tasks}")
    print(f"Passed: {total_passed}")
    print(f"Failed: {total_failed}")
    print(f"Overall Pass Rate: {overall_pass_rate:.2f}%")
    print(f"\nDetailed report saved to: {report_path}")
    print(f"Log files saved to: {args.log_dir}")
    print('=' * 80)
    
    # Exit with appropriate code
    sys.exit(0 if total_failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
