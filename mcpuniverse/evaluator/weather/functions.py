"""
Evaluation functions for Google-maps tasks
"""
# pylint: disable=broad-exception-caught,unused-argument,too-many-return-statements
from typing import Any
import httpx
from mcpuniverse.evaluator.functions import compare_func
from mcpuniverse.evaluator.google_maps.functions import google_maps__search_place_by_place_id

##################################################################################
# Utils Function for Weather
##################################################################################
NWS_API_BASE = "https://api.weather.gov"
USER_AGENT = "weather-app/1.0"


async def weather__make_nws_request(url: str) -> dict[str, Any] | None:
    """Make a request to the NWS API with proper error handling."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/geo+json"
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None


async def weather__get_forecast(latitude: float, longitude: float) -> str:
    """
    Get weather forecast for a location.

    Args:
        latitude: Latitude of the location
        longitude: Longitude of the location
    """
    # First get the forecast grid endpoint
    points_url = f"{NWS_API_BASE}/points/{latitude:.4f},{longitude:.4f}"
    points_data = await weather__make_nws_request(points_url)

    if not points_data:
        return None

    # Get the forecast URL from the points response
    forecast_url = points_data["properties"]["forecast"]
    forecast_data = await weather__make_nws_request(forecast_url)

    if not forecast_data:
        return None

    # Format the periods into a readable forecast
    periods = forecast_data["properties"]["periods"]
    forecasts = {}
    for period in periods[:5]:  # Only show next 5 periods
        forecasts[period['name']] = {
            "temperature": period['temperature'],
            "temperature_unit": period['temperatureUnit'],
            "wind": f"{period['windSpeed']} {period['windDirection']}",
            "forecast": period['detailedForecast']
        }

    return forecasts


async def weather__find_tomorrow_rain_or_not_by_query(
        latitude: float, longitude: float, night_or_not: bool) -> (bool, str):
    """Check if tomorrow has rain or not."""
    try:
        forecasts = await weather__get_forecast(latitude, longitude)
    except Exception as e:
        return False, f"Failed to retrieve weather forecast for coordinates ({latitude}, {longitude}): {e}"

    if forecasts is None:
        return False, "Weather forecast data is unavailable for the specified location"

    # Find the next appropriate forecast period
    target_period_key = None
    c = 0
    for period_name in forecasts:
        if "night" not in period_name.lower() and c > 0:
            target_period_key = period_name
            break
        c += 1
    # Adjust for night conditions if specified
    if night_or_not:
        target_period_key = f"{target_period_key} Night"

    # Determine if rain is expected
    forecast_text = forecasts[target_period_key]["forecast"].lower()
    is_rain_expected = False
    if "rain" in forecast_text or "shower" in forecast_text or "thunderstorm" in forecast_text:
        is_rain_expected = True
    return is_rain_expected, ""


async def weather__find_tomorrow_higher_temperature_by_query(
        latitude: float, longitude: float, night_or_not: bool, condition_value: float) -> (bool, str):
    """Find temperature tomorrow."""
    try:
        forecasts = await weather__get_forecast(latitude, longitude)
    except Exception as e:
        return False, f"Failed to retrieve weather forecast for coordinates ({latitude}, {longitude}): {e}"

    if forecasts is None:
        return False, "Weather forecast data is unavailable for the specified location"

    # Find the next appropriate forecast period
    target_period_key = None
    c = 0
    for period_name in forecasts:
        if "night" not in period_name.lower() and c > 0:
            target_period_key = period_name
            break
        c += 1

    # Adjust for night conditions if specified
    if night_or_not:
        target_period_key = f"{target_period_key} Night"

    # Determine if rain is expected
    temperature = float(forecasts[target_period_key]["temperature"])
    if temperature > condition_value:
        return True, ""
    return False, ""


##################################################################################
# Eval Function for Weather
##################################################################################

@compare_func(name="weather.check_place_type_with_weather")
async def weather_check_place_type_with_weather(x: dict, *args, **kwargs) -> (bool, str):
    """
    Validate weather conditions for a specific place type for tomorrow (optional night).
    
    This function checks if weather conditions are suitable for a given park type
    based on rainfall predictions and time of day preferences.
    
    Args:
        x: Input data dictionary
        *args: Variable arguments containing operation parameters
        **kwargs: Keyword arguments
        
    Returns:
        tuple: (bool, str) - Success status and error message if applicable
    """
    _, op_args = args
    condition_type = op_args['condition_type']
    condition_value = op_args['condition_value']
    night_or_not = op_args['night_or_not']
    options = op_args['options']
    latitude = op_args['latitude']
    longitude = op_args['longitude']

    place_type = x['stops'][0]['place type']
    name = x['stops'][0]['name']
    place_id = x['stops'][0]['place id']

    if condition_type == "rain_or_not":
        # Determine if rain is expected
        is_expected, msg = await weather__find_tomorrow_rain_or_not_by_query(latitude, longitude, night_or_not)
    elif condition_type == "temperature_higher_than":
        # Determine if temperature is higher than the condition value
        is_expected, msg = await weather__find_tomorrow_higher_temperature_by_query(latitude, longitude, night_or_not,
                                                                                    condition_value)
    else:
        return False, f"Invalid condition type: {condition_type}"

    if msg != "":
        return False, msg

    # Select appropriate option based on weather conditions
    selected_option = options[0] if is_expected else options[1]

    # Check if the selected option matches the park type
    if selected_option not in place_type.lower():
        return False, "Weather conditions do not match the recommended place type"

    # Get place details to validate type
    details = await google_maps__search_place_by_place_id(name, place_id, **kwargs)
    if details is None:
        return False, f"Can't find the place: {name} {place_id}"

    # Check if place type matches requirement
    types = details['types']
    for p_type in types:
        if selected_option in p_type:
            return True, ""

    return False, "Place type does not match weather conditions requirement"


@compare_func(name="weather.check_place_type_with_multiple_weather")
async def weather_check_place_type_with_multiple_weather(x: dict, *args, **kwargs) -> (bool, str):
    """
    Validate weather conditions for a specific place type for tomorrow (optional night).
    
    This function checks if weather conditions are suitable for a given park type
    based on rainfall predictions and time of day preferences.
    
    Args:
        x: Input data dictionary
        *args: Variable arguments containing operation parameters
        **kwargs: Keyword arguments
        
    Returns:
        tuple: (bool, str) - Success status and error message if applicable
    """
    _, op_args = args
    condition_type = op_args['condition_type']
    condition_value = op_args['condition_value']
    night_or_not = op_args['night_or_not']
    options = op_args['options']
    geocode_1 = op_args['geocode_1']
    geocode_2 = op_args['geocode_2']

    place_type = x['stops'][0]['place type']
    name = x['stops'][0]['name']
    place_id = x['stops'][0]['place id']

    if condition_type == "rain_or_not":
        # Determine if rain is expected
        is_expected_1, msg_1 = await weather__find_tomorrow_rain_or_not_by_query(geocode_1['latitude'],
                                                                                 geocode_1['longitude'], night_or_not)
        is_expected_2, msg_2 = await weather__find_tomorrow_rain_or_not_by_query(geocode_2['latitude'],
                                                                                 geocode_2['longitude'], night_or_not)
        if msg_1 != "" or msg_2 != "":
            return False, msg_1 + "\n" + msg_2
        is_expected = is_expected_1 and is_expected_2
        msg = ""
    elif condition_type == "temperature_higher_than":
        # Determine if temperature is higher than the condition value
        is_expected_1, msg_1 = await weather__find_tomorrow_higher_temperature_by_query(geocode_1['latitude'],
                                                                                        geocode_1['longitude'],
                                                                                        night_or_not, condition_value)
        is_expected_2, msg_2 = await weather__find_tomorrow_higher_temperature_by_query(geocode_2['latitude'],
                                                                                        geocode_2['longitude'],
                                                                                        night_or_not, condition_value)
        if msg_1 != "" or msg_2 != "":
            return False, msg_1 + "\n" + msg_2
        is_expected = is_expected_1 and is_expected_2
        msg = ""
    else:
        return False, f"Invalid condition type: {condition_type}"

    if msg != "":
        return False, msg

    # Select appropriate option based on weather conditions
    selected_option = options[0] if is_expected else options[1]

    # Check if the selected option matches the park type
    if selected_option not in place_type.lower():
        return False, "Weather conditions do not match the recommended place type"

    # Get place details to validate type
    details = await google_maps__search_place_by_place_id(name, place_id, **kwargs)
    if details is None:
        return False, f"Can't find the place: {name} {place_id}"

    # Check if place type matches requirement
    types = details['types']
    for p_type in types:
        if selected_option in p_type:
            return True, ""

    return False, "Place type does not match weather conditions requirement"
