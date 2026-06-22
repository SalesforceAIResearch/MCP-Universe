"""
Evaluation functions for Google-maps tasks
"""
# pylint: disable=broad-exception-caught, unused-argument, consider-using-set-comprehension
import json
from typing import Any
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.evaluator.functions import compare_func


##################################################################################
# Utils Function for Google-Maps
##################################################################################
async def google_maps__search_place_by_query(query: str, **kwargs):
    """Search place by a query."""
    manager = MCPManager(context=kwargs.get("context", None))
    try:
        output = await manager.execute(
            server_name="google-maps",
            tool_name="maps_search_places",
            arguments={"query": query},
            transport="stdio"
        )
    except Exception as e:
        print(f"Error searching place: {e}")
        return None
    json_obj = json.loads(output.content[0].text)
    return json_obj


async def google_maps__search_place_by_place_id(query: str, place_id: str, **kwargs):
    """Search place by an ID."""
    manager = MCPManager(context=kwargs.get("context", None))
    try:
        output = await manager.execute(
            server_name="google-maps",
            tool_name="maps_search_places",
            arguments={"query": query},
            transport="stdio"
        )
    except Exception as e:
        print(f"Error searching place: {e}")
        return None
    json_obj = json.loads(output.content[0].text)
    places = json_obj['places']
    for place in places:
        if place['place_id'] == place_id:
            return place
    return None


async def google_maps__get_elevation_by_address(address: str, **kwargs):
    """Get the elevation of a place."""
    manager = MCPManager(context=kwargs.get("context", None))
    try:
        output = await manager.execute(
            server_name="google-maps",
            tool_name="maps_search_places",
            arguments={"query": address},
            transport="stdio"
        )
    except Exception as e:
        print(f"Error getting elevation: {e}")
        return None
    json_obj = json.loads(output.content[0].text)
    assert len(json_obj['places']) == 1, "the number of found place should be 1"
    lat = json_obj['places'][0]['location']['lat']
    lng = json_obj['places'][0]['location']['lng']
    print("lat, lng", address, lat, lng)

    # get elevation of a place given lat, lng
    try:
        output = await manager.execute(
            server_name="google-maps",
            tool_name="maps_elevation",
            arguments={"locations": [{"latitude": lat, "longitude": lng}]},
            transport="stdio"
        )
    except Exception as e:
        print(f"Error getting elevation: {e}")
        return None
    json_obj = json.loads(output.content[0].text)
    assert len(json_obj['results']) == 1, "the number of found place should be 1"
    elevation = json_obj['results'][0]['elevation']
    print("elevation", address, elevation)
    return elevation


async def google_maps__get_geocode_by_address(address: str, **kwargs):
    """Get the geocode of a place."""
    manager = MCPManager(context=kwargs.get("context", None))
    try:
        output = await manager.execute(
            server_name="google-maps",
            tool_name="maps_geocode",
            arguments={"address": address},
            transport="stdio"
        )
    except Exception as e:
        print(f"Error getting geocode: {e}")
        return None
    json_obj = json.loads(output.content[0].text)
    return json_obj


async def google_maps__get_place_details_by_place_id(place_id: str, **kwargs):
    """Get a place details by a place id."""
    manager = MCPManager(context=kwargs.get("context", None))
    try:
        output = await manager.execute(
            server_name="google-maps",
            tool_name="maps_place_details",
            arguments={"place_id": place_id},
            transport="stdio"
        )
    except Exception as e:
        print(f"Error getting place details: {e}")
        return None
    json_obj = json.loads(output.content[0].text)
    return json_obj


async def google_maps__measure_distance_and_duration_by_addresses_and_mode(
        place1: str, place2: str, mode: str, **kwargs
) -> tuple[bool, str | dict]:
    """Measure distance and duration by addresses and mode."""
    manager = MCPManager(context=kwargs.get("context", None))
    try:
        output = await manager.execute(
            server_name="google-maps",
            tool_name="maps_distance_matrix",
            arguments={
                "origins": [place1],
                "destinations": [place2],
                "mode": mode
            },
            transport="stdio"
        )
    except Exception as e:
        print(f"Error measuring distance and duration: {e}")
        return None
    json_obj = json.loads(output.content[0].text)
    return json_obj


##################################################################################
# Eval Function for Google-Maps
##################################################################################

@compare_func(name="google_maps.city_name_match")
async def google_maps_city_name_match(x: dict, *args, **kwargs) -> (bool, str):
    """Validate a google map places."""
    _, op_args = args
    city_name = x[op_args['key']]
    candidates = op_args['values']
    for candidate in candidates:
        if city_name.lower() in candidate.lower():
            return True, ""
    return False, "The city name doesn't match"


@compare_func(name="google_maps.validate_places")
async def google_maps_validate_places(x: dict, *args, **kwargs) -> (bool, str):
    """Validate a google map places."""
    place_type = args[1]['place_type']
    places = x[place_type]
    if not isinstance(places, list):
        places = [places]
    for place in places:
        place_id = place['place id']
        ret = await google_maps__get_place_details_by_place_id(place_id, **kwargs)
        if ret.isError:
            return False, f"the place {place_id} doesn't exists"
    return True, ""


@compare_func(name="google_maps.validate_number_of_routes")
async def google_maps_validate_number_of_routes(x: dict, *args, **kwargs) -> (bool, str):
    """Validate the number of google map routes."""
    value, _ = args
    places = x['routes']
    if not isinstance(places, list):
        places = [places]
    if len(places) == value:
        return True, ""
    return False, ""


@compare_func(name="google_maps.stop_include_keys")
async def google_maps_stop_include_keys(x: dict, *args, **kwargs) -> (bool, str):
    """Check if a stop has some key."""
    _, op_args = args
    for stop in x:
        for key in op_args['keys']:
            if not key in stop:
                return False, f"{key} must in stop"
    return True, ""


@compare_func(name="google_maps.is_a_validate_stop")
async def google_maps_is_a_validate_stop(x: dict, *args, **kwargs) -> (bool, str):
    """Check if a stop is valid."""
    for place in x:
        place_id = place['place id']
        res = await google_maps__get_place_details_by_place_id(place_id, **kwargs)
        if res is None:
            return False, f"the place {place_id} doesn't exists"
    return True, ""


@compare_func(name="google_maps.are_stops_different")
async def google_maps_are_stops_different(x: dict, *args, **kwargs) -> (bool, str):
    """Check if two routes have different stops."""
    route_1_stops_names = set([x["route_1_stops"][i]["name"] for i in range(len(x["route_1_stops"]))])
    route_1_stops_ids = set([x["route_1_stops"][i]["place id"] for i in range(len(x["route_1_stops"]))])
    route_2_stops_names = set([x["route_2_stops"][i]["name"] for i in range(len(x["route_2_stops"]))])
    route_2_stops_ids = set([x["route_2_stops"][i]["place id"] for i in range(len(x["route_2_stops"]))])
    if route_1_stops_names == route_2_stops_names and route_1_stops_ids == route_2_stops_ids:
        return False, "the stops are the same"
    return True, ""


@compare_func(name="google_maps.validate_stop_type")
async def google_maps_validate_stop_type(x: dict, *args, **kwargs) -> (bool, str):
    """Check if a stop has a valid type."""
    _, required_types = args
    for place in x:
        name = place['name']
        place_id = place['place id']
        details = await google_maps__search_place_by_place_id(name, place_id, **kwargs)
        if details is None:
            return False, f"Can't find the place: {name} {place_id}"
        types = details['types']
        validate_type = False
        for required_type in required_types:
            for t in types:
                if required_type in t:
                    validate_type = True
                    break
            if validate_type:
                break
        if not validate_type:
            return False, "The type of the place is not valid."
    return True, ""


@compare_func(name="google_maps.validate_location")
async def google_maps_validate_location(x: dict, *args, **kwargs) -> (bool, str):
    """Check if a stop has a valid type."""
    _, required_locations = args
    for place in x:
        name = place['name']
        for required_location in required_locations:
            if required_location.lower() in name.lower():
                return True, ""
    return False, "The location doesn't match"


@compare_func(name="google_maps.places_in_country")
async def google_maps_places_in_country(x: dict, *args, **kwargs) -> (bool, str):
    """Check if a place is in a country."""
    country = args[1]
    for place in x:
        place_name = place['name']
        place_id = place['place id']
        output = await google_maps__search_place_by_place_id(place_name, place_id, **kwargs)
        if output is None:
            return False, f"Can't find the place: {place_name} {place_id}"
        if not country.lower() in output["formatted_address"].lower():
            return False, f"{output['formatted_address']} is not in {country}"
    return True, ""


@compare_func(name="google_maps.places_in_countries")
async def google_maps_places_in_countries(x: dict, *args, **kwargs) -> (bool, str):
    """Check if a place is in a countries."""
    countries = args[1]
    for place in x:
        place_name = place['name']
        place_id = place['place id']
        output = await google_maps__search_place_by_place_id(place_name, place_id, **kwargs)
        if output is None:
            return False, f"Can't find the place: {place_name} {place_id}"
        for country in countries:
            if country.lower() in output["formatted_address"].lower():
                return True, ""
    return False, "The place is not in any of the countries"


@compare_func(name="google_maps.compare_time_of_middle_point")
async def google_maps_compare_time_to_middle_point(x: Any, *args, **kwargs) -> (bool, str):
    """Compare time of middle points."""
    if isinstance(x, list):
        assert len(x) == 1, "the length of stops should be one"
        stop_id = f"place_id:{x[0]['place id']}"
    elif isinstance(x, dict):
        stop_id = f"place_id:{x['place id']}"
    else:
        assert False, "the input is not a list or a dict"

    place1 = args[1]['place1']['place']
    place2 = args[1]['place2']['place']
    mode1 = args[1]['place1']['mode']
    mode2 = args[1]['place2']['mode']
    threshold = args[1]['threshold']

    duration1 = await google_maps__measure_distance_and_duration_by_addresses_and_mode(
        place1, stop_id, mode1, **kwargs)
    if duration1['results'][0]['elements'][0]['status'] in ['ZERO_RESULTS', 'NOT_FOUND']:
        return False, (
            f"can't measure distance or duration between {place1}, {stop_id}, "
            "this usually means the place is not found"
        )
    duration1 = duration1['results'][0]['elements'][0]['duration']['value']

    duration2 = await google_maps__measure_distance_and_duration_by_addresses_and_mode(
        place2, stop_id, mode2, **kwargs)
    if duration2['results'][0]['elements'][0]['status'] in ['ZERO_RESULTS', 'NOT_FOUND']:
        return False, (
            f"can't measure distance or duration between {place2}, {stop_id}, "
            "this usually means the place is not found"
        )
    duration2 = duration2['results'][0]['elements'][0]['duration']['value']

    if abs(duration1 - duration2) / duration1 > threshold:
        return False, "doesn't match the required duration"
    return True, ""


@compare_func(name="google_maps.validate_direction_of_two_places")
async def google_maps_validate_direction_of_two_places(x: dict, *args, **kwargs) -> (bool, str):
    """Validate directions of two places."""

    def _is_direction(place1, place2, direction):
        lat1, lon1 = place1
        lat2, lon2 = place2
        if direction == 'north':
            return lat1 > lat2
        if direction == 'south':
            return lat1 < lat2
        if direction == 'east':
            return lon1 > lon2
        if direction == 'west':
            return lon1 < lon2
        raise ValueError("Direction must be 'north', 'south', 'east', or 'west'")

    required_directions = args[1]
    for place1 in x:
        place1_details = await google_maps__search_place_by_place_id(place1['name'], place1['place id'], **kwargs)
        if place1_details is None:
            return False, f"Can't find the place: {place1['name']} {place1['place id']}"
        place1 = [place1_details['location']['lat'], place1_details['location']['lng']]
        for p in required_directions:
            place2_addr, direction = p['place'], p['direction']

            place2_details = await google_maps__search_place_by_query(place2_addr, **kwargs)
            place2_details = place2_details["places"][0]

            place2 = [place2_details['location']['lat'], place2_details['location']['lng']]
            if not _is_direction(place1, place2, direction):
                return False, f"the direction from {place2} to {place1} is wrong"
    return True, ""


@compare_func(name="google_maps.places_in_cities_visited")
async def google_maps_rest_stops_in_cities_visited(x: dict, *args, **kwargs) -> (bool, str):
    """Check if places in the visited cities."""
    _, op_args = args
    place_type = op_args
    for route in x['routes']:
        cities_visited = route['cities_visited']
        places = route[place_type]
        for place in places:
            if not place['city'] in cities_visited:
                return False, f"city[{place['city']}] is not in {place_type}[{cities_visited}]"
    return True, ""


@compare_func(name="google_maps.city_different_from_rest_stops")
async def google_maps_city_different_from_rest_stops(x: dict, *args, **kwargs) -> (bool, str):
    """Check if places in the visited cities."""
    for route in x['routes']:
        rest_stops = route['rest_stops']
        scenic_viewpoints = route['scenic_viewpoints']
        rest_stop_cities = set(rest_stop['city'].lower() for rest_stop in rest_stops)
        scenic_viewpoint_cities = set(
            scenic_viewpoint['city'].lower() for scenic_viewpoint in scenic_viewpoints
        )
        if rest_stop_cities == scenic_viewpoint_cities:
            return False, (f"rest_stop_cities[{rest_stop_cities}] "
                           f"and scenic_viewpoint_cities[{scenic_viewpoint_cities}] are the same")
    return True, ""


@compare_func(name="google_maps.validate_elevation_meters")
async def google_maps_validate_elevation_meters_of_scenic_viewpoints(x: dict, *args, **kwargs) -> (bool, str):
    """
    Validate the elevation.
    Example of llm return output:
        {
            "routes": [
                "scenic_viewpoints": [
                    {
                        "name": str,
                        "city": str,
                        "address": str,
                        "elevation_meters": int
                    }
                ]
            ]
        }
    """
    for route in x['routes']:
        for scenic_viewpoint in route['scenic_viewpoints']:
            name = scenic_viewpoint['name']
            city = scenic_viewpoint['city']
            address = scenic_viewpoint['address']
            elevation = scenic_viewpoint['elevation_meters']
            gt_elevation = await google_maps__get_elevation_by_address(address, **kwargs)
            if gt_elevation is None:
                return False, f"can't get the elevation of {name} in {city} at {address}"
            print(f"{name}, {city}, {address}, elevation: {float(elevation):.2f}, "
                  f"gt elevation: {float(gt_elevation):.2f}")

            if abs(float(elevation) - float(gt_elevation)) / abs(float(gt_elevation)) >= 0.05:
                return False, (f"the returned elevation of {name} in {city} at {address} "
                               f"is {float(elevation):.2f}, while gt = {float(gt_elevation):.2f}")
    return True, ""


@compare_func(name="google_maps.place_in_cities_visited_of_routes")
async def google_maps_place_in_cities_visited_of_routes(x: dict, *args, **kwargs) -> (bool, str):
    """Check if a place is in a route."""
    _, places = args
    for route in x['routes']:
        cities_visited = route['cities_visited']
        cities_visited = [x.lower() for x in cities_visited]
        flag = False
        for city in cities_visited:
            for place in places:
                if place.lower() in city:
                    flag = True
                    break
            if flag:
                break
        if not flag:
            return False, "city must be in all routes"
    return True, ""


@compare_func(name="google_maps.place_not_in_cities_visited_of_routes")
async def google_maps_place_not_in_cities_visited_of_routes(x: dict, *args, **kwargs) -> (bool, str):
    """Check if a place is not in a route."""
    _, place = args
    for route in x['routes']:
        cities_visited = route['cities_visited']
        cities_visited = [x.lower() for x in cities_visited]
        if place.lower() in cities_visited:
            return False, f"city {place} must not be in all routes"
    return True, ""


@compare_func(name="google_maps.include_one_place_in_rest_stops")
async def google_maps_include_one_place_in_rest_stops(x: dict, *args, **kwargs) -> (bool, str):
    """Check if including one place in the rest stops."""
    _, op_args = args
    required_city = op_args['city']

    for route in x['routes']:
        validated = False
        for rest_stop in route['rest_stops']:
            city = rest_stop['city']
            if city.lower() == required_city.lower():
                validated = True
                break
        if not validated:
            return False, ""
    return True, ""


@compare_func(name="google_maps.at_least_unique_city_of_rest_stops_in_routes")
async def google_maps_at_least_unique_city_of_rest_stops_in_routes(x: dict, *args, **kwargs) -> (bool, str):
    """Check if there is at least one unique city."""
    _, op_args = args
    for route in x['routes']:
        cities = []
        for rest_stop in route['rest_stops']:
            cities.append(rest_stop['city'].lower())
        if len(list(set(cities))) < op_args:
            return False, f"unique cities number: {len(list(set(cities)))}, required number is {op_args}"
    return True, ""


@compare_func(name="google_maps.validate_stop_rating")
async def google_maps_validate_stop_rating(x: dict | list, *args, **kwargs) -> (bool, str):
    """Validate stop rating."""
    _, required_rating = args
    if isinstance(x, dict):
        x = [x]

    for place in x:
        name = place['name']
        place_id = place['place id']
        details = await google_maps__search_place_by_place_id(name, place_id, **kwargs)
        if details is None:
            return False, f"Can't find the place: {name} {place_id}"
        rating = details['rating']
        if rating < required_rating:
            return False, f"Rating of stop {name} is {rating}, while the required rating is {required_rating}"
    return True, ""


@compare_func(name="google_maps.compare_distance_between_stops")
async def google_maps_compare_distance_between_stops(x: dict, *args, **kwargs) -> (bool, str):
    """Compare distance between stops.
    Example of llm return output:
        [
            {
                "place id": "Place ID",
                "name": "Name"
            }
        ]
    """
    if len(x) == 0:
        return False, "there is no intermediate stop, the input should be a list"
    stops = [f"place_id:{item['place id']}" for item in x]
    place1 = args[1]['place1']
    place2 = args[1]['place2']
    mode = args[1]['mode']
    threshold = args[1]['threshold']

    stops = [place1] + stops + [place2]
    distances = []
    for stop_idx in range(0, len(stops) - 1):
        stop1 = stops[stop_idx]
        stop2 = stops[stop_idx + 1]
        dis_and_time = await google_maps__measure_distance_and_duration_by_addresses_and_mode(
            stop1, stop2, mode, **kwargs)
        if dis_and_time is None:
            return False, (
                f"can't measure distance or time between {stop1}, {stop2}, "
                "it usually means the place is not found"
            )
        if dis_and_time['results'][0]['elements'][0]['status'] in ['ZERO_RESULTS', 'NOT_FOUND']:
            return False, f"can't measure distance or time between {stop1}, {stop2}"
        distances.append(dis_and_time['results'][0]['elements'][0]['distance']['value'])

    if (max(distances) - min(distances)) / min(distances) > threshold:
        return False, "doesn't match the required distance"
    return True, ""


@compare_func(name="google_maps.compare_distance_with_and_wo_stops")
async def google_maps_compare_distance_with_and_wo_stops(x: dict, *args, **kwargs) -> (bool, str):
    """Compare distance with/without stops."""
    if len(x) == 0:
        return False, "there is no intermediate stop, the input should be a list"
    stops = [f"place_id:{item['place id']}" for item in x]
    place1 = args[1]['place1']
    place2 = args[1]['place2']
    mode = args[1]['mode']
    threshold = args[1]['threshold']

    stops = [place1] + stops + [place2]
    distances = []
    for stop_idx in range(0, len(stops) - 1):
        stop1 = stops[stop_idx]
        stop2 = stops[stop_idx + 1]
        dis_and_time = await google_maps__measure_distance_and_duration_by_addresses_and_mode(
            stop1, stop2, mode, **kwargs)
        if dis_and_time['results'][0]['elements'][0]['status'] in ['ZERO_RESULTS', 'NOT_FOUND']:
            return False, (
                f"can't measure distance or time between {stop1}, {stop2}, "
                "this usually means the place is not found"
            )
        distances.append(dis_and_time['results'][0]['elements'][0]['distance']['value'])

    ret = await google_maps__measure_distance_and_duration_by_addresses_and_mode(
        place1, place2, mode, **kwargs)
    if ret['results'][0]['elements'][0]['status'] in ['ZERO_RESULTS', 'NOT_FOUND']:
        return False, (
            f"can't measure distance or time between {stop1}, {stop2}, "
            "this usually means the place is not found"
        )
    dis_wo_stops = ret['results'][0]['elements'][0]['distance']['value']
    dis_with_stops = sum(distances)

    if abs(dis_with_stops - dis_wo_stops) / dis_wo_stops > threshold:
        return False, "doesn't match the required distance"
    return True, ""


@compare_func(name="google_maps.check_places_and_ratings")
async def google_maps_check_places_and_ratings(x: dict, *args, **kwargs) -> (bool, str):
    """Check places and ratings.
    Example of llm return output:
        {"Merlion Park": 4.5, "Garden by the Bay": 4.3, "Marina Bay Sands": 4.2, 
        "China Town": 4.1, "Sentosa Island": 4.0}
    """
    _, op_args = args
    places = op_args['places']
    min_rating = op_args['min_rating']
    location = op_args['location']

    ground_truth = {}
    for place in places:
        details = await google_maps__search_place_by_query(f"{place}, {location}", **kwargs)
        if details is None:
            return False, f"Can't find the place: {place}"
        place_details = details['places'][0]
        rating = place_details.get("rating", 0)
        if rating > min_rating:
            ground_truth[place] = rating

    # check if the llm return output is the same as the ground truth, no order
    if set(x.keys()) != set(ground_truth.keys()):
        return False, f"the places are not the same, llm_response: {x}, ground_truth: {ground_truth}"
    for place in x:
        if x[place] != ground_truth[place]:
            return False, f"Rating of {place} is {x[place]}, while the required rating is {ground_truth[place]}"
    return True, ""
