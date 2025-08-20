import os
import json
import unittest
from mcpuniverse.evaluator.evaluator import Evaluator, EvaluatorConfig


class TestEvaluator(unittest.IsolatedAsyncioTestCase):

    def test_parse_func(self):
        func_str = "get ( key1 ) -> foreach -> get(key2)"
        funcs = Evaluator._parse_func(func_str)
        self.assertEqual(len(funcs), 3)
        self.assertDictEqual(funcs[0], {'name': 'get', 'args': ['key1']})
        self.assertDictEqual(funcs[1], {'name': 'foreach'})
        self.assertDictEqual(funcs[2], {'name': 'get', 'args': ['key2']})

    async def test_execute_1(self):
        evaluator = Evaluator(
            config={
                "func": "get(x) -> foreach -> get(y)"
            }
        )
        data = {"x": [{"y": 1}, {"y": 2}, {"y": 3}]}
        res = await evaluator.execute(data)
        self.assertEqual(len(res), 3)
        self.assertListEqual([r.result for r in res], [1, 2, 3])

    async def test_execute_2(self):
        evaluator = Evaluator(
            config={
                "func": "get(x) -> foreach -> get(y) -> len"
            }
        )
        data = {"x": [{"y": [1]}, {"y": [1, 1]}, {"y": [1, 2, 3, 4]}]}
        res = await evaluator.execute(data)
        self.assertEqual(len(res), 3)
        self.assertListEqual([r.result for r in res], [1, 2, 4])

    async def test_evaluate_1(self):
        evaluator = Evaluator(
            config={
                "func": "get(x) -> foreach -> get(y) -> len",
                "op": "=",
                "value": 2
            }
        )
        data = {"x": [{"y": [1, 2]}, {"y": [3, 4]}, {"y": [5, 6]}]}
        res = await evaluator.evaluate(data)
        self.assertEqual(res.passed, True)
        data = {"x": [{"y": [1, 2]}, {"y": [3, 4]}, {"y": [5, 6, 7]}]}
        res = await evaluator.evaluate(data)
        self.assertEqual(res.passed, False)

    async def test_evaluate_2(self):
        evaluator = Evaluator(
            config={
                "func": "json -> get(x) -> foreach -> get(y) -> len",
                "op": "=",
                "value": 2
            }
        )
        data = json.dumps({"x": [{"y": [1, 2]}, {"y": [3, 4]}, {"y": [5, 6]}]})
        res = await evaluator.evaluate(data)
        self.assertEqual(res.passed, True)

    async def test_set_environ_variables(self):
        config = EvaluatorConfig(
            func="raw",
            op="github.check_branches_exist",
            op_args={
                "owner": "{{GITHUB_PERSONAL_ACCOUNT_NAME}}",
                "repo": "travel-planner-app",
                "path": "README.md",
                "branches": ["main", "feature-maps", "feature-itinerary"]
            },
            value="{{ SOME_VALUE }}"
        )
        os.environ["GITHUB_PERSONAL_ACCOUNT_NAME"] = "abc"
        config.set_environ_variables()

        self.assertEqual(config.func, "raw")
        self.assertEqual(config.op, "github.check_branches_exist")
        self.assertEqual(config.value, "{{ SOME_VALUE }}")
        self.assertDictEqual(config.op_args, {
            "owner": "abc",
            "repo": "travel-planner-app",
            "path": "README.md",
            "branches": ["main", "feature-maps", "feature-itinerary"]
        })


if __name__ == "__main__":
    unittest.main()
