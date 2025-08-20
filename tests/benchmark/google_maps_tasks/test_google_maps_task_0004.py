import json
import pytest
import unittest
from mcpuniverse.benchmark.task import Task


class TestTask(unittest.TestCase):

    @pytest.mark.skip
    def test_evaluate(self):
        task = Task("mcpuniverse/benchmark/configs/test/google_maps/google_maps_task_0004.json")
        data = {
            "starting_city": "Johor Bahru",
            "destination_city": "Kuala Lumpur",
            "routes": [
                {
                    "route_id": "1",
                    "route_name": "Coastal Heritage Route",
                    "cities_visited": [
                        "Batu Pahat",
                        "Muar",
                        "Malacca",
                        "Port Dickson"
                    ],
                    "rest_stops": [
                        {
                            "city": "Bentong",
                            "rest_stop_id": "1",
                            "name": "Ayer Keroh Rest House",
                            "address": "Alor Gajah, 78000 Malacca, Malaysia",
                            "amenities": [
                                "Restrooms",
                                "Food Court",
                                "Parking"
                            ]
                        }
                    ],
                    "scenic_viewpoints": [
                        {
                            "city": "Port Dickson",
                            "viewpoint_id": "1",
                            "name": "Cape Rachado Lighthouse Viewpoint",
                            "elevation_meters": "20",
                            "description": "With ocean views and historic lighthouse, it offers stunning coastal scenery."
                        }
                    ]
                },
                {
                    "route_id": "2",
                    "route_name": "Inland Cultural Route",
                    "cities_visited": [
                        "Kluang",
                        "Segamat",
                        "Malacca",
                        "Seremban"
                    ],
                    "rest_stops": [
                        {
                            "city": "Bentong",
                            "rest_stop_id": "1",
                            "name": "Kluang Railway Coffee",
                            "address": "Jalan Station, 86000 Kluang, Johor, Malaysia",
                            "amenities": [
                                "Coffee",
                                "Snacks",
                                "Local Cuisine"
                            ]
                        }
                    ],
                    "scenic_viewpoints": [
                        {
                            "city": "Seremban",
                            "viewpoint_id": "1",
                            "name": "Bukit Kepayang Lookout",
                            "elevation_meters": "92",
                            "description": "A panoramic view of Seremban city and its surroundings."
                        }
                    ]
                },
                {
                    "route_id": "3",
                    "route_name": "Nature Explorer's Route",
                    "cities_visited": [
                        "Pontian",
                        "Simpang Renggam",
                        "Muadzam Shah",
                        "Bentong"
                    ],
                    "rest_stops": [
                        {
                            "city": "Bentong",
                            "rest_stop_id": "1",
                            "name": "Bentong Hot Springs",
                            "address": "28700 Bentong, Pahang, Malaysia",
                            "amenities": [
                                "Natural Pool",
                                "Changing Rooms",
                                "Parking"
                            ]
                        }
                    ],
                    "scenic_viewpoints": [
                        {
                            "city": "Bentong",
                            "viewpoint_id": "1",
                            "name": "Chamang Waterfall",
                            "elevation_meters": "57",
                            "description": "A picturesque waterfall with lush surroundings perfect for relaxation."
                        },
                        {
                            "city": "Bentong",
                            "viewpoint_id": "1",
                            "name": "Chamang Waterfall",
                            "elevation_meters": "57",
                            "description": "A picturesque waterfall with lush surroundings perfect for relaxation."
                        }
                    ]
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
