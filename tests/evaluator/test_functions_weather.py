import unittest
import pytest
from mcpuniverse.evaluator.weather.functions import *


class TestFunctionsExtra(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test_func1(self):
        x = {'stops': [{'name': 'Ripple Cafe', 'place id': 'UNKNOWN', 'place type': 'park'}]}
        forecast, _ = await weather_check_place_type_with_multiple_weather(
            x,
            {
                "night_or_not": False,
                "condition_type": "rain_or_not",
                "condition_value": "",
                "options": ["restaurant", "park"],
                "geocode_1": {
                    "latitude": 40.7489,
                    "longitude": -73.9862
                },
                "geocode_2": {
                    "latitude": 41.8787,
                    "longitude": -87.6360
                }
            }
        )
        print(forecast)


if __name__ == "__main__":
    unittest.main()
