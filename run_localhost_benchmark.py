import asyncio
from mcpuniverse.tracer.collectors import FileCollector
from mcpuniverse.benchmark.runner import BenchmarkRunner
from mcpuniverse.callbacks.handlers.vprint import get_vprint_callbacks

async def run_benchmark():
    trace_collector = FileCollector(log_file="log/localhost_browser.log")
    benchmark = BenchmarkRunner("configs/localhost_browser_benchmark.yaml")
    
    results = await benchmark.run(
        trace_collector=trace_collector,
        callbacks=get_vprint_callbacks()
    )
    
    print("\n" + "="*70)
    print("RESULTS SUMMARY")
    print("="*70)
    for i, benchmark_result in enumerate(results, 1):
        print(f"\nBenchmark {i}: {benchmark_result.benchmark.description}")
        for task_path, task_result in benchmark_result.task_results.items():
            eval_results = task_result.get('evaluation_results', [])
            
            passed = all(ev.passed for ev in eval_results) if eval_results else False
            
            print(f"\n  Task: {task_path}")
            print(f"    Passed: {passed}")
            
            if eval_results:
                print(f"    Evaluations: {len(eval_results)} checks")
                for j, ev in enumerate(eval_results, 1):
                    status = "✓" if ev.passed else "✗"
                    print(f"      {status} {j}. {ev.config.func} {ev.config.op} '{ev.config.value}'")
                    if not ev.passed and ev.reason:
                        print(f"         Reason: {ev.reason}")
    
    print("\n" + "="*70)
    print("Log file: log/localhost_browser.log")
    print("="*70)

if __name__ == "__main__":
    asyncio.run(run_benchmark())
