import unittest
import pytest
from mcpuniverse.evaluator.google_maps.functions import *


class TestFunctionsExtra(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test_func1(self):
        elevation = await google_maps__get_elevation_by_address("Singapore")
        print(elevation)

    @pytest.mark.skip
    async def test_func2(self):
        geocode = await google_maps__get_geocode_by_address("Singapore Salesforce")
        print(geocode)

    @pytest.mark.skip
    async def test_func3(self):
        salesforce_place_id = 'ChIJE9n1qK8Z2jERgkFYBuW3fCk'
        details = await google_maps__get_place_details_by_place_id(salesforce_place_id)
        print(details)

    @pytest.mark.skip
    async def test_func4(self):
        distance_and_time = await google_maps__measure_distance_and_duration_by_addresses_and_mode(
            place1="Salesforce Singapore",
            place2="National University of Singapore",
            mode="driving"
        )
        print(distance_and_time)


if __name__ == "__main__":
    unittest.main()
