import pytest
import unittest
from mcpuniverse.benchmark.task import Task


class TestTask(unittest.TestCase):

    @pytest.mark.skip
    def test_evaluate(self):
        task = Task("mcpuniverse/benchmark/configs/test/github/github_task_0008.json")
        results = task.evaluate("")

        from prettytable import PrettyTable
        table = PrettyTable()
        table.field_names = ["Eval Id", "[Function][Op](Args)", "Result"]
        for eval_id, result in enumerate(results, start=1):
            table.add_row([f"Eval {eval_id}", f"[{result.config.func}][{result.config.op}]({result.config.op_args})",
                           result.passed])

        print(table)


if __name__ == "__main__":
    unittest.main()
