import os
import json
import unittest
from mcpuniverse.benchmark.task import Task, TaskCleanupConfig, TaskConfig
from mcpuniverse.tracer.types import TraceRecord, DataRecord


class TestTask(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.folder = os.path.dirname(os.path.realpath(__file__))

    async def test_init(self):
        config_file = os.path.join(self.folder, "../data/task/google-map_task_0001.json")
        task = Task(config_file)
        self.assertEqual(len(task.get_mcp_servers()), 1)
        self.assertEqual(len(task.get_evaluators()), 3)

    async def test_evaluate(self):
        config_file = os.path.join(self.folder, "../data/task/google-map_task_0001.json")
        task = Task(config_file)
        data = {
            "starting_city": "Johor Bahru",
            "destination_city": "Kuala Lumpur",
            "routes": [
                {
                    "route_id": "1",
                    "cities_visited": [
                        "[City 1]",
                        "[City 2]",
                        "[City 3]"
                    ],
                    "total_distance_km": "[Estimated Distance in km]",
                    "total_travel_time_hours": "[Estimated Travel Time in hours]"
                },
                {
                    "route_id": "2",
                    "cities_visited": [
                        "[City 1]",
                        "[City 2]",
                        "[City 3]"
                    ],
                    "total_distance_km": "[Estimated Distance in km]",
                    "total_travel_time_hours": "[Estimated Travel Time in hours]"
                }
            ],
            "rest_stops": [
                {
                    "city": "[Specific City]",
                    "rest_stop_id": "1",
                    "name": "[Rest Stop Name]",
                    "address": "[Rest Stop Address]",
                    "amenities": [
                        "[Amenity 1]",
                        "[Amenity 2]",
                        "..."
                    ]
                },
                {
                    "city": "[Specific City]",
                    "rest_stop_id": "2",
                    "name": "[Rest Stop Name]",
                    "address": "[Rest Stop Address]",
                    "amenities": [
                        "[Amenity 1]",
                        "[Amenity 2]",
                        "..."
                    ]
                }
            ]
        }
        results = await task.evaluate(json.dumps(data))
        self.assertEqual(len(results), 3)
        self.assertTrue(results[0].passed)
        self.assertTrue(results[1].passed)
        self.assertTrue(results[2].passed)

    async def test_cleanup_1(self):
        config_file = os.path.join(self.folder, "../data/task/google-map_task_0001.json")
        task = Task(config_file)
        trace_records = [
            TraceRecord(
                id="123",
                trace_id="abc",
                parent_id="abc",
                running_time=1,
                timestamp=1,
                span_index=0,
                records=[
                    DataRecord(
                        timestamp=1,
                        data={
                            "server": "google-maps",
                            "tool_name": "maps_search_places",
                            "arguments": {"query": "Singapore"},
                            "response": {"content": [{"annotations": None, "text": "Singapore", "type": "text"}]},
                            "type": "tool"
                        }
                    ),
                    DataRecord(
                        timestamp=2,
                        data={
                            "server": "google-maps",
                            "tool_name": "maps_reverse_geocode",
                            "arguments": {"latitude": 37.7749, "longitude": -122.4194},
                            "response": {"content": [{"annotations": None, "text": "San Francisco", "type": "text"}]},
                            "type": "tool"
                        }
                    )
                ]
            )
        ]
        await task.reset(trace_records)

    async def test_cleanup_2(self):
        config_file = os.path.join(self.folder, "../data/task/weather_task.json")
        task = Task(config_file)
        trace_records = [
            TraceRecord(
                id="123",
                trace_id="abc",
                parent_id="abc",
                running_time=1,
                timestamp=1,
                span_index=0,
                records=[
                    DataRecord(
                        timestamp=1,
                        data={
                            "server": "weather",
                            "tool_name": "get_forecast",
                            "arguments": {"latitude": 37.7749, "longitude": -122.4194},
                            "response": {"content": [{"annotations": None, "text": "Singapore", "type": "text"}]},
                            "type": "tool"
                        }
                    )
                ]
            )
        ]
        await task.reset(trace_records)

    async def test_execute_reset(self):
        config_file = os.path.join(self.folder, "../data/task/google-map_task_0001.json")
        task = Task(config_file)
        cleanup_config = TaskCleanupConfig(
            server="google-maps",
            tool="maps_reverse_geocode",
            cleanup_func="cleanup",
            cleanup_args={"name": {"content": "$return -> get(content) -> array(0) -> get(text)"}}
        )
        res = await task._execute_reset(cleanup_config, tool_call={
            "server": "google-maps",
            "tool_name": "maps_reverse_geocode",
            "arguments": {"latitude": 37.7749, "longitude": -122.4194},
            "response": {"content": [{"annotations": None, "text": "San Francisco", "type": "text"}]},
            "type": "tool"
        })
        self.assertDictEqual(res, {"name": {"content": "San Francisco"}})

    async def test_set_environ_variables(self):
        config = TaskConfig(
            category="test",
            question="{{ACCOUNT_NAME}}"
        )
        self.assertEqual(config.question, "{{ACCOUNT_NAME}}")

        os.environ["ACCOUNT_NAME"] = "abc"
        config.set_environ_variables()
        self.assertEqual(config.question, "abc")


if __name__ == "__main__":
    unittest.main()
