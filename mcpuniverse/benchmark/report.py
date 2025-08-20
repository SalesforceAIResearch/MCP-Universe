"""
The class for a generate a report
"""
# pylint: disable=broad-exception-caught
import uuid
from datetime import datetime
from typing import List, Dict
from pathlib import Path
from collections import defaultdict
from mcpuniverse.agent.base import TOOL_RESPONSE_SUMMARIZER_PROMPT
from mcpuniverse.tracer.collectors import BaseCollector
from .runner import BenchmarkResult, BenchmarkConfig, BenchmarkRunner

REPORT_FOLDER = Path('log')


class BenchmarkReport:
    """
    Class for generating a benchmark report.
    """

    def __init__(self, runner: BenchmarkRunner, trace_collector: BaseCollector):
        self.benchmark_configs: List[BenchmarkConfig] = runner._benchmark_configs
        self.benchmark_results: List[BenchmarkResult] = runner._benchmark_results
        self.benchmark_agent_configs: List[Dict] = runner._agent_configs
        self.trace_collector = trace_collector

        self.llm_configs = [x for x in self.benchmark_agent_configs if x['kind'] == 'llm']
        assert len(self.llm_configs) == 1, "the number of llm configs should be 1"
        self.llm_configs = self.llm_configs[0]

        self.agent_configs = [x for x in self.benchmark_agent_configs if x['kind'] == 'agent']
        assert len(self.agent_configs) == 1, "the number of agent configs should be 1"
        self.agent_configs = self.agent_configs[0]

        assert len(self.benchmark_configs) == len(
            self.benchmark_results), "benchmark_configs and benchmark_result should have the same length"
        self.log_file = ''

    def dump(self):
        """Dump the result to a report, will dump to REPORT_FOLDER"""
        final_report_str = []

        for benchmark_idx, (benchmark_config, benchmark_result) in enumerate(
                zip(self.benchmark_configs, self.benchmark_results)):
            section_config = []
            section_config.append("## Benchmark Config\n")
            section_config.append(f"**Benchmark description:** {benchmark_config.description}\n")
            section_config.append(f"**Agent:** {benchmark_config.agent}\n")
            section_config.append(
                f"**LLM:** {self.llm_configs['spec']['type']}: {self.llm_configs['spec']['config']['model_name']}\n")

            section_summary = []
            section_summary.append("## Benchmark Summary")
            section_summary.append(
                "| Name | Passed | Not Passed | Score |\n"
                "| ---  | ------ | ---------- | ----- |"
            )

            section_details = []
            section_details.append("## Appendix (Benchmark Details)")

            for task_name in benchmark_result.task_results.keys():
                trace_id = self.benchmark_results[benchmark_idx].task_trace_ids.get(task_name)
                stats = defaultdict(int)
                iter_names = []

                for task_trace in self.trace_collector.get(trace_id):
                    iter_type = task_trace.records[0].data['type']
                    iter_name = iter_type
                    if iter_type == 'llm':
                        summary_prompt = TOOL_RESPONSE_SUMMARIZER_PROMPT[:20]
                        is_summarized = task_trace.records[0].data['messages'][0]['content'].startswith(summary_prompt)
                        print(iter_type, is_summarized)
                        iter_name = f"llm_{'summary' if is_summarized else 'thought'}"

                    iter_names.append(iter_name)
                    stats[iter_name] += 1

                section_details.append("### Task")
                section_details.append(f"- config: {task_name}")
                eval_results = benchmark_result.task_results[task_name]["evaluation_results"]

                task_passed = 0
                task_notpassed = 0
                section_details.append("- Agent Response:")

                for key, value in stats.items():
                    section_details.append(f"  - {key}: {value}\n")

                section_details.append(f"- Iterations: \n[{', '.join(iter_names)}]")
                section_details.append("- Evaluation Results: \n")

                for eval_idx, eval_result in enumerate(eval_results, start=1):
                    section_details.append(f"  - Eval id: {eval_idx}")
                    section_details.append(f"    - Evaluation Description: {eval_result.config.desc}\n")
                    if eval_result.passed:
                        eval_passed = '<span color="green">True<span>'
                        task_passed += 1
                    else:
                        eval_passed = '<span color="red">False<span>'
                        task_notpassed += 1
                        if eval_result.reason:
                            section_details.append(f"    - Reason: {eval_result.reason}\n")
                        if eval_result.error:
                            section_details.append(f"    - Error: {eval_result.error}\n")

                    section_details.append(f"    - Passed? {eval_passed}\n")
                # Summary
                section_summary.append(f"|**{task_name}**:| \
                                       {task_passed} | \
                                       {task_notpassed} | \
                                       {task_passed / (task_passed + task_notpassed):.2f} |")

            final_report_str.extend(section_config)
            final_report_str.extend(section_summary)
            final_report_str.extend(section_details)
            final_report_str = '\n'.join(final_report_str)
            self.write_to_report(final_report_str)

    def write_to_report(self, report_str):
        """Write a report in MD format."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4()
        report_name = REPORT_FOLDER / f"report_{timestamp}_{unique_id}.md"
        try:
            with open(report_name, "w", encoding="utf-8") as f:
                f.write(report_str)
        except Exception as e:
            print(f"Write report error: {e}")
