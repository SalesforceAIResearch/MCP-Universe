"""
Evaluation functions for playwright tasks
"""
# pylint: disable=unused-argument,line-too-long
from datetime import datetime, timedelta
import re
import asyncio
from typing import Literal
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from mcpuniverse.evaluator.notion.functions import notion__get_content_by_page_title
from mcpuniverse.evaluator.functions import compare_func


##################################################################################
# Utils Function for PlayWright
##################################################################################
def playwright__is_dict_equal(dict_a: dict, dict_b: dict) -> bool:
    """
    Check whether two dictionaries are equal (have the same key-value pairs).
    Order of keys doesn't matter.

    Args:
        dict_a: The first dictionary to compare
        dict_b: The second dictionary to compare

    Returns:
        bool: True if both dictionaries have the same key-value pairs, False otherwise
    """
    # Check if they have the same number of keys
    if len(dict_a) != len(dict_b):
        return False

    # Check if all key-value pairs in dict_a are also in dict_b
    # Since we already verified they have the same length, this is sufficient
    for key, value in dict_a.items():
        if key not in dict_b or dict_b[key] != value:
            return False

    return True


def playwright__extract_numeric_price(price_string: str) -> tuple[float, str]:
    """
    Extract numeric price and currency from a price string like "SGD40.00" or "HK$1,234.56"
    
    Args:
        price_string: Price string in format "CURRENCY+PRICE" like "SGD40.00"
        
    Returns:
        tuple: (numeric_price, currency) where numeric_price is float and currency is str
    """
    if not price_string:
        return 0.0, ""

    # Extract currency using a more comprehensive approach
    # Look for currency symbols, codes, or any non-numeric prefix
    currency = ""

    # First, try to match common currency patterns
    currency_patterns = [
        r'([A-Z]{3})',  # 3-letter currency codes
        r'([A-Z]{2})',  # 2-letter currency codes
    ]

    for pattern in currency_patterns:
        currency_match = re.match(pattern, price_string)
        if currency_match:
            currency = currency_match.group(1)
            break

    # If no currency found with patterns, extract any non-numeric prefix
    if not currency:
        # Find the first numeric character and extract everything before it
        for i, char in enumerate(price_string):
            if char.isdigit():
                currency = price_string[:i].strip()
                break

    # Extract the numeric part (everything after the currency)
    numeric_part = price_string[len(currency):] if currency else price_string

    # Remove any remaining non-numeric characters except decimal point and comma
    numeric_match = re.search(r'[\d,]+\.?\d*', numeric_part.replace(',', ''))
    if numeric_match:
        return float(numeric_match.group()), currency

    return 0.0, currency


async def playwright__get_flight_price(
        depart_date: str,
        return_date: str,
        from_location: str,
        to_location: str,
        from_country: str,
        to_country: str,
        from_location_name: str,
        to_location_name: str,
        flight_type: Literal["ONEWAY", "ROUNDTRIP"],
        adults: int,
        children: int,
        stops: int,
        cabin_class: Literal["ECONOMY", "BUSINESS", "FIRST"],
        sort: Literal["CHEAPEST", "FASTEST", "BEST"],
        travel_purpose: Literal["leisure", "business"],
):
    """
    Visit booking.com flights page and extract the price from the first flight card.

    Args:
        depart_date: The date of the departure, format: YYYY-MM-DD

    Returns:
        str: The content of the price element, or None if not found
    """
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)  # Set to True for headless mode
        page = await browser.new_page()

        try:
            # convert parameters to url format
            url = (
                f"https://flights.booking.com/flights/{from_location}-{to_location}/?"
                f"type={flight_type}&"
                f"adults={'' if adults == 0 else adults}&"
                f"children={'' if children == 0 else children}&"
                f"cabinClass={cabin_class}&"
                f"from={from_location}&to={to_location}&fromCountry={from_country}&toCountry={to_country}&"
                f"fromLocationName={from_location_name}&toLocationName={to_location_name}&"
                f"depart={depart_date}&return={return_date}&sort={sort}&travelPurpose={travel_purpose}&stops={stops}"
            )

            print(f"Navigating to: {url}")
            await page.goto(url, wait_until="domcontentloaded")

            # Wait for the flight card element to appear
            print("Waiting for #flightcard-0 element...")
            await page.wait_for_selector("#flightcard-0", timeout=30000)  # 30 seconds timeout

            # Extract the price content from the specified selector
            price_selector = '#flightcard-0 [data-testid="upt_price"]'
            print(f"Looking for price element: {price_selector}")

            # Wait for the price element specifically
            await page.wait_for_selector(price_selector, timeout=10000)  # 10 seconds timeout

            # Get the text content of the price element
            price_element = await page.query_selector(price_selector)
            if price_element:
                # Get innerHTML instead of text_content directly
                price_html = await price_element.inner_html()

                # Use BeautifulSoup to parse and remove <s> tags
                soup = BeautifulSoup(price_html, 'html.parser')

                # Remove all <s> tags
                for s_tag in soup.find_all('s'):
                    s_tag.decompose()

                # Get the text content from the cleaned HTML
                price_content = soup.get_text()

                print(f"Found price: {price_content}")
                return price_content.strip() if price_content else None

            print("Price element not found")
            return None

        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Error occurred: {e}")
            return None

        finally:
            # Close the browser
            await browser.close()


async def playwright__get_flight_price_with_time(depart_date: str):
    """
    Visit booking.com flights page for LHR to CDG roundtrip and extract the price from the first flight card.
    Return date is automatically set to 6 days after departure date.

    Args:
        depart_date: The date of the departure, format: YYYY-MM-DD

    Returns:
        str: The content of the price element, or None if not found
    """
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)  # Set to True for headless mode
        page = await browser.new_page()

        try:
            # Calculate return date as 6 days after departure date
            depart_datetime = datetime.strptime(depart_date, "%Y-%m-%d")
            return_datetime = depart_datetime + timedelta(days=6)
            return_date = return_datetime.strftime("%Y-%m-%d")

            # Navigate to the booking.com flights URL for LHR to CDG roundtrip
            url = ("https://flights.booking.com/flights/LHR.AIRPORT-CDG.AIRPORT/"
                   "?type=ROUNDTRIP&adults=1&cabinClass=ECONOMY&children=&"
                   "from=LHR.AIRPORT&to=CDG.AIRPORT&fromCountry=GB&toCountry=FR&"
                   "fromLocationName=London+Heathrow+Airport&"
                   "toLocationName=Paris+-+Charles+de+Gaulle+Airport&"
                   f"depart={depart_date}&return={return_date}&sort=CHEAPEST&"
                   "travelPurpose=leisure&stops=0")

            print(f"Navigating to: {url}")
            print(f"Departure: {depart_date}, Return: {return_date}")
            await page.goto(url, wait_until="domcontentloaded")

            # Wait for the flight card element to appear
            print("Waiting for #flightcard-0 element...")
            await page.wait_for_selector("#flightcard-0", timeout=30000)  # 30 seconds timeout

            # Extract the price content from the specified selector
            price_selector = '#flightcard-0 [data-testid="upt_price"]'
            print(f"Looking for price element: {price_selector}")

            # Wait for the price element specifically
            await page.wait_for_selector(price_selector, timeout=10000)  # 10 seconds timeout

            # Get the text content of the price element
            price_element = await page.query_selector(price_selector)
            if price_element:
                # Get innerHTML instead of text_content directly
                price_html = await price_element.inner_html()

                # Use BeautifulSoup to parse and remove <s> tags
                soup = BeautifulSoup(price_html, 'html.parser')

                # Remove all <s> tags
                for s_tag in soup.find_all('s'):
                    s_tag.decompose()

                # Get the text content from the cleaned HTML
                price_content = soup.get_text()

                print(f"Found price: {price_content}")
                return price_content.strip() if price_content else None

            print("Price element not found")
            return None

        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Error occurred: {e}")
            return None

        finally:
            # Close the browser
            await browser.close()


async def playwright__get_hotel_price(checkin_date: str):
    """
    Visit booking.com hotel page and extract the price from the first hotel card.

    Args:
        checkin_date: The check-in date, format: YYYY-MM-DD

    Returns:
        str: The content of the price element, or None if not found
    """
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True, )  # Set to True for headless mode
        page = await browser.new_page()

        try:
            # Calculate checkout date as one day after checkin date
            checkin_datetime = datetime.strptime(checkin_date, "%Y-%m-%d")
            checkout_datetime = checkin_datetime + timedelta(days=1)
            checkin_date_formated = checkin_datetime.strftime("%Y/%m/%d")
            checkout_date_formated = checkout_datetime.strftime("%Y/%m/%d")

            # Navigate to the booking.com hotel URL
            url = (
                "https://www.trip.com/hotels/list?"
                "city=734&cityName=Kyoto&provinceId=11087&countryId=78&districtId=0&"
                f"checkin={checkin_date_formated}&"
                f"checkout={checkout_date_formated}&"
                "barCurr=HKD&searchType=CT&"
                "searchWord=Kyoto&searchValue=19~734*19*734*1&"
                "searchCoordinate=3_-1_-1_0~2_-1_-1_0~1_-1_-1_0~NORMAL_35.0116363_135.7680294_0&"
                "crn=1&adult=2&children=0&searchBoxArg=t&travelPurpose=0&ctm_ref=ix_sb_dl&domestic=true&"
                "listFilters=29~1*29*1~2*2%2C17~3*17*3%2C80~0~1*80*0*2%2C6~8*6*8*7%2B%2C3~664*3*664*Public%20baths%2C77~183*77*183*TV&"
                "locale=en-XX&curr=HKD"
            )

            print(f"Navigating to: {url}")
            print(f"Check-in: {checkin_date_formated}, Check-out: {checkout_date_formated}")
            await page.goto(url, wait_until="domcontentloaded")

            # Wait for the hotel card element to appear
            print('Waiting for #meta-real-price element...')
            await page.wait_for_selector('#meta-real-price', timeout=30000)  # 30 seconds timeout

            # Extract the price content from the specified selector
            price_selector = '#meta-real-price'
            print(f"Looking for price element: {price_selector}")

            # Wait for the price element specifically
            await page.wait_for_selector(price_selector, timeout=10000)  # 10 seconds timeout

            # Get the text content of the price element
            price_element = await page.query_selector(price_selector)
            if price_element:
                # Get innerHTML instead of text_content directly
                price_html = await price_element.inner_html()

                # Use BeautifulSoup to parse and remove <s> tags
                soup = BeautifulSoup(price_html, 'html.parser')

                # Remove all <s> tags
                for s_tag in soup.find_all('s'):
                    s_tag.decompose()

                # Get the text content from the cleaned HTML
                price_content = soup.get_text()

                print(f"Found price: {price_content}")

                if price_content is None:
                    return None

                price_content = price_content.strip()
                price_content = price_content \
                    .replace("&nbsp;", "") \
                    .replace(" ", "")
                price_content = price_content.replace("S$", "HK") \
                    .replace(",", "")

                return price_content

            print("Price element not found")
            return None

        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Error occurred: {e}")
            return None

        finally:
            # Close the browser
            await browser.close()


async def playwright__get_hotel_price_with_conditions(checkin_date: str, currency: str = "SGD"):
    """
    Visit booking.com hotel page for Sydney and extract the price from the first hotel card.
    Uses specific parameters for Sydney hotels with 4 adults, 2 rooms, 1 child.
    Checkout date is automatically set to 7 days after checkin date.

    Args:
        checkin_date: The check-in date, format: YYYY-MM-DD

    Returns:
        str: The content of the price element, or None if not found
    """
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)  # Set to True for headless mode
        page = await browser.new_page()

        try:
            # Calculate checkout date as 7 days after checkin date (2025-06-21 to 2025-06-28 is 7 days)
            checkin_datetime = datetime.strptime(checkin_date, "%Y-%m-%d")
            checkout_datetime = checkin_datetime + timedelta(days=7)
            checkout_date = checkout_datetime.strftime("%Y-%m-%d")

            # Navigate to the booking.com hotel URL for Sydney
            url = ("https://www.booking.com/searchresults.html?"
                   "ss=Sydney%2C+New+South+Wales%2C+Australia&"
                   "ssne=Kyoto&"
                   "ssne_untouched=Kyoto&"
                   "efdco=1&"
                   "lang=en-us&"
                   "dest_id=-1603135&"
                   "dest_type=city&"
                   "ac_position=0&"
                   "ac_click_type=b&"
                   "ac_langcode=en&"
                   "ac_suggestion_list_length=5&"
                   "search_selected=true&"
                   "search_pageview_id=26dd520834a00382&"
                   f"checkin={checkin_date}&"
                   f"checkout={checkout_date}&"
                   "group_adults=4&"
                   "no_rooms=2&"
                   "group_children=1&"
                   "age=6&"
                   "nflt=fc%3D2%3Bhotelfacility%3D8%3Bhotelfacility%3D28&"
                   "order=class&"
                   f"selected_currency={currency}")

            print(f"Navigating to: {url}")
            print(f"Check-in: {checkin_date}, Check-out: {checkout_date}")
            await page.goto(url, wait_until="domcontentloaded")

            # Wait for the hotel card element to appear
            print('Waiting for [data-testid="property-card"] element...')
            await page.wait_for_selector('[data-testid="property-card"]', timeout=30000)  # 30 seconds timeout

            # Extract the price content from the specified selector
            price_selector = '[data-testid="property-card"] [data-testid="price-and-discounted-price"]'
            print(f"Looking for price element: {price_selector}")

            # Wait for the price element specifically
            await page.wait_for_selector(price_selector, timeout=10000)  # 10 seconds timeout

            # Get the text content of the price element
            price_element = await page.query_selector(price_selector)
            if price_element:
                # Get innerHTML instead of text_content directly
                price_html = await price_element.inner_html()

                # Use BeautifulSoup to parse and remove <s> tags
                soup = BeautifulSoup(price_html, 'html.parser')

                # Remove all <s> tags
                for s_tag in soup.find_all('s'):
                    s_tag.decompose()

                # Get the text content from the cleaned HTML
                price_content = soup.get_text()

                print(f"Found price: {price_content}")

                if price_content is None:
                    return None

                price_content = price_content.strip()
                price_content = price_content \
                    .replace("&nbsp;", "") \
                    .replace(" ", "") \
                    .replace("\xa0", "")
                price_content = price_content.replace("S$", "SGD") \
                    .replace(",", "")

                return price_content

            print("Price element not found")
            return None

        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Error occurred: {e}")
            return None

        finally:
            # Close the browser
            await browser.close()


async def playwright__booking_com_get_hotel_price_with_lowest_price_highest_rating(
        city: str,
        group_adults: int,
        no_rooms: int,
        group_children: int,
        checkin_date: str,
        checkout_date: str,
        currency: str = "SGD",
        order: Literal["class", "price"] = "price"):
    """
    Visit booking.com hotel page and extract the price from the first hotel card.

    Args:
        checkin_date: The check-in date, format: YYYY-MM-DD
        checkout_date: The check-out date, format: YYYY-MM-DD
        currency: The currency to use, default: SGD, INR

    Returns:
        str: The content of the price element, or None if not found

    ToDO: combine with playwright__get_hotel_price_with_conditions
    """
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=False)  # Set to True for headless mode
        page = await browser.new_page()

        try:
            # Navigate to the booking.com hotel URL for Sydney
            url = ("https://www.booking.com/searchresults.html?"
                   f"ss={city}&"
                   "lang=en-us&"
                   "dest_type=city&"
                   f"checkin={checkin_date}&"
                   f"checkout={checkout_date}&"
                   "group_adults=1&"
                   "no_rooms=1&"
                   "group_children=0&"
                   "nflt=hotelfacility%3D8&"
                   f"order={order}&"
                   f"selected_currency={currency}")

            print(f"Navigating to: {url}")

            await page.goto(url, wait_until="domcontentloaded")

            # Wait for the hotel card element to appear
            print('Waiting for [data-testid="property-card"] element...')
            await page.wait_for_selector('[data-testid="property-card"]', timeout=30000)  # 30 seconds timeout

            title_selector = '[data-testid="property-card"] [data-testid="title"]'
            await page.wait_for_selector(title_selector, timeout=10000)  # 10 seconds timeout
            title_element = await page.query_selector(title_selector)
            if title_element:
                title_text = await title_element.text_content()
                print(f"Found title: {title_text}")

            # Extract the price content from the specified selector
            price_selector = '[data-testid="property-card"] [data-testid="price-and-discounted-price"]'
            print(f"Looking for price element: {price_selector}")

            # Wait for the price element specifically
            await page.wait_for_selector(price_selector, timeout=10000)  # 10 seconds timeout
            price_element = await page.query_selector(price_selector)
            if price_element:
                price_text = await price_element.text_content()
                print(f"Found price: {price_text}")
                price_text = price_text.replace('\\xa0', ' ')

            return title_text, price_text

        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Error occurred: {e}")
            return None

        finally:
            # Close the browser
            await browser.close()


async def playwright__get_rwsentosa_price_with_conditions(checkin_date: str, theme_park: str):
    """
    Visit RWSentosa attraction page and extract the price from the first hotel card.

    Args:
        checkin_date: The check-in date, format: YYYY-MM-DD
        theme_park: The theme park code
        adults: Number of adults
        children: Number of children

    Returns:
        dict: Dictionary containing adult and child prices, or None if not found
    """
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)  # Set to True for headless mode
        page = await browser.new_page()

        try:
            # Navigate to the RWSentosa attraction URL
            url = (f"https://www.rwsentosa.com/en/reservations/attraction-selection?ThemeParkCode={theme_park}"
                   f"&VisitDate={checkin_date}")

            print(f"Navigating to: {url}")
            await page.goto(url, wait_until="domcontentloaded")

            # Wait for the attraction booking widget elements to appear
            print('Waiting for .attraction-booking-widget__control .control-wrapper elements...')
            await page.wait_for_selector('.attraction-booking-widget__control .control-wrapper',
                                         timeout=30000)  # 30 seconds timeout

            # Find all control wrapper elements
            control_wrappers = await page.query_selector_all('.attraction-booking-widget__control .control-wrapper')

            if len(control_wrappers) >= 2:
                # Extract adult price from the first control wrapper
                adult_price_element = await control_wrappers[0].query_selector(
                    '.attraction-booking-widget__control__qty .rws__input-bottom-text .m-0 b')
                adult_price = None
                if adult_price_element:
                    adult_price = await adult_price_element.inner_html()
                    print(f"Found adult price: {adult_price}")

                # Extract child price from the second control wrapper
                child_price_element = await control_wrappers[1].query_selector(
                    '.attraction-booking-widget__control__qty .rws__input-bottom-text .m-0 b')
                child_price = None
                if child_price_element:
                    child_price = await child_price_element.inner_html()
                    print(f"Found child price: {child_price}")

                return {
                    "adult_price": adult_price,
                    "child_price": child_price
                }
            print(f"Expected 2 control wrapper elements, found {len(control_wrappers)}")
            return None

        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Error occurred: {e}")
            return None

        finally:
            # Close the browser
            await browser.close()


#################################################################################
# Eval Function for PlayWright
#################################################################################
@compare_func(name="playwright.is_dict_equal")
async def playwright_is_dict_equal(x: dict, *args, **kwargs) -> (bool, str):
    """Validate two dictionaries are equal."""
    value, _ = args

    dict_equal = playwright__is_dict_equal(x, value)
    if not dict_equal:
        return False, f"the dictionaries are not equal, llm response: {x}, expected: {value}"
    return True, ""


@compare_func(name="playwright.check_flight_price")
async def playwright_check_flight_price(x: dict, *args, **kwargs) -> (bool, str):
    """Check flight price by getting today's date and calculating departure date from op_args."""
    _, op_args = args
    llm_response = x.get("price", "")

    # Get today's date
    today = datetime.now().date()

    # Get parameters from op_args
    depart_days_after = op_args.get("depart_days_after", 0)
    return_days_after = op_args.get("return_days_after", None)
    flight_type = op_args.get("flight_type", "ONEWAY")
    cabin_class = op_args.get("cabin_class", "ECONOMY")
    adults = op_args.get("adults", 1)
    children = op_args.get("children", 0)
    stops = op_args.get("stops", 0)
    sort = op_args.get("sort", "CHEAPEST")
    travel_purpose = op_args.get("travel_purpose", "leisure")
    from_location = op_args.get("from_location", "")
    to_location = op_args.get("to_location", "")
    from_country = op_args.get("from_country", "")
    to_country = op_args.get("to_country", "")
    from_location_name = op_args.get("from_location_name", "")
    to_location_name = op_args.get("to_location_name", "")

    # Calculate departure date
    departure_date = today + timedelta(days=depart_days_after)
    depart_date_str = departure_date.strftime("%Y-%m-%d")

    print(f"Today: {today}, Days after: {depart_days_after}, Departure date: {depart_date_str}")

    return_date_str = ""
    if return_days_after is not None:
        return_date = departure_date + timedelta(days=return_days_after)
        return_date_str = return_date.strftime("%Y-%m-%d")
        print(f"Return days after: {return_days_after}, Return date: {return_date_str}")

    # Get the flight price
    price = await playwright__get_flight_price(
        depart_date=depart_date_str,
        return_date=return_date_str,
        flight_type=flight_type,
        cabin_class=cabin_class,
        adults=adults,
        children=children,
        stops=stops,
        sort=sort,
        travel_purpose=travel_purpose,
        from_location=from_location,
        to_location=to_location,
        from_country=from_country,
        to_country=to_country,
        from_location_name=from_location_name,
        to_location_name=to_location_name
    )

    # For now, just return success if we got a price
    # You can add more specific validation logic here based on your needs
    if price:
        print(f"Successfully retrieved flight price: {price}")
        print(f"Flight price retrieved: {price}")

        if price == llm_response:
            return True, ""

        return False, f"Flight price retrieved: {price}, expected: {llm_response}"

    return False, "Failed to retrieve flight price"


@compare_func(name="playwright.check_flight_price_with_time")
async def playwright_check_flight_price_with_time(x: dict, *args, **kwargs) -> (bool, str):
    """Check flight price with time by getting today's date and calculating departure date from op_args."""
    _, op_args = args
    llm_response = x.get("price", "")

    # Get today's date
    today = datetime.now().date()

    # Get days after today from op_args
    days_after = op_args.get("days_after", 0)

    # Calculate departure date
    departure_date = today + timedelta(days=days_after)
    depart_date_str = departure_date.strftime("%Y-%m-%d")

    print(f"Today: {today}, Days after: {days_after}, Departure date: {depart_date_str}")

    # Get the flight price with time (LHR to CDG roundtrip)
    price = await playwright__get_flight_price_with_time(depart_date_str)

    # For now, just return success if we got a price
    # You can add more specific validation logic here based on your needs
    if price:
        print(f"Successfully retrieved flight price with time: {price}")
        print(f"Flight price with time retrieved: {price}")

        if price == llm_response:
            return True, ""

        return False, f"Flight price with time retrieved: {price}, expected: {llm_response}"

    return False, "Failed to retrieve flight price with time"


@compare_func(name="playwright.check_hotel_price")
async def playwright_check_hotel_price(x: dict, *args, **kwargs) -> (bool, str):
    """Check hotel price by getting today's date and calculating check-in date from op_args."""
    _, op_args = args
    llm_response = x.get("price", "")

    # Get today's date
    today = datetime.now().date()

    # Get days after today from op_args
    days_after = op_args.get("days_after", 0)

    # Calculate check-in date
    checkin_date = today + timedelta(days=days_after)
    checkin_date_str = checkin_date.strftime("%Y-%m-%d")

    print(f"Today: {today}, Days after: {days_after}, Check-in date: {checkin_date_str}")

    # Get the hotel price
    price = await playwright__get_hotel_price(checkin_date_str)

    # For now, just return success if we got a price
    # You can add more specific validation logic here based on your needs
    if price:
        print(f"Successfully retrieved hotel price: {price}")
        print(f"Hotel price retrieved: {price}")

        if price == llm_response:
            return True, ""

        return False, f"Hotel price retrieved: {price}, expected: {llm_response}"

    return False, "Failed to retrieve hotel price"


@compare_func(name="playwright.check_hotel_price_with_conditions")
async def playwright_check_hotel_price_with_conditions(x: dict, *args, **kwargs) -> (bool, str):
    """Check hotel price with conditions by getting today's date and calculating check-in date from op_args."""
    _, op_args = args
    llm_response = x.get("price", "")

    # Get today's date
    today = datetime.now().date()

    # Get days after today from op_args
    days_after = op_args.get("days_after", 0)

    # Calculate check-in date
    checkin_date = today + timedelta(days=days_after)
    checkin_date_str = checkin_date.strftime("%Y-%m-%d")

    print(f"Today: {today}, Days after: {days_after}, Check-in date: {checkin_date_str}")

    # Get the hotel price with conditions (Sydney hotels with 4 adults, 2 rooms, 1 child)
    price = await playwright__get_hotel_price_with_conditions(checkin_date_str)

    # For now, just return success if we got a price
    # You can add more specific validation logic here based on your needs
    if price:
        print(f"Successfully retrieved hotel price with conditions: {price}")
        print(f"Hotel price with conditions retrieved: {price}")

        if price == llm_response:
            return True, ""

        return False, f"Hotel price with conditions retrieved: {price}, expected: {llm_response}"

    return False, "Failed to retrieve hotel price with conditions"


@compare_func(name="playwright.check_rwsentosa_price_with_conditions")
async def playwright_check_rwsentosa_price_with_conditions(x: dict, *args, **kwargs) -> (bool, str):
    """Check RWSentosa attraction price with conditions by getting today's date and calculating visit date from op_args."""
    _, op_args = args
    llm_response = x.get("price", {})

    # Get today's date
    today = datetime.now().date()

    # Get days after today from op_args
    days_after = op_args.get("days_after", 0)

    # Calculate visit date
    visit_date = today + timedelta(days=days_after)
    visit_date_str = visit_date.strftime("%Y-%m-%d")

    # Get other parameters from op_args
    theme_parks = op_args.get("theme_parks", [])
    adults = op_args.get("adults", 0)
    children = op_args.get("children", 0)

    print(f"Today: {today}, Days after: {days_after}, Visit date: {visit_date_str}")
    print(f"Theme parks: {theme_parks}, Adults: {adults}, Children: {children}")

    total_price = 0
    response_currency = ""
    for theme_park in theme_parks:
        # Get the RWSentosa attraction prices
        prices = await playwright__get_rwsentosa_price_with_conditions(visit_date_str, theme_park)
        adult_price_str = prices.get("adult_price", None)
        child_price_str = prices.get("child_price", None)

        adult_price, adult_currency = playwright__extract_numeric_price(adult_price_str)
        child_price, child_currency = playwright__extract_numeric_price(child_price_str)

        if adult_currency != child_currency:
            return False, f"Adult and child prices have different currencies: {adult_currency} and {child_currency}"

        if not response_currency:
            response_currency = adult_currency

        if adult_currency != response_currency:
            return False, f"Adult and child prices have different currencies: {adult_currency} and {response_currency}"

        total_price += adult_price * adults + child_price * children

    if not response_currency:
        return False, "No response currency found"

    gt_price_response = f"{response_currency}{total_price:.2f}"

    if not gt_price_response == llm_response:
        return False, f"RWSentosa prices retrieved: {gt_price_response}, llm response: {llm_response}"

    return True, ""


@compare_func(name="playwright.multi_task_check_hotel_price_with_lowest_price_highest_rating")
async def playwright_check_singapore_hotel_price_with_lowest_price_highest_rating(x: dict, *args, **kwargs) -> (
bool, str):
    """Check Singapore hotel price with lowest price and highest rating by getting today's date and calculating check-in date from op_args.
    This function is used for multi-task evaluation. For task: multi-server_task_playwright_notion_0004.json, we need to check the price of the hotel with the lowest price and the hotel with the highest rating.
    """
    _, op_args = args
    notion_page_title = op_args.get("notion_page_title", "")

    await asyncio.sleep(20)
    _, notion_page_content = await notion__get_content_by_page_title(notion_page_title, return_block=False)

    # # Get today's date
    today = datetime.now().date()
    # Get days after today from op_args
    days_after = op_args.get("days_after", 0)
    currency = op_args.get("currency", "SGD")
    # order = op_args.get("order", "price")
    city = op_args.get("city", "Singapore")
    group_adults = op_args.get("group_adults", 1)
    no_rooms = op_args.get("no_rooms", 1)
    group_children = op_args.get("group_children", 0)

    # Calculate check-in date
    checkin_date = today
    checkin_date_str = checkin_date.strftime("%Y-%m-%d")

    # Get checkout date
    checkout_date = checkin_date + timedelta(days=days_after)
    checkout_date_str = checkout_date.strftime("%Y-%m-%d")

    # Get the hotel price with lowest price and highest rating
    hotel_title_lowest_price, price_lowest = await playwright__booking_com_get_hotel_price_with_lowest_price_highest_rating(
        city=city,
        group_adults=group_adults,
        no_rooms=no_rooms,
        group_children=group_children,
        checkin_date=checkin_date_str,
        checkout_date=checkout_date_str,
        currency=currency,
        order="price"
    )

    hotel_title_highest_rating, highest_rating = await playwright__booking_com_get_hotel_price_with_lowest_price_highest_rating(
        city=city,
        group_adults=group_adults,
        no_rooms=no_rooms,
        group_children=group_children,
        checkin_date=checkin_date_str,
        checkout_date=checkout_date_str,
        currency=currency,
        order="class"
    )

    ground_truth_content = f"1. Hotel with the Highest Rating: {hotel_title_highest_rating}, Price: {highest_rating}\n2. Hotel with the Lowest Price: {hotel_title_lowest_price}, Price: {price_lowest}"

    if not notion_page_content == ground_truth_content:
        return False, f"\nNotion page content: {notion_page_content} \nGround truth content: {ground_truth_content}"
    return True, ""


@compare_func(name="playwright.check_flight_price_with_notion")
async def playwright_check_flight_price_with_notion(x: dict, *args, **kwargs) -> (bool, str):
    """Check flight price with Notion by getting today's date and calculating departure date from op_args."""

    _, op_args = args
    # Get notion page title from op_args
    notion_page_title = op_args.get("notion_page_title", "")

    # Get parameters from op_args
    depart_days_after = op_args.get("depart_days_after", 0)
    return_days_after = op_args.get("return_days_after", None)
    flight_type = op_args.get("flight_type", "ONEWAY")
    cabin_class = op_args.get("cabin_class", "ECONOMY")
    adults = op_args.get("adults", 1)
    children = op_args.get("children", 0)
    stops = op_args.get("stops", 0)
    sort = op_args.get("sort", "CHEAPEST")
    travel_purpose = op_args.get("travel_purpose", "leisure")
    from_location = op_args.get("from_location", "")
    to_location = op_args.get("to_location", "")
    from_country = op_args.get("from_country", "")
    to_country = op_args.get("to_country", "")
    from_location_name = op_args.get("from_location_name", "")
    to_location_name = op_args.get("to_location_name", "")

    await asyncio.sleep(20)
    ret, notion_page_content = await notion__get_content_by_page_title(notion_page_title, return_block=False)
    if not ret:
        return False, f"Failed to get notion page content: {notion_page_title}"

    # Get today's date
    today = datetime.now().date()

    # Calculate departure date
    departure_date = today + timedelta(days=depart_days_after)
    depart_date_str = departure_date.strftime("%Y-%m-%d")

    return_date_str = ""
    if return_days_after is not None:
        return_date = departure_date + timedelta(days=return_days_after)
        return_date_str = return_date.strftime("%Y-%m-%d")
        print(f"Return days after: {return_days_after}, Return date: {return_date_str}")

    # Get the flight price
    price = await playwright__get_flight_price(
        depart_date=depart_date_str,
        return_date=return_date_str,
        flight_type=flight_type,
        cabin_class=cabin_class,
        adults=adults,
        children=children,
        stops=stops,
        sort=sort,
        travel_purpose=travel_purpose,
        from_location=from_location,
        to_location=to_location,
        from_country=from_country,
        to_country=to_country,
        from_location_name=from_location_name,
        to_location_name=to_location_name
    )

    ground_truth_content = f"The cheapest flight price: {price}"

    if not notion_page_content == ground_truth_content:
        return False, f"\nNotion page content: {notion_page_content} \nGround truth content: {ground_truth_content}"
    return True, ""
