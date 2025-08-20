import json
import pytest
import unittest
from mcpuniverse.benchmark.task import Task


class TestTask(unittest.TestCase):

    @pytest.mark.skip
    def test_evaluate(self):
        task = Task("mcpuniverse/benchmark/configs/test/google_maps/google_maps_task_0010.json")
        data = {
            "stops": [
                {
                    "name": "Restaurant Al Omara Hadramout",
                    "place id": "ChIJ2YU5VY-5zTER1E_yH7f-RQU"
                }
            ]
        }
        results = task.evaluate(json.dumps(data))

        from prettytable import PrettyTable
        table = PrettyTable()
        table.field_names = ["Eval Id", "[Function][Op](Args)", "Result"]
        for eval_id, result in enumerate(results, start=1):
            table.add_row([f"Eval {eval_id}", f"[{result.config.func}][{result.config.op}]({result.config.op_args})",
                           result.passed])
        print(table)


if __name__ == "__main__":
    unittest.main()
