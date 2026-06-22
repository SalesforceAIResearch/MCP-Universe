"""
Evaluation functions for Yahoo finance tasks
"""
# pylint: disable=broad-exception-caught, unused-argument
# pylint: disable=too-many-boolean-expressions, too-many-lines, too-many-return-statements, too-many-branches
from datetime import datetime, timedelta
from typing import Literal
import math
import pandas as pd
import yfinance as yf
from mcpuniverse.evaluator.functions import compare_func


##################################################################################
# Utils Function for Yahoo-Finance
##################################################################################

def yfinance__calculate_portfolio_return(
        tickers: list,
        start_date_str: str,
        end_date_str: str,
        initial_investment: float,
        split: list
) -> tuple[float, float]:
    """
    Calculates the expected final value and total percentage return for a portfolio
    of multiple stocks using yfinance.

    Args:
        tickers: List of stock tickers
        start_date_str: Starting date in format 'YYYY-MM-DD'
        end_date_str: Ending date in format 'YYYY-MM-DD'
        initial_investment: Total initial investment amount
        split: List of allocation percentages (must sum to 1.0)

    Returns:
        Tuple of (final_value, percentage_return)
    """
    if abs(sum(split) - 1.0) > 0.001:
        raise ValueError("Portfolio split must sum to 1.0")
    if len(tickers) != len(split):
        raise ValueError("Number of tickers must match number of allocation percentages")

    end_date_dt = datetime.strptime(end_date_str, "%Y-%m-%d")
    yf_query_end_date_str = (end_date_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    final_value = 0.0

    for i, ticker in enumerate(tickers):
        stock_investment = initial_investment * split[i]
        stock_data = yf.download(
            ticker, start=start_date_str, end=yf_query_end_date_str, progress=False
        )
        if stock_data.empty:
            raise ValueError(f"No data found for {ticker} from {start_date_str} to {end_date_str}")
        # Needs to be improved, as the market may be closed on that date.
        start_price = stock_data.loc[start_date_str]['Close'].values[0]
        end_price = stock_data.loc[end_date_str]['Close'].values[0]
        if start_price == 0:
            raise ValueError(
                f"Start price for {ticker} is zero, cannot calculate investment metrics."
            )
        num_shares = stock_investment / start_price
        stock_final_value = num_shares * end_price
        final_value += stock_final_value

    total_percentage_return = ((final_value - initial_investment) / initial_investment) * 100
    return round(final_value, 2), round(total_percentage_return, 2)


def yfinance__get_latest_financial_data(
        ticker_symbol: str,
        period: Literal['annually', 'quarterly'] = 'annually'
) -> dict | None:
    """
    Retrieves specified financial data for a ticker from its most recent annual income statement.
    Fetches: Total Revenue, Research And Development expense, Operating Income (exact values).
    Calculates: Net Profit Margin (as a percentage).

    Returns a dictionary with keys matching the output format, or None if essential data is missing.
    """
    output_keys = {
        'total revenue': ["Total Revenue"],
        'rd expense': ["Research And Development", "ResearchAndDevelopment", "RDExpenses",
                       "Research Development Expense"],
        'operating income': [
            "Operating Income", "OperatingIncome", "EBIT", "Earnings Before Interest And Taxes"
        ],
        'gross profit': ["Gross Profit", "GrossProfit"],
        'net income': ["Net Income Common Stockholders", "Netincomecommonstockholders"]
    }

    retrieved_data = {}

    try:
        stock = yf.Ticker(ticker_symbol)
        if period == 'annually':
            annual_is = stock.financials
        else:
            annual_is = stock.quarterly_financials

        if not isinstance(annual_is, pd.DataFrame) or annual_is.empty:
            print(f"Warning: Annual income statement data not found or empty for {ticker_symbol}.")
            return None

        if not annual_is.columns.tolist():
            print(f"Warning: No data columns in annual income statement for {ticker_symbol}.")
            return None

        latest_year_data = annual_is[annual_is.columns[0]]  # Series for the most recent year
        fiscal_year_end_obj = latest_year_data.name
        if isinstance(fiscal_year_end_obj, pd.Timestamp):
            fiscal_year_end_str = fiscal_year_end_obj.strftime('%Y-%m-%d')
        else:
            fiscal_year_end_str = str(fiscal_year_end_obj)
        print(f"Processing data for {ticker_symbol} (FY ending {fiscal_year_end_str})")

        # Retrieve direct values
        for output_key, yf_keys_list in output_keys.items():
            found_value = None
            for yf_key in yf_keys_list:
                if yf_key in latest_year_data.index:
                    value = latest_year_data.loc[yf_key]
                    if pd.notna(value):
                        found_value = float(value)  # Store as float
                        break
            if found_value is None:
                warning_msg = (f"Warning: Metric for '{output_key}' (searched {yf_keys_list}) "
                               f"not found or NaN for {ticker_symbol}. "
                               f"Available keys example: {latest_year_data.index[:20].tolist()}")
                print(warning_msg)
                return None  # Essential direct metric missing
            retrieved_data[output_key] = found_value

        return retrieved_data

    except Exception as e:
        print(f"Error processing yfinance data for {ticker_symbol}: {e}")
        return None


def yfinance__get_lastest_year_raw_gross_profit_margin(ticker_symbol: str) -> float | None:
    """
    Retrieves and calculates the raw gross profit margin for a given ticker
    from its most recent annual income statement using yfinance.

    Returns the raw margin as a float or None if calculation fails.
    """
    try:
        financial_data = yfinance__get_latest_financial_data(ticker_symbol)
        gross_profit = financial_data['gross profit']
        total_revenue = financial_data['total revenue']
        margin = gross_profit / total_revenue
        return margin  # Return raw, unrounded margin
    except Exception as e:
        print(f"Error processing yfinance data for {ticker_symbol}: {e}")
        return None


def yfinance__get_lastest_year_raw_net_profit_margin(ticker_symbol: str) -> float | None:
    """
    Retrieves and calculates the raw net profit margin for a given ticker
    from its most recent annual income statement.
    Uses "Net Income Common Stockholders" / "Total Revenue".
    Falls back to "Net Income" if "Net Income Common Stockholders" is not found.

    Returns the raw margin as a float or None if calculation fails.
    """
    try:
        financial_data = yfinance__get_latest_financial_data(ticker_symbol)
        net_income = financial_data['net income']
        total_revenue = financial_data['total revenue']
        margin = net_income / total_revenue
        return margin
    except Exception as e:
        print(f"Error processing yfinance data for {ticker_symbol} : {e}")
        return None


def yfinance__get_lastest_year_raw_rd_expense(ticker_symbol: str) -> float | None:
    """
    Retrieves and calculates the raw R&D expense as a number of total revenue
    for a given ticker from its most recent annual income statement.

    Returns the raw number as a float or None if calculation fails.
    """
    try:
        financial_data = yfinance__get_latest_financial_data(ticker_symbol)
        rd_expense = financial_data['rd expense']
        total_revenue = financial_data['total revenue']
        # R&D expense is typically reported as a positive value.
        percentage = rd_expense / total_revenue
        return percentage
    except Exception as e:
        print(f"Error processing yfinance data for {ticker_symbol}: {e}")
        return None


def yfinance__get_lastest_year_raw_rd(ticker_symbol: str) -> float | None:
    """
    Retrieves and calculates the raw R&D expense as a number of total revenue
    for a given ticker from its most recent annual income statement.

    Returns the raw number as a float or None if calculation fails.
    """
    try:
        financial_data = yfinance__get_latest_financial_data(ticker_symbol)
        rd_expense = financial_data['rd expense']
        return rd_expense
    except Exception as e:
        print(f"Error processing yfinance data for {ticker_symbol}: {e}")
        return None


def yfinance__get_filtered_institutional_holders(ticker_symbol, min_pct_change) -> dict | None:
    """
    Attempts to retrieve institutional holders, filter them by a 'pctChange'
    criterion (pctChange > min_pct_change), and calculate the aggregate market value.

    Returns a dictionary with 'institutional holders' list and 'aggregate market value',
    or None if essential data (especially a usable 'pctChange' column) is missing or fails.
    """
    # Keys for the output dictionary, matching the task's output format
    output_key_list = 'institutional holders'
    output_key_agg_value = 'aggregate market value'

    output_data = {output_key_list: [], output_key_agg_value: 0.0}

    try:
        stock = yf.Ticker(ticker_symbol)
        holders_df_original = stock.institutional_holders

        if not isinstance(holders_df_original, pd.DataFrame) or holders_df_original.empty:
            print(f"Warning: Institutional holders data not found or empty for {ticker_symbol}.")
            return None

        holders_df = holders_df_original.copy()  # Work on a copy

        # --- CRITICAL: Identify and process the 'pctChange' column ---
        # yfinance's institutional_holders often LACKS a direct, reliable pctChange column.
        # The task assumes its existence. We try to find it or a common variant.
        pct_change_col_candidates = [
            '% Change', 'Pct Change', 'pctChange', 'Change (%)', 'Change %', 'Chg %'
        ]
        actual_pct_change_col = None
        for col_name in pct_change_col_candidates:
            if col_name in holders_df.columns:
                actual_pct_change_col = col_name
                break

        if actual_pct_change_col is None:
            critical_msg = (f"CRITICAL Warning: Could not find a 'pctChange'-like column "
                            f"in yfinance's institutional_holders DataFrame for {ticker_symbol}. "
                            f"Searched for {pct_change_col_candidates}. "
                            f"Available columns: {holders_df.columns.tolist()}. "
                            f"Cannot perform task as specified.")
            print(critical_msg)
            return None  # This is a showstopper for the task's requirements.

        print(
            f"Using column '{actual_pct_change_col}' for pctChange filtering for {ticker_symbol}."
        )

        # Ensure 'Holder' and 'Value' columns exist
        if 'Holder' not in holders_df.columns or 'Value' not in holders_df.columns:
            print(
                f"Warning: 'Holder' or 'Value' column missing. "
                f"Columns: {holders_df.columns.tolist()}"
            )
            return None

        # --- Data Type Conversion ---
        # Convert 'Value' to numeric
        holders_df['Value'] = pd.to_numeric(holders_df['Value'], errors='coerce')

        # Convert 'pctChange' column to numeric decimal (e.g., 2.5% -> 0.025)
        # This is complex because the source format is uncertain.
        # Assuming it might be a string like "2.50%" or a float already.
        if holders_df[actual_pct_change_col].dtype == 'object':
            # Try to strip '%' and convert, then divide by 100 if it was a percentage string
            try:
                holders_df[actual_pct_change_col] = (
                        holders_df[actual_pct_change_col]
                        .astype(str)
                        .str.rstrip('%')
                        .astype('float') / 100.0
                )
            except ValueError:  # If above fails, try direct numeric conversion
                holders_df[actual_pct_change_col] = pd.to_numeric(
                    holders_df[actual_pct_change_col], errors='coerce'
                )
        elif pd.api.types.is_numeric_dtype(holders_df[actual_pct_change_col]):
            # If it's already numeric, assume it's decimal (0.02 for 2%)
            # unless it's clearly whole percentages (e.g. 2.0 for 2%)
            # If values are like 2.5, 10.0, they are likely percentages, so divide by 100.
            # If values are like 0.025, 0.10, they are likely already decimals.
            # This is ambiguous without knowing yfinance's exact format for this
            # hypothetical column. For now, if numeric, assume it's already in the
            # required decimal format (0.02 for 2%). A more robust solution would
            # inspect data range or have clearer spec from yfinance.
            # Let's assume if numeric, it's already decimal (0.02 = 2%).
            pass  # Assume numeric column is already in decimal format
        else:  # Not object, not numeric, try converting
            holders_df[actual_pct_change_col] = pd.to_numeric(
                holders_df[actual_pct_change_col], errors='coerce'
            )

        # Drop rows where essential conversions failed (NaN introduced)
        holders_df.dropna(subset=[actual_pct_change_col, 'Value', 'Holder'], inplace=True)
        if holders_df.empty:
            print(
                f"Note: Dataframe became empty after coercing types for pctChange/Value "
                f"for {ticker_symbol}."
            )
            return output_data  # Return empty valid structure

        # --- Filtering based on pctChange > minpctchange ---
        # The task states "minpctchange (representing a 2 percentage point increase)"
        filtered_df = holders_df[holders_df[actual_pct_change_col] > min_pct_change]

        if filtered_df.empty:
            print(
                f"Note: No institutional holders found for {ticker_symbol} with "
                f"{actual_pct_change_col} > {min_pct_change}."
            )
        else:
            for _, row in filtered_df.iterrows():
                output_data[output_key_list].append({
                    'institution': str(row['Holder']),
                    'value': float(row['Value']),
                    'pctChange': float(row[actual_pct_change_col])
                })
            output_data[output_key_agg_value] = float(filtered_df['Value'].sum())

        print(
            f"Filtered {len(output_data[output_key_list])} institutions for {ticker_symbol}. "
            f"Aggregate value: {output_data[output_key_agg_value]:,.0f}"
        )
        return output_data

    except Exception as e:
        print(
            f"An unexpected error occurred in get_filtered_institutional_holders "
            f"for {ticker_symbol}: {e}"
        )
        return None


def yfinance__get_blackrock_pct_change(ticker_symbol: str) -> float | None:
    """
    Attempts to retrieve the 'pctChange' for 'Blackrock Inc.' from a ticker's
    institutional holders data.

    Returns the pctChange as a decimal float (e.g., 0.02 for 2%) or None if not found/calculable.
    """
    try:
        stock = yf.Ticker(ticker_symbol)
        holders_df_original = stock.institutional_holders

        if not isinstance(holders_df_original, pd.DataFrame) or holders_df_original.empty:
            print(f"Warning: Institutional holders data not found or empty for {ticker_symbol}.")
            return None

        holders_df = holders_df_original.copy()

        # --- Find 'Blackrock Inc.' ---
        # Normalize search string and DataFrame holder names for comparison
        holder_name_to_find_lc = "blackrock inc."  # Target name
        blackrock_row = None

        if 'Holder' not in holders_df.columns:
            print(f"Warning: 'Holder' column missing in institutional_holders for {ticker_symbol}.")
            return None

        # Try exact (case-insensitive) match first for "Blackrock Inc."
        for _, row_series in holders_df.iterrows():
            current_holder_name = str(row_series['Holder'])
            if holder_name_to_find_lc == current_holder_name.lower():
                blackrock_row = row_series
                print(
                    f"Info: Found exact match for '{holder_name_to_find_lc}' in "
                    f"{ticker_symbol}: {current_holder_name}"
                )
                break

        if blackrock_row is None:  # If no exact match, try common variations containing "blackrock"
            # This list could be expanded based on common yfinance naming for BlackRock entities
            blackrock_variants_lc = [
                "blackrock fund advisors",
                "blackrock advisors, llc",
                "blackrock institutional trust company",
                "blackrock financial management"
            ]
            # Prioritize "blackrock inc." still, but broaden search

            best_match_row = None
            match_priority = float('inf')

            for _, row_series in holders_df.iterrows():
                current_holder_name_lc = str(row_series['Holder']).lower()
                if "blackrock" in current_holder_name_lc:
                    current_priority = float('inf')
                    if holder_name_to_find_lc == current_holder_name_lc:  # Exact "blackrock inc."
                        current_priority = 0
                    elif any(
                            variant in current_holder_name_lc for variant in blackrock_variants_lc
                    ):
                        current_priority = 1  # Known variant
                    else:  # General "blackrock" substring
                        current_priority = 2

                    if current_priority < match_priority:
                        match_priority = current_priority
                        best_match_row = row_series
                        if match_priority == 0:  # Found best possible match
                            break

            if best_match_row is not None:
                blackrock_row = best_match_row
                print(
                    f"Info: Using best available match for 'Blackrock' in {ticker_symbol}: "
                    f"{blackrock_row['Holder']}"
                )

        if blackrock_row is None:
            print(
                f"Warning: 'Blackrock Inc.' or a close variant not found in institutional "
                f"holders for {ticker_symbol}. Holder names sample: "
                f"{holders_df['Holder'].head().tolist()}"
            )
            return None

        # --- Identify and process the 'pctChange' column ---
        pct_change_col_candidates = [
            '% Change', 'Pct Change', 'pctChange', 'Change (%)', 'Change %', 'Chg %'
        ]
        actual_pct_change_col = None
        for col_name in pct_change_col_candidates:
            if col_name in blackrock_row.index:  # Check if column exists for the row
                actual_pct_change_col = col_name
                break

        if actual_pct_change_col is None:
            print(
                f"CRITICAL Warning: Could not find a 'pctChange'-like column for Blackrock "
                f"in {ticker_symbol}. Searched for {pct_change_col_candidates}. "
                f"Available columns for Blackrock row: {blackrock_row.index.tolist()}"
            )
            return None

        pct_change_val_raw = blackrock_row[actual_pct_change_col]

        # Convert pctChange to numeric decimal
        pct_change_numeric = None
        if isinstance(pct_change_val_raw, (int, float)) and pd.notna(pct_change_val_raw):
            # If it's already numeric:
            # If value seems like a whole percentage (e.g., 2.5 for 2.5%), divide by 100.
            # If value seems like a decimal (e.g., 0.025 for 2.5%), use as is.
            # This is ambiguous. Yahoo often shows "2.50%" string. If numeric from yf,
            # it might be 2.5 or 0.025. Task states "0.02 (representing a 2 percentage
            # point increase)", implies target is decimal. Assume if yfinance provides
            # a number, it's the direct value (e.g. 2.5 for 2.5%). This might need
            # adjustment based on yfinance typical output for this *hypothetical* column.
            # For now, if it's e.g. 2.5, we'll assume it means 2.5% and divide by 100.
            # If it's already < 1 (and not 0), assume it's decimal.
            # Check if it's likely a whole percentage number
            if abs(pct_change_val_raw) > 1 or pct_change_val_raw == 0:
                pct_change_numeric = pct_change_val_raw / 100.0
            else:  # Assumed to be already in decimal form e.g. 0.025
                pct_change_numeric = pct_change_val_raw

        elif isinstance(pct_change_val_raw, str):
            try:
                cleaned_str = pct_change_val_raw.replace('%', '').strip()
                pct_change_numeric = float(cleaned_str) / 100.0
            except ValueError:
                print(
                    f"Warning: Could not parse string pctChange value "
                    f"'{pct_change_val_raw}' for Blackrock in {ticker_symbol}."
                )
                return None
        elif pd.isna(pct_change_val_raw):
            print(f"Warning: pctChange value is NaN for Blackrock in {ticker_symbol}.")
            return None
        else:
            print(
                f"Warning: Unexpected type for pctChange value '{pct_change_val_raw}' "
                f"({type(pct_change_val_raw)}) for Blackrock in {ticker_symbol}."
            )
            return None

        print(
            f"Data for {ticker_symbol}: Blackrock Holder='{blackrock_row['Holder']}', "
            f"Raw pctChange='{pct_change_val_raw}', Processed pctChange={pct_change_numeric:.4f}"
        )
        return pct_change_numeric

    except Exception as e:
        print(
            f"An unexpected error occurred in get_blackrock_pct_change for {ticker_symbol}: {e}"
        )
        return None


def yfinance__get_significant_holders_for_ticker(
        ticker_symbol: str, threshold_pct_held_decimal: float = 0.05
) -> set[str] | None:
    """
    Retrieves institutional holders for a ticker that hold more than the specified
    threshold percentage of outstanding shares. Holder names are returned as lowercase.

    Returns a set of holder names, or None if data retrieval/processing fails.
    """
    try:
        stock = yf.Ticker(ticker_symbol)
        holders_df_original = stock.institutional_holders

        if not isinstance(holders_df_original, pd.DataFrame) or holders_df_original.empty:
            print(f"Warning: Institutional holders data not found or empty for {ticker_symbol}.")
            return None

        holders_df = holders_df_original.copy()  # Work on a copy

        # Identify the '% Out' column
        pct_out_col_candidates = ['pctHeld']
        actual_pct_out_col = None
        for col_name in pct_out_col_candidates:
            if col_name in holders_df.columns:
                actual_pct_out_col = col_name
                break

        if actual_pct_out_col is None:
            print(
                f"Warning: Could not find a '% Out'-like column for {ticker_symbol}. "
                f"Searched for {pct_out_col_candidates}. "
                f"Available columns: {holders_df.columns.tolist()}."
            )
            return None

        if 'Holder' not in holders_df.columns:
            print(
                f"Warning: 'Holder' column missing for {ticker_symbol}. "
                f"Columns: {holders_df.columns.tolist()}"
            )
            return None

        print(f"Using column '{actual_pct_out_col}' for pctHeld filtering for {ticker_symbol}.")

        # Drop rows where conversion failed (NaN introduced) or Holder name is NaN/missing
        holders_df.dropna(subset=[actual_pct_out_col, 'Holder'], inplace=True)
        if holders_df.empty:
            print(
                f"Note: Dataframe became empty after coercing types for '% Out'/Holder "
                f"for {ticker_symbol}."
            )
            return set()  # Return empty set if no valid data after cleaning

        # Filter based on the threshold
        filtered_df = holders_df[holders_df[actual_pct_out_col] > threshold_pct_held_decimal]

        # Get holder names, convert to string, lowercase, and put in a set
        significant_holder_names = set(
            filtered_df['Holder'].astype(str).str.lower().tolist()
        )

        print(
            f"Found {len(significant_holder_names)} significant holders "
            f"(>{threshold_pct_held_decimal * 100:.2f}%) for {ticker_symbol}.")
        return significant_holder_names

    except Exception as e:
        print(f"An unexpected error occurred in get_significant_holders_for_ticker "
              f"for {ticker_symbol}: {e}")
        return None


def yfinance__get_specific_holder_pct_change(
        ticker_symbol: str, holder_name_query: str
) -> float | None:
    """
    Attempts to retrieve the 'pctChange' for a specific holder from a ticker's
    institutional holders data.

    Returns pctChange as a decimal float (e.g., 0.02 for 2%) or None if not found/calculable.
    """
    try:
        stock = yf.Ticker(ticker_symbol)
        holders_df_original = stock.institutional_holders

        if not isinstance(holders_df_original, pd.DataFrame) or holders_df_original.empty:
            print(f"Warning: Institutional holders data not found or empty for {ticker_symbol}.")
            return None

        holders_df = holders_df_original.copy()

        if 'Holder' not in holders_df.columns:
            print(f"Warning: 'Holder' column missing for {ticker_symbol}.")
            return None

        # --- Find the specified holder ---
        normalized_query_lc = holder_name_query.lower()
        core_name_lc = normalized_query_lc.split(' ')[0]  # e.g., "blackrock", "vanguard"

        exact_match_row = None
        best_match_row = None

        for _, row_series in holders_df.iterrows():
            current_holder_name_lc = str(row_series['Holder']).lower()
            if normalized_query_lc == current_holder_name_lc:
                exact_match_row = row_series
                break

        if exact_match_row is not None:
            best_match_row = exact_match_row
            print(f"Info: Found exact match for '{holder_name_query}' in {ticker_symbol}: "
                  f"{best_match_row['Holder']}")
        else:  # No exact match, try a broader search including common known variations or simple substring
            known_variants = {
                "blackrock inc.": ["blackrock fund advisors", "blackrock advisors, llc",
                                   "blackrock institutional trust company", "blackrock financial management"],
                "vanguard group": ["the vanguard group, inc.", "vanguard fiduciary trust co",
                                   "vanguard total stock market index", "vanguard specialized funds"]
                # Example, expand as needed
            }

            priority_match_row = None
            current_best_priority = float('inf')

            for _, row_series in holders_df.iterrows():
                current_holder_name_lc = str(row_series['Holder']).lower()
                priority = float('inf')

                if normalized_query_lc == current_holder_name_lc:  # Should have been caught by exact_match_row
                    priority = 0
                elif holder_name_query.lower() in known_variants:  # Check if query is a base for known variants
                    for variant in known_variants[holder_name_query.lower()]:
                        if variant in current_holder_name_lc:
                            priority = 1  # Known variant match
                            break

                if priority > 1 and core_name_lc in current_holder_name_lc:  # Simple substring if no better match
                    priority = 2

                if priority < current_best_priority:
                    current_best_priority = priority
                    priority_match_row = row_series
                    if current_best_priority == 0:
                        break  # Can't get better than exact

            if priority_match_row is not None:
                best_match_row = priority_match_row
                print(
                    f"Info: Using best available match for '{holder_name_query}' "
                    f"(core: '{core_name_lc}') in {ticker_symbol}: "
                    f"{best_match_row['Holder']} (Match type priority: {current_best_priority})")

        if best_match_row is None:
            print(
                f"Warning: Holder '{holder_name_query}' (or similar with core "
                f"'{core_name_lc}') not found for {ticker_symbol}. Sample holders: "
                f"{holders_df['Holder'].head().tolist()}")
            return None

        # --- Identify and process the 'pctChange' column from the found row ---
        pct_change_col_candidates = ['pctChange', 'Change (%)', 'Change %', 'Chg %']
        actual_pct_change_col = None
        for col_name in pct_change_col_candidates:
            if col_name in best_match_row.index:
                actual_pct_change_col = col_name
                break

        if actual_pct_change_col is None:
            print(
                f"CRITICAL Warning: Could not find 'pctChange'-like column for "
                f"holder '{best_match_row['Holder']}' in {ticker_symbol}. "
                f"Searched for {pct_change_col_candidates}. Available columns for row: "
                f"{best_match_row.index.tolist()}")
            return None

        pct_change_val_raw = best_match_row[actual_pct_change_col]
        pct_change_numeric = None

        if isinstance(pct_change_val_raw, (int, float)) and pd.notna(pct_change_val_raw):
            # If numeric: assume values like 2.5 mean 2.5% -> 0.025; values like 0.025 mean 0.025
            # This heuristic might need adjustment if yfinance output is different
            # for this hypothetical column
            # Likely 2.5 for 2.5% or 0
            if abs(pct_change_val_raw) > 1.0 or pct_change_val_raw == 0:
                pct_change_numeric = pct_change_val_raw / 100.0
            else:  # Likely already 0.025 for 2.5%
                pct_change_numeric = pct_change_val_raw
        elif isinstance(pct_change_val_raw, str):
            try:
                cleaned_str = pct_change_val_raw.replace('%', '').strip()
                pct_change_numeric = float(cleaned_str) / 100.0
            except ValueError:
                print(
                    f"Warning: Could not parse string pctChange "
                    f"'{pct_change_val_raw}' for '{best_match_row['Holder']}' "
                    f"in {ticker_symbol}.")
                return None
        elif pd.isna(pct_change_val_raw):
            print(f"Warning: pctChange value is NaN for '{best_match_row['Holder']}' in {ticker_symbol}.")
            return None
        else:
            print(
                f"Warning: Unexpected type for pctChange value "
                f"'{pct_change_val_raw}' ({type(pct_change_val_raw)}) for "
                f"'{best_match_row['Holder']}' in {ticker_symbol}.")
            return None

        print(
            f"Data for {ticker_symbol}: Holder='{best_match_row['Holder']}', "
            f"Raw pctChange='{pct_change_val_raw}', "
            f"Processed pctChange={pct_change_numeric:.4f}")
        return pct_change_numeric

    except Exception as e:
        print(
            f"An error occurred in get_specific_holder_pct_change for "
            f"{ticker_symbol} processing {holder_name_query}: {e}")
        # import traceback; traceback.print_exc() # Uncomment for detailed debugging
        return None


def yfinance__get_significant_holders_by_pct_held(
        ticker_symbol: str, threshold_pct_held_decimal: float = 0.05
) -> set[str] | None:
    """
    Retrieves institutional holders for a ticker that hold more than the specified
    threshold percentage of outstanding shares. Holder names are returned as lowercase.

    Returns a set of holder names, or None if data retrieval/processing fails.
    """
    try:
        stock = yf.Ticker(ticker_symbol)
        holders_df_original = stock.institutional_holders

        if not isinstance(holders_df_original, pd.DataFrame) or holders_df_original.empty:
            print(
                f"Warning (get_significant_holders_by_pct_held for {ticker_symbol}): "
                f"Institutional holders data not found or empty.")
            return None

        holders_df = holders_df_original.copy()

        pct_out_col_candidates = ['pctHeld', 'Percentage Of Outstanding Shares Held']
        actual_pct_out_col = None
        for col_name in pct_out_col_candidates:
            if col_name in holders_df.columns:
                actual_pct_out_col = col_name
                break

        if actual_pct_out_col is None:
            print(
                f"Warning (get_significant_holders_by_pct_held for {ticker_symbol}): "
                f"Could not find '% Out'-like column. Searched: {pct_out_col_candidates}. "
                f"Available: {holders_df.columns.tolist()}.")
            return None

        if 'Holder' not in holders_df.columns:
            print(
                f"Warning (get_significant_holders_by_pct_held for {ticker_symbol}): "
                f"'Holder' column missing. Columns: {holders_df.columns.tolist()}")
            return None

        print(f"Using column '{actual_pct_out_col}' for pctHeld filtering for {ticker_symbol}.")

        holders_df.dropna(subset=[actual_pct_out_col, 'Holder'], inplace=True)
        if holders_df.empty:
            print(
                f"Note (get_significant_holders_by_pct_held for {ticker_symbol}): "
                f"Dataframe empty after type coercion/dropna.")
            return set()

        filtered_df = holders_df[holders_df[actual_pct_out_col] > threshold_pct_held_decimal]
        significant_holder_names = set(filtered_df['Holder'].astype(str).str.lower().tolist())

        print(
            f"Found {len(significant_holder_names)} significant holders "
            f"(>{threshold_pct_held_decimal * 100:.2f}%) for {ticker_symbol}.")
        return significant_holder_names

    except Exception as e:
        print(f"An error in get_significant_holders_by_pct_held for {ticker_symbol}: {e}")
        # import traceback; traceback.print_exc() # For debugging
        return None


def yfinance__get_vanguard_latest_report_date(ticker_symbol):
    """
    Finds the latest 'Date Reported' for 'Vanguard Group Inc.' (or variants)
    in AAPL's institutional holdings.
    """
    try:
        stock = yf.Ticker(ticker_symbol)
        holders_df = stock.institutional_holders

        if holders_df is None or holders_df.empty:
            print(f"Warning (Task 16 Helper): Institutional holders data "
                  f"not found/empty for {ticker_symbol}.")
            return None
        if 'Holder' not in holders_df.columns or 'Date Reported' not in holders_df.columns:
            print(
                f"Warning (Task 16 Helper): 'Holder' or 'Date Reported' column missing "
                f"for {ticker_symbol}. Cols: {holders_df.columns.tolist()}")
            return None

        # Normalize search terms
        # Task specifies "Vanguard Group Inc."
        # Common yfinance names: "THE VANGUARD GROUP, INC.", "VANGUARD GROUP INC"
        vanguard_search_terms_lc = [
            "vanguard group inc.",  # Exact from task (lowercase)
            "the vanguard group, inc.",  # Common yfinance name
            "vanguard group, inc.",
            "vanguard group"  # Broader, use with caution
        ]

        vanguard_entries_dates = []
        matched_holder_names = set()

        for _, row in holders_df.iterrows():
            holder_name_lc = str(row['Holder']).lower()
            is_match = False
            if holder_name_lc == vanguard_search_terms_lc[0]:  # Prioritize exact match to task name
                is_match = True
            elif not is_match and holder_name_lc == vanguard_search_terms_lc[1]:  # Prioritize common yf name
                is_match = True
            elif not is_match and holder_name_lc == vanguard_search_terms_lc[2]:
                is_match = True
            elif not is_match and vanguard_search_terms_lc[3] in holder_name_lc:
                # Avoid overly broad matches if it's a specific fund vs. the main group
                # This simple check might include individual Vanguard funds.
                # For this task, assume "Vanguard Group Inc" implies the main reporting entity.
                # Let's be stricter for the main entity or a very close match.
                # The current logic takes the first good match.
                # For simplicity, if the name *contains* "vanguard group" and is not clearly a specific sub-fund.
                # This part is tricky. The most common name is "THE VANGUARD GROUP, INC."
                if ("index fund" not in holder_name_lc and "etf" not in holder_name_lc
                        and "trust" not in holder_name_lc):  # Heuristic
                    is_match = True

            if is_match:
                date_reported_val = row['Date Reported']
                if pd.notna(date_reported_val) and isinstance(date_reported_val, pd.Timestamp):
                    vanguard_entries_dates.append(date_reported_val.date())
                    matched_holder_names.add(row['Holder'])
                else:
                    print(
                        f"Warning (Task 16 Helper): Invalid 'Date Reported' for potential "
                        f"Vanguard entry: {row['Holder']}, Date: {date_reported_val}")

        if not vanguard_entries_dates:
            print(
                f"Warning (Task 16 Helper): 'Vanguard Group Inc.' or close variant not "
                f"found for {ticker_symbol}. Searched for variants like "
                f"'{vanguard_search_terms_lc[0]}'. Sample holders: {holders_df['Holder'].head().tolist()}")
            return None

        latest_date = max(vanguard_entries_dates)
        print(
            f"Info (Task 16 Helper): Latest 'Date Reported' for Vanguard "
            f"({', '.join(list(matched_holder_names)[:2])}...) for {ticker_symbol} "
            f"found as: {latest_date.strftime('%Y-%m-%d')}")
        return latest_date
    except Exception as e:
        print(f"Error in get_vanguard_latest_report_date_aapl_task16: {e}")
        return None


def yfinance__calculate_expected_price_changes(ticker_symbol):
    """
    Calculates the expected data for Task 16: Vanguard's report date for a ticker,
    and subsequent 7-day and 30-day stock price changes.
    """
    report_date_dt = yfinance__get_vanguard_latest_report_date(ticker_symbol)
    if report_date_dt is None:
        return None  # Failure message already printed by helper

    date0_dt = report_date_dt
    date7_dt = report_date_dt + timedelta(days=7)
    date30_dt = report_date_dt + timedelta(days=30)

    # Current date for context (to check if target dates are in the future)
    current_exec_date = datetime.now().date()

    # Fetch a data range covering all necessary dates, with buffer for ffill
    fetch_start_dt = date0_dt - timedelta(days=10)  # Buffer before D0 for ffill
    # End date for fetch needs to be at least D30. Add buffer.
    fetch_end_dt = date30_dt + timedelta(days=10)

    # Ensure fetch_end_dt is not too far in the future beyond available data
    if fetch_end_dt > current_exec_date + timedelta(days=1):  # yf.download end is exclusive
        fetch_end_dt = current_exec_date + timedelta(days=1)
        print(f"Note (Task 16 Calc): Adjusted fetch_end_dt to "
              f"{fetch_end_dt.strftime('%Y-%m-%d')} due to current date.")

    try:
        aapl_prices_df = yf.download(f"{ticker_symbol}", start=fetch_start_dt.strftime('%Y-%m-%d'),
                                     end=fetch_end_dt.strftime('%Y-%m-%d'), progress=False)
        if aapl_prices_df.empty:
            print(
                f"Warning (Task 16 Calc): No {ticker_symbol} price data found for range "
                f"{fetch_start_dt} to {fetch_end_dt}.")
            return None
        if 'Close' not in aapl_prices_df.columns:
            print(f"Warning (Task 16 Calc): 'Close' column missing in {ticker_symbol} price data.")
            return None

        aapl_prices_df.index = pd.to_datetime(aapl_prices_df.index)  # Ensure index is DatetimeIndex

        # Target dates as Pandas Timestamps for reindexing
        target_timestamps_pd = pd.to_datetime([date0_dt, date7_dt, date30_dt])

        # Get prices on or immediately before the target dates using ffill
        # This means if date0_dt is a holiday, it takes the closing price of the day before.
        prices_at_target_dates = aapl_prices_df['Close'].reindex(target_timestamps_pd, method='ffill')

        p0 = prices_at_target_dates.iloc[0]
        p7 = prices_at_target_dates.iloc[1]
        p30 = prices_at_target_dates.iloc[2]

        print(
            f"Info (Task 16 Calc): Prices used -> P0 ({date0_dt.strftime('%Y-%m-%d')}): {p0}, "
            f"P7 ({date7_dt.strftime('%Y-%m-%d')}): {p7}, P30 ({date30_dt.strftime('%Y-%m-%d')}): {p30}")

        pct_change_7_day = None
        if date7_dt > current_exec_date:
            print(
                f"Note (Task 16 Calc): 7-day target date {date7_dt.strftime('%Y-%m-%d')} is in "
                f"the future. 7-day change uncalculable.")
        else:
            pct_change_7_day = ((p7.iloc[0] - p0.iloc[0]) / p0.iloc[0]) * 100.0

        pct_change_30_day = None
        if date30_dt > current_exec_date:
            print(
                f"Note (Task 16 Calc): 30-day target date {date30_dt.strftime('%Y-%m-%d')} is in "
                f"the future. 30-day change uncalculable.")
        else:
            pct_change_30_day = ((p30.iloc[0] - p0.iloc[0]) / p0.iloc[0]) * 100.0

        result = {
            'Date Reported': date0_dt.strftime('%d%m%Y'),  # DDMMYYYY
            '7-day percentage change': round(pct_change_7_day, 2) if pct_change_7_day is not None else None,
            '30-day percentage change': round(pct_change_30_day, 2) if pct_change_30_day is not None else None
        }
        # Task output format requires NUMBER. If change is None, this implies task is
        # unanswerable for that part.
        # Checker will compare NUMBER vs (expected_NUMBER or None).
        # If user provides NUMBER and expected is None, it's a mismatch.
        return result

    except Exception as e:
        print(f"Error in calculate_expected_price_changes_task16 ({ticker_symbol} price processing): {e}")
        # import traceback; traceback.print_exc()
        return None


def yfinance__get_holder_latest_report_data(ticker_symbol: str, holder_target_name_exact: str):
    """
    Finds the latest 'Date Reported', 'Shares', and 'Value' for a specific 
    holder
    in a given company's institutional holdings.
    """
    holder_search_aliases = {
        "blackrock inc.": ["blackrock inc."],
        "the vanguard group": ["the vanguard group, inc.", "vanguard group, inc.", "the vanguard group"],
        "berkshire hathaway, inc": ["berkshire hathaway, inc", "berkshire hathaway inc", "berkshire hathaway, inc."],
        "state street corporation": ["state street corporation", "state street corp"]
    }
    holder_target_name_lc = holder_target_name_exact.lower()
    search_terms_lc = holder_search_aliases.get(holder_target_name_lc, [holder_target_name_lc])

    print(
        f"Info (Holder Helper): Searching for '{holder_target_name_exact}' "
        f"(using terms: {search_terms_lc}) in {ticker_symbol} holdings.")

    try:
        stock = yf.Ticker(ticker_symbol)
        holders_df = stock.institutional_holders

        if holders_df is None or holders_df.empty:
            print(f"Warning (Holder Helper): Institutional holders data not found/empty for {ticker_symbol}.")
            return None

        required_cols = ['Holder', 'Shares', 'Date Reported', 'Value']
        for col in required_cols:
            if col not in holders_df.columns:
                print(
                    f"Warning (Holder Helper): Column '{col}' missing for {ticker_symbol}. "
                    f"Cols: {holders_df.columns.tolist()}")
                return None

        matched_entries = []
        for _, row in holders_df.iterrows():
            current_holder_name_lc = str(row['Holder']).lower()
            is_match_found = False
            for term in search_terms_lc:
                if term == current_holder_name_lc:
                    is_match_found = True
                    break

            if is_match_found:
                date_reported_val = row['Date Reported']
                shares_val = row['Shares']
                value_val = row['Value']

                if pd.notna(date_reported_val) and isinstance(date_reported_val, pd.Timestamp) and \
                        pd.notna(shares_val) and pd.notna(value_val):
                    try:
                        shares_int = int(shares_val)
                        value_int = int(value_val)
                        matched_entries.append({
                            'date': date_reported_val.date(),
                            'shares': shares_int,
                            'reported_value': value_int,
                            'holder_name': str(row['Holder'])
                        })
                    except ValueError:
                        print(
                            f"Warning (Holder Helper): Could not convert S/V for {row['Holder']} "
                            f"in {ticker_symbol}: S={shares_val}, V={value_val}")

        if not matched_entries:
            print(
                f"Warning (Holder Helper): '{holder_target_name_exact}' not found for "
                f"{ticker_symbol} with complete data. Sample holders: "
                f"{holders_df['Holder'].head(3).tolist() if not holders_df.empty else 'N/A'}")
            return None

        latest_entry = max(matched_entries, key=lambda x: x['date'])

        print(
            f"Info (Holder Helper): Latest report for '{latest_entry['holder_name']}' "
            f"({holder_target_name_exact}) in {ticker_symbol} found: "
            f"Date: {latest_entry['date'].strftime('%Y-%m-%d')}, Shares: {latest_entry['shares']:,}, "
            f"Reported Value: ${latest_entry['reported_value']:,}")
        return latest_entry['date'], latest_entry['shares'], latest_entry['reported_value']

    except Exception as e:
        print(f"Error in get_holder_latest_report_data for {ticker_symbol}/{holder_target_name_exact}: {e}")
        return None


def yfinance__calculate_institutional_holding_values(ticker_symbol, holder_name):
    """
    Calculates the expected data
    """

    print(f"Info (Calc Expected): Calculating for Ticker: {ticker_symbol}, Holder: {holder_name}")
    report_data = yfinance__get_holder_latest_report_data(ticker_symbol, holder_name)

    if report_data is None:
        return None

    report_date_dt, holder_shares, originally_reported_value = report_data

    price_on_date = None
    actual_price_date_used = report_date_dt

    try:
        price_fetch_start_str = report_date_dt.strftime('%Y-%m-%d')
        price_fetch_end_str = (report_date_dt + timedelta(days=1)).strftime('%Y-%m-%d')

        prices_df = yf.download(ticker_symbol,
                                start=price_fetch_start_str,
                                end=price_fetch_end_str,
                                progress=False, auto_adjust=False, actions=False)

        if not prices_df.empty and 'Close' in prices_df.columns:
            prices_df.index = pd.to_datetime(prices_df.index).normalize()
            target_datetime_norm = pd.to_datetime(report_date_dt)
            if target_datetime_norm in prices_df.index:
                price_on_date = prices_df.loc[target_datetime_norm, 'Close']

        if price_on_date is None:
            print(
                f"Info (Calc Expected): Primary price fetch for {ticker_symbol} on "
                f"{report_date_dt.strftime('%Y-%m-%d')} failed/NaN. Attempting ffill.")
            fetch_start_ffill = (report_date_dt - timedelta(days=10)).strftime('%Y-%m-%d')
            fetch_end_ffill = (report_date_dt + timedelta(days=2)).strftime('%Y-%m-%d')
            prices_wider_df = yf.download(
                ticker_symbol,
                start=fetch_start_ffill,
                end=fetch_end_ffill,
                progress=False,
                auto_adjust=False,
                actions=False
            )
            if prices_wider_df.empty or 'Close' not in prices_wider_df.columns:
                print(
                    f"Error (Calc Expected): No {ticker_symbol} price data with ffill "
                    f"fallback around {report_date_dt.strftime('%Y-%m-%d')}.")
                return None
            prices_wider_df.index = pd.to_datetime(prices_wider_df.index).normalize()
            target_timestamp_pd = pd.to_datetime(report_date_dt)
            if target_timestamp_pd < prices_wider_df.index.min():
                print(
                    f"Error (Calc Expected): Target date {report_date_dt.strftime('%Y-%m-%d')} "
                    f"before price data start for ffill.")
                return None
            price_series = prices_wider_df['Close'].reindex(
                [target_timestamp_pd], method='ffill')
            if price_series.empty:
                print(
                    f"Error (Calc Expected): Could not determine {ticker_symbol} price for "
                    f"{report_date_dt.strftime('%Y-%m-%d')} using ffill.")
                return None
            price_on_date = price_series.iloc[0]
            actual_price_date_used = price_series.index[0].date()
            if actual_price_date_used != report_date_dt:
                print(
                    f"Info (Calc Expected): Used {ticker_symbol} price from "
                    f"{actual_price_date_used.strftime('%Y-%m-%d')} for report date "
                    f"{report_date_dt.strftime('%Y-%m-%d')} (ffill).")

        if price_on_date is None:
            print(
                f"Error (Calc Expected): Failed to get valid {ticker_symbol} price "
                f"near {report_date_dt.strftime('%Y-%m-%d')}.")
            return None

        calculated_market_value = float(holder_shares * price_on_date.iloc[0])
        absolute_difference = abs(float(originally_reported_value) - calculated_market_value)

        print(
            f"Info (Calc Expected Task): {ticker_symbol} price on/near "
            f"{report_date_dt.strftime('%Y-%m-%d')} (actual used: "
            f"{actual_price_date_used.strftime('%Y-%m-%d')}): {price_on_date.iloc[0]:.2f}. "
            f"Shares: {holder_shares:,}. Orig Value: ${originally_reported_value:,.0f}. "
            f"Calc Value: ${calculated_market_value:,.2f}")

        return {
            'Date Reported': report_date_dt.strftime('%d%m%Y'),
            'originally reported value': float(originally_reported_value),
            'calculated market value': round(calculated_market_value, 2),
            'absolute difference': round(absolute_difference, 2)
        }
    except Exception as e:
        print(f"Error in calculate_expected_values ({ticker_symbol}): {e}")
        return None


def yfinance__moving_average_crossover_signal(stock_data, short_window=10, long_window=50):
    """
    Determines the trading signal based on a moving average crossover strategy.

    Args:
        stock_data (pd.DataFrame): DataFrame with a 'Date' and 'Close' column.
        short_window (int): The shorter moving average window.
        long_window (int): The longer moving average window.

    Returns:
        str: "buy", "sell", or "hold"
    """
    # Ensure data is sorted by date
    stock_data['date'] = pd.to_datetime(stock_data['date'])
    stock_data = stock_data.sort_values('date').reset_index(drop=True)

    # Calculate moving averages
    stock_data['SMA_short'] = stock_data['close_price'].rolling(window=short_window).mean()
    stock_data['SMA_long'] = stock_data['close_price'].rolling(window=long_window).mean()

    # Get the latest data point
    latest_data = stock_data.iloc[-1]
    previous_data = stock_data.iloc[-2]

    # Check for a crossover
    if (latest_data['SMA_short'] > latest_data['SMA_long'] and
            previous_data['SMA_short'] <= previous_data['SMA_long']):
        return "buy"
    if (latest_data['SMA_short'] < latest_data['SMA_long'] and
            previous_data['SMA_short'] >= previous_data['SMA_long']):
        return "sell"
    return "hold"


def yfinance__mean_reversion_bollinger_signal(stock_data, window=20, std_dev=2):
    """
    Determine the trading signal based on a mean reversion Bollinger Bands strategy.

    Args:
        stock_data (pd.DataFrame): DataFrame with a 'Date' and 'Close' column.
        window (int): The window period for calculating the moving average and standard deviation.
        std_dev (int): The number of standard deviations used to calculate the upper and lower bands.

    Returns:
        str: "buy", "sell", or "hold"
    """
    # Ensure data is sorted by date
    stock_data['date'] = pd.to_datetime(stock_data['date'])
    stock_data = stock_data.sort_values('date').reset_index(drop=True)

    # Calculate moving average (SMA) and standard deviation
    stock_data['SMA'] = stock_data['close_price'].rolling(window=window).mean()
    stock_data['StdDev'] = stock_data['close_price'].rolling(window=window).std()

    # Calculate the upper and lower bands
    stock_data['UpperBand'] = stock_data['SMA'] + (stock_data['StdDev'] * std_dev)
    stock_data['LowerBand'] = stock_data['SMA'] - (stock_data['StdDev'] * std_dev)

    # Get the latest data point
    latest_data = stock_data.iloc[-1]

    # Determine the signal
    if latest_data['close_price'] < latest_data['LowerBand']:
        return "buy"
    if latest_data['close_price'] > latest_data['UpperBand']:
        return "sell"
    return "hold"


def yfinance__roc_reversal_signal(
        stock_data, roc_period=12, overbought_threshold=20, oversold_threshold=-20
):
    """
    Determine the trading signal based on a rate of change (ROC) reversal strategy.

    Args:
        stock_data (pd.DataFrame): DataFrame with a 'Date' and 'Close' column.
        roc_period (int): The time window period for calculating the rate of change.
        overbought_threshold (float): The threshold for defining overbought conditions (positive value).
        oversold_threshold (float): The threshold for defining oversold conditions (negative value).

    Returns:
        str: "buy", "sell", or "hold"
    """
    # Ensure data is sorted by date
    stock_data['date'] = pd.to_datetime(stock_data['date'])
    stock_data = stock_data.sort_values('date').reset_index(drop=True)

    # Check if there is enough data to calculate ROC
    if len(stock_data) <= roc_period:
        return "hold"  # Not enough data

    # --- ROC calculation ---
    # Get the price N periods ago
    price_n_periods_ago = stock_data['close_price'].shift(roc_period)

    # Calculate ROC = [(current price - price N periods ago) / price N periods ago] * 100
    price_diff = stock_data['close_price'] - price_n_periods_ago
    stock_data['ROC'] = (price_diff / price_n_periods_ago) * 100

    # --- Signal determination ---
    # Get the latest data point
    latest_data = stock_data.iloc[-1]

    # If the latest ROC value is NaN (because of insufficient data), return "hold"
    if pd.isna(latest_data['ROC']):
        return "hold"

    # Determine the signal
    if latest_data['ROC'] < oversold_threshold:
        return "buy"
    if latest_data['ROC'] > overbought_threshold:
        return "sell"
    return "hold"


def yfinance__price_breakout_signal(stock_data, breakout_period=20, sell_threshold=0.97):
    """
    Determine the trading signal based on a Price Breakout strategy.

    Args:
        stock_data (pd.DataFrame): DataFrame with a 'date' and 'close_price' column.
        breakout_period (int): The lookback period to determine the highest high (for breakout).
        sell_threshold (float): The threshold for selling (e.g., 0.97 for 3% below the highest high).

    Returns:
        str: "buy", "sell", or "hold"
    """
    # Ensure data is sorted by date
    stock_data['date'] = pd.to_datetime(stock_data['date'])
    stock_data = stock_data.sort_values('date').reset_index(drop=True)

    # Check if there is enough data to calculate breakout
    if len(stock_data) <= breakout_period:
        return "hold"  # Not enough data

    # --- Breakout calculation ---
    # Calculate the highest close in the past `breakout_period` days (excluding today)
    shifted_prices = stock_data['close_price'].shift(1)
    stock_data['rolling_high'] = shifted_prices.rolling(window=breakout_period).max()

    # --- Signal determination ---
    latest_data = stock_data.iloc[-1]

    if pd.isna(latest_data['rolling_high']):
        return "hold"

    if latest_data['close_price'] > latest_data['rolling_high']:
        return "buy"
    if latest_data['close_price'] < latest_data['rolling_high'] * sell_threshold:
        return "sell"
    return "hold"


def yfinance__ma_distance_reversion_signal(stock_data, ma_period=20, threshold=0.05):
    """
    Determine the trading signal based on a Moving Average Distance Reversion strategy.

    Args:
        stock_data (pd.DataFrame): DataFrame with 'date' and 'close_price' columns.
        ma_period (int): The lookback period for the moving average (e.g., 20 days).
        threshold (float): The distance threshold as a fraction (e.g., 0.05 for 5%).

    Returns:
        str: "buy", "sell", or "hold"
    """
    # Ensure data is sorted by date
    stock_data['date'] = pd.to_datetime(stock_data['date'])
    stock_data = stock_data.sort_values('date').reset_index(drop=True)

    # Check if there is enough data to calculate the moving average
    if len(stock_data) < ma_period:
        return "hold"  # Not enough data

    # --- Moving average calculation ---
    stock_data['sma'] = stock_data['close_price'].rolling(window=ma_period).mean()

    # --- Signal determination ---
    latest_data = stock_data.iloc[-1]

    if pd.isna(latest_data['sma']):
        return "hold"

    price = latest_data['close_price']
    sma = latest_data['sma']
    distance = (price - sma) / sma

    if distance < -threshold:
        return "buy"
    if distance > threshold:
        return "sell"
    return "hold"


def yfinance__check_net_income_growth(ticker_symbol, num_quarters):
    """
    Check if a company's net income has grown for num_quarters consecutive quarters.

    Args:
        ticker_symbol (str): The stock ticker symbol (e.g., 'AAPL').
        num_quarters (int): The number of consecutive quarters to check.
    Returns:
        bool: True if net income grew for four consecutive quarters, otherwise False.
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        income_df = ticker.quarterly_financials

        # Ensure Net Income row exists
        if 'Net Income' not in income_df.index:
            return False, f"Net Income not found for {ticker_symbol}"

        # Extract the last num_quarters quarters of net income
        net_income_series = income_df.loc['Net Income'].dropna()

        # Ensure at least num_quarters quarters are available
        if len(net_income_series) < num_quarters:
            return False, f"Not enough quarters for {ticker_symbol}"

        # Take the most recent 4 quarters
        recent_net_income = net_income_series.iloc[:num_quarters]

        # Check if net income is strictly increasing over these quarters
        is_increasing = all(
            recent_net_income.iloc[i] > recent_net_income.iloc[i + 1]
            for i in range(num_quarters - 1)
        )

        return is_increasing, f"Net income growth for {ticker_symbol}"

    except Exception as e:
        return False, f"Error checking ticker {ticker_symbol}: {e}"


def yfinance__check_dividend_consistency(ticker_symbol, min_years=5):
    """
    Check if a company has paid dividends consistently for at least `min_years` years.

    Args:
        ticker_symbol (str): The stock ticker symbol (e.g., 'T', 'KO').
        min_years (int): Minimum number of years of consistent dividend payments.

    Returns:
        (bool, str): Tuple of (condition_met, message)
    """
    try:
        ticker = yf.Ticker(ticker_symbol)

        # Get dividend history (Series with date index)
        dividends = ticker.dividends

        if dividends.empty:
            return False, f"No dividend history found for {ticker_symbol}"

        # Get all years where dividend was paid at least once
        years_with_dividends = dividends.index.year
        unique_years = sorted(set(years_with_dividends), reverse=True)  # Sort descending (most recent first)

        if len(unique_years) < min_years:
            return False, f"{ticker_symbol} has dividends in only {len(unique_years)} years"

        # Check if the most recent min_years are consecutive
        most_recent_years = unique_years[:min_years]
        for i in range(len(most_recent_years) - 1):
            if most_recent_years[i] - most_recent_years[i + 1] != 1:
                return False, (f"{ticker_symbol} does not have {min_years} consecutive years "
                               f"of dividends (missing year between {most_recent_years[i]} "
                               f"and {most_recent_years[i + 1]})")

        return True, f"{ticker_symbol} passed: {len(unique_years)} years of dividends"

    except Exception as e:
        return False, f"Error checking {ticker_symbol}: {e}"


def yfinance__get_nearest_expiry_date(ticker_symbol):
    """
    Get the nearest available options expiry date for a given stock ticker.

    Args:
        ticker_symbol (str): The stock ticker symbol (e.g., 'AAPL', 'TSLA').

    Returns:
        (bool, str): Tuple of (success flag, expiry date string or error message)
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        expiry_dates = ticker.options

        if not expiry_dates:
            return False, f"No expiry dates found for {ticker_symbol}"

        # Sort dates chronologically
        sorted_dates = sorted(expiry_dates, key=lambda x: datetime.strptime(x, "%Y-%m-%d"))

        # Return the soonest upcoming expiry
        return True, sorted_dates[0]

    except Exception as e:
        return False, f"Error retrieving expiry dates for {ticker_symbol}: {e}"


def yfinance__find_highest_iv_otm_call(ticker_symbol, expiry_date):
    """
    Find the out-of-the-money (OTM) call option with the highest implied volatility (IV)
    for a given stock and expiration date.

    Args:
        ticker_symbol (str): The stock ticker symbol (e.g., 'AAPL', 'TSLA').
        expiry_date (str): The expiration date in format 'YYYY-MM-DD'.

    Returns:
        (bool, str or dict): 
            If successful, returns (True, dict with option details). 
            Otherwise, returns (False, error message).
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        spot_price = ticker.history(period="1d")["Close"][-1]

        # Get option chain
        option_chain = ticker.option_chain(expiry_date)
        calls = option_chain.calls

        if calls.empty:
            return False, f"No call options found for {ticker_symbol} on {expiry_date}"

        # Filter out-of-the-money calls (strike > current stock price)
        otm_calls = calls[calls['strike'] > spot_price]

        if otm_calls.empty:
            return False, f"No OTM call options available for {ticker_symbol} on {expiry_date}"

        # Find the OTM call with the highest implied volatility
        highest_iv_row = otm_calls.loc[otm_calls['impliedVolatility'].idxmax()]

        result = {
            "symbol": ticker_symbol,
            "expiration": expiry_date,
            "strike": highest_iv_row["strike"],
            "implied_volatility": highest_iv_row["impliedVolatility"],
            "last_price": highest_iv_row["lastPrice"],
            "bid": highest_iv_row["bid"],
            "ask": highest_iv_row["ask"],
            "in_the_money": highest_iv_row["inTheMoney"]
        }

        return True, result

    except Exception as e:
        return False, f"Error processing {ticker_symbol} on {expiry_date}: {e}"


##################################################################################
# Eval Function for Yahoo-Finance
##################################################################################

@compare_func(name="yfinance.check_highest_iv_otm_call_task_output")
async def check_highest_iv_otm_call_task_output(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output for the 
    highest IV OTM call task.
    """
    _, op_args = args
    user_output_dict = x
    ticker = op_args['ticker']

    # check format
    expected_keys = ['ticker', 'expiration', 'strike', 'implied_volatility',
                     'last_price', 'bid', 'ask', 'in_the_money']
    for key in expected_keys:
        if key not in user_output_dict:
            return False, f"Output format error: Missing key '{key}'."

    # check ticker
    if user_output_dict['ticker'] != ticker:
        return False, f"Ticker error: Expected {ticker}, but got {user_output_dict['ticker']}"

    # check expiration
    success, expiry_date = yfinance__get_nearest_expiry_date(ticker)
    if not success:
        return False, f"Error retrieving expiry date for {ticker}: {expiry_date}"
    if user_output_dict['expiration'] != expiry_date:
        return False, (f"Expiration error: Expected {expiry_date}, but got "
                       f"{user_output_dict['expiration']}")

    # Check others
    success, result = yfinance__find_highest_iv_otm_call(ticker, expiry_date)
    if not success:
        return False, (f"Error finding highest IV OTM call for {ticker} on "
                       f"{expiry_date}: {result}")

    # check strike
    if abs(user_output_dict['strike'] - result['strike']) > 0.001:
        return (False, f"Strike error: Expected {result['strike']}, "
                       f"but got {user_output_dict['strike']}")

    # check implied volatility
    if abs(user_output_dict['implied_volatility'] - result['implied_volatility']) > 0.001:
        return False, (f"Implied volatility error: Expected {result['implied_volatility']}, "
                       f"but got {user_output_dict['implied_volatility']}")

    # check last price
    if abs(user_output_dict['last_price'] - result['last_price']) > 0.001:
        return (False, f"Last price error: Expected {result['last_price']}, "
                       f"but got {user_output_dict['last_price']}")

    # check bid
    if abs(user_output_dict['bid'] - result['bid']) > 0.001:
        return False, f"Bid error: Expected {result['bid']}, but got {user_output_dict['bid']}"

    # check ask
    if abs(user_output_dict['ask'] - result['ask']) > 0.001:
        return False, f"Ask error: Expected {result['ask']}, but got {user_output_dict['ask']}"

    # check in the money
    if user_output_dict['in_the_money'] != result['in_the_money']:
        return False, (f"In the money error: Expected {result['in_the_money']}, "
                       f"but got {user_output_dict['in_the_money']}")

    return True, ""


@compare_func(name="yfinance.check_dividend_consistency_task_output")
async def check_dividend_consistency_task_output(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output for the dividend consistency task.
    """
    _, op_args = args
    user_output_dict = x
    num_tickers = op_args['num_tickers']
    min_years = op_args['min_years']

    # check format
    expected_keys = ['tickers']
    for key in expected_keys:
        if key not in user_output_dict:
            return False, f"Output format error: Missing key '{key}'."
        try:
            user_output_dict[key] = list(user_output_dict[key])
        except Exception:
            return False, f"Output format error: Value for '{key}' is not a list"

    # check tickers
    tickers = user_output_dict['tickers']

    if len(tickers) != num_tickers:
        return False, f"Output format error: Value for 'tickers' is not equal to {num_tickers}"

    # check dividend consistency
    for ticker in tickers:
        if not yfinance__check_dividend_consistency(ticker, min_years)[0]:
            return False, (f"Dividend consistency error: {ticker} does not have {min_years} "
                           f"years of consistent dividend payments")
    return True, ""


@compare_func(name="yfinance.check_net_income_growth_task_output")
async def check_net_income_growth_task_output(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output for the net income growth task.

    Args:
        x: The user's output.
        args: The task details.
    """
    _, op_args = args
    user_output_dict = x
    num_quarters = op_args['num_quarters']
    num_tickers = op_args['num_tickers']

    # check format
    expected_keys = ['tickers']
    for key in expected_keys:
        if key not in user_output_dict:
            return False, f"Output format error: Missing key '{key}'."
        try:
            user_output_dict[key] = list(user_output_dict[key])
        except Exception:
            return False, f"Output format error: Value for '{key}' is not a list"

    # check tickers
    tickers = user_output_dict['tickers']

    if len(tickers) != num_tickers:
        return False, f"Output format error: Value for 'tickers' is not equal to {num_tickers}"

    # check net income growth
    for ticker in tickers:
        if not yfinance__check_net_income_growth(ticker, num_quarters)[0]:
            return False, (f"Net income growth error: {ticker} does not have {num_quarters} "
                           f"consecutive quarters of rising net income")
    return True, ""


@compare_func(name="yfinance.check_quant_investment_task_output")
async def check_quant_investment_task_output(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output for the quant investment task.

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args
    user_output_dict = x

    # check format
    expected_keys = ['date', 'earn']
    for key in expected_keys:
        if key not in user_output_dict:
            return False, f"Output format error: Missing key '{key}'."
        try:
            user_output_dict[key] = str(user_output_dict[key])
        except Exception:
            return False, f"Output format error: Value for '{key}' is not a string"

    # get data
    ticker = op_args['ticker']
    start_date = op_args['start_date']
    end_date = op_args['end_date']
    initial_investment = op_args['initial_investment']

    # get user date and earn
    try:
        user_date = user_output_dict['date']
    except Exception:
        return False, "Output format error for 'date'."
    try:
        user_earn = float(user_output_dict['earn'])
    except Exception:
        return False, "Output format error for 'earn'."

    # check date
    if user_date != start_date:
        return False, f"Date error: Expected {start_date}, but got {user_date}"

    # get expected value
    expected_final_value, _ = yfinance__calculate_portfolio_return(
        [ticker], start_date, end_date, initial_investment, [1.0]
    )
    expected_earn = expected_final_value - initial_investment

    # check earn
    if abs(user_earn - expected_earn) > 0.5:
        return False, f"Earn error: Expected {expected_earn}, but got {user_earn}"

    return True, ""


@compare_func(name="yfinance.check_buy_sell_hold_signal")
async def check_buy_sell_hold_signal(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output for the portfolio investment task.

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args
    user_output_dict = x

    # check format
    expected_keys = ['check_buy_sell_hold_signal']
    for key in expected_keys:
        if key not in user_output_dict:
            return False, f"Output format error: Missing key '{key}'."
        try:
            user_output_dict[key] = str(user_output_dict[key])
        except Exception:
            return False, f"Output format error: Value for '{key}' is not a string"

    # get data
    ticker = op_args['ticker']
    date = op_args['date']
    quant_strategy_name = op_args['quant_strategy']['name']
    quant_strategy_params = op_args['quant_strategy']['params']

    # get stock data
    # Calculate start date (100 days before the target date)
    target_date = datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)
    start_date = target_date - timedelta(days=100)
    start_date_str = start_date.strftime("%Y-%m-%d")

    # Download stock data for the 100-day period
    stock_data = yf.download(ticker, start=start_date_str, end=target_date,
                             progress=False)
    if stock_data.empty:
        return False, f"Stock data for {ticker} from {start_date_str} to {target_date} is empty"

    # Convert to DataFrame with date and close price columns
    stock_df = pd.DataFrame({
        'date': stock_data.index,
        'close_price': stock_data['Close'].values.reshape(1, -1)[0],
    }).reset_index(drop=True)

    # get signal
    if quant_strategy_name == "moving_average_crossover":
        signal = yfinance__moving_average_crossover_signal(
            stock_df, **quant_strategy_params)
    elif quant_strategy_name == "mean_reversion_bollinger":
        signal = yfinance__mean_reversion_bollinger_signal(
            stock_df, **quant_strategy_params)
    elif quant_strategy_name == "roc_reversal":
        signal = yfinance__roc_reversal_signal(stock_df, **quant_strategy_params)
    elif quant_strategy_name == "price_breakout":
        signal = yfinance__price_breakout_signal(stock_df, **quant_strategy_params)
    elif quant_strategy_name == "ma_distance_reversion":
        signal = yfinance__ma_distance_reversion_signal(stock_df, **quant_strategy_params)
    elif quant_strategy_name == "mean_reversion_bollinger_plus_moving_average_crossover":
        signal_ma = yfinance__moving_average_crossover_signal(
            stock_df, **quant_strategy_params['moving_average_crossover_params'])
        signal_mr = yfinance__mean_reversion_bollinger_signal(
            stock_df, **quant_strategy_params['mean_reversion_bollinger_params'])
        if ((signal_ma == "buy" and signal_mr == "buy") or
                (signal_ma == "buy" and signal_mr == "hold") or
                (signal_ma == "hold" and signal_mr == "buy")):
            signal = "buy"
        elif ((signal_ma == "sell" and signal_mr == "sell") or
              (signal_ma == "sell" and signal_mr == "hold") or
              (signal_ma == "hold" and signal_mr == "sell")):
            signal = "sell"
        else:
            signal = "hold"
    elif quant_strategy_name == "mean_reversion_bollinger_plus_roc_reversal":
        signal_ma = yfinance__mean_reversion_bollinger_signal(
            stock_df, **quant_strategy_params['mean_reversion_bollinger_params'])
        signal_rr = yfinance__roc_reversal_signal(stock_df, **quant_strategy_params['roc_reversal_params'])
        if ((signal_ma == "buy" and signal_rr == "buy") or
                (signal_ma == "buy" and signal_rr == "hold") or
                (signal_ma == "hold" and signal_rr == "buy")):
            signal = "buy"
        elif ((signal_ma == "sell" and signal_rr == "sell") or
              (signal_ma == "sell" and signal_rr == "hold") or
              (signal_ma == "hold" and signal_rr == "sell")):
            signal = "sell"
        else:
            signal = "hold"
    elif quant_strategy_name == "mean_reversion_bollinger_plus_ma_distance_reversion":
        signal_ma = yfinance__mean_reversion_bollinger_signal(
            stock_df, **quant_strategy_params['mean_reversion_bollinger_params'])
        signal_ma_distance = yfinance__ma_distance_reversion_signal(
            stock_df, **quant_strategy_params['ma_distance_reversion_params'])
        if ((signal_ma == "buy" and signal_ma_distance == "buy") or
                (signal_ma == "buy" and signal_ma_distance == "hold") or
                (signal_ma == "hold" and signal_ma_distance == "buy")):
            signal = "buy"
        elif ((signal_ma == "sell" and signal_ma_distance == "sell") or
              (signal_ma == "sell" and signal_ma_distance == "hold") or
              (signal_ma == "hold" and signal_ma_distance == "sell")):
            signal = "sell"
        else:
            signal = "hold"
    else:
        return False, f"Quant strategy {quant_strategy_name} not supported"

    # compare signal
    if signal in user_output_dict['check_buy_sell_hold_signal'].lower():
        return True, ""
    return False, f"Signal error: Expected {signal}, but got {user_output_dict['check_buy_sell_hold_signal']}"


@compare_func(name="yfinance.check_portfolio_task_output")
async def check_portfolio_task_output(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output for the portfolio investment task.

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args
    user_output_dict = x

    # check format
    expected_keys = ['total value', 'total percentage return']
    for key in expected_keys:
        if key not in user_output_dict:
            return False, f"Output format error: Missing key '{key}'."
        try:
            user_output_dict[key] = float(user_output_dict[key])
        except Exception:
            return False, f"Output format error: Value for '{key}' is not a float"

    # Get data
    tickers = op_args["tickers"]
    initial_investment = op_args["initial_investment"]
    start_date_str = op_args["start_date"]
    end_date_str = op_args["end_date"]
    split = op_args["split"]

    # Compute yfinance return
    expected_final_value, expected_percentage_return = yfinance__calculate_portfolio_return(
        tickers, start_date_str, end_date_str, initial_investment, split
    )

    # Compare result
    final_value_tolerance = 0.5
    percentage_return_tolerance = 0.05
    user_final_value = user_output_dict['total value']
    user_percentage_return = user_output_dict['total percentage return']

    if abs(user_final_value - expected_final_value) > final_value_tolerance:
        return False, (f"Value error for 'total value': Expected approximately "
                       f"{expected_final_value:.2f}, but got {user_final_value:.2f}.")
    if abs(user_percentage_return - expected_percentage_return) > percentage_return_tolerance:
        return False, (f"Value error for 'total percentage return': Expected approximately "
                       f"{expected_percentage_return:.2f}%, but got {user_percentage_return:.2f}%.")
    return True, ""


# ----------------------------------------------------------------
# gross_profit_margin
# ----------------------------------------------------------------
@compare_func(name="yfinance.check_gross_profit_margin")
async def check_gross_profit_margin(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args
    ticker = op_args['ticker']
    actual_gross_profit = yfinance__get_lastest_year_raw_gross_profit_margin(ticker) * 100  # percentage figure
    if ticker not in x:
        return False, f"ticker:{ticker} is not in llm response"
    if 'gross profit margin' not in x[ticker]:
        return False, f"key: gross profit margin is not in ticker:{ticker}"

    llm_gross_profit = float(x[ticker]['gross profit margin'])
    margin_tolerance = 0.05

    if abs(actual_gross_profit - llm_gross_profit) > margin_tolerance:
        return False, f"{ticker} gross price error"
    return True, ""


@compare_func(name="yfinance.compare_companies_gross_profit_margin")
async def compare_companies_gross_profit_margin(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args

    # check the output format
    for ticker in op_args['tickers']:
        if not ticker in x:
            return False, f"{ticker} is not in llm response"
        if 'gross profit margin' not in x[ticker]:
            return False, f"key: gross profit margin is not in ticker:{ticker}"

    if "company with higher gross profit margin" not in x:
        return False, "key: company with higher gross profit margin is not in llm response"

    # get actual gross prices
    actual_gross_dict = {}
    for ticker in op_args['tickers']:
        actual_gross_dict[ticker] = yfinance__get_lastest_year_raw_gross_profit_margin(
            ticker) * 100  # percentage figure

    # check the higher gross company
    actual_higher_gross_ticker = max(actual_gross_dict, key=actual_gross_dict.get)

    if actual_higher_gross_ticker == x['company with higher gross profit margin']:
        return True, ""
    return False, "the company with higher gross profit margin is wrong"


# ----------------------------------------------------------------
# net_profit_margin
# ----------------------------------------------------------------

@compare_func(name="yfinance.check_net_profit_margin")
async def check_net_profit_margin(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args
    ticker = op_args['ticker']
    actual_net_profit = yfinance__get_lastest_year_raw_net_profit_margin(ticker) * 100  # percentage figure
    if ticker not in x:
        return False, f"ticker:{ticker} is not in llm response"
    if 'net profit margin' not in x[ticker]:
        return False, f"key: net profit margin is not in ticker:{ticker}"

    llm_net_profit = float(x[ticker]['net profit margin'])
    margin_tolerance = 0.05
    if abs(actual_net_profit - llm_net_profit) > margin_tolerance:
        return False, f"{ticker} net profit margin error"
    return True, ""


@compare_func(name="yfinance.compare_companies_net_profit_margin")
async def compare_companies_net_profit_margin(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output.

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args

    # check the output format
    for ticker in op_args['tickers']:
        if not ticker in x:
            return False, f"{ticker} is not in llm response"
        if 'net profit margin' not in x[ticker]:
            return False, f"key: [net profit margin] is not in ticker:{ticker}"

    if "company with highest net profit margin" not in x:
        return False, "key: [company with highest net profit margin] is not in llm response"

    # get actual net profits
    actual_net_profit_dict = {}
    for ticker in op_args['tickers']:
        actual_net_profit_dict[ticker] = yfinance__get_lastest_year_raw_net_profit_margin(ticker)

    # check the higher net profit company
    actual_higher_ticker = max(actual_net_profit_dict, key=actual_net_profit_dict.get)

    if actual_higher_ticker == x['company with highest net profit margin']:
        return True, ""
    return False, "the company with company with highest net profit margin is wrong"


# ----------------------------------------------------------------
# net_profit_margin
# ----------------------------------------------------------------
@compare_func(name="yfinance.check_rd_expense")
async def check_rd_expense(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args
    ticker = op_args['ticker']
    financial_data = yfinance__get_latest_financial_data(ticker_symbol=ticker)
    if financial_data is None:
        return False, f"get financial_data for ticket {ticker} error "

    actual_rd_expense = financial_data['rd expense']
    if ticker not in x:
        return False, f"ticker:{ticker} is not in llm response"
    if 'R&D expense' not in x[ticker]:
        return False, f"key: R&D expense is not in ticker:{ticker}"

    llm_rd_expense = float(x[ticker]['R&D expense'])
    margin_tolerance = 0.05
    if abs(actual_rd_expense - llm_rd_expense) > margin_tolerance:
        return False, f"{ticker} R&D expense data error"
    return True, ""


@compare_func(name="yfinance.check_rd_expense_percentage")
async def check_rd_expense_percentage(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args
    ticker = op_args['ticker']
    actual_rd_expense_percentage = yfinance__get_lastest_year_raw_rd_expense(ticker) * 100  # percentage figure
    if ticker not in x:
        return False, f"ticker:{ticker} is not in llm response"
    if 'R&D expense percentage' not in x[ticker]:
        return False, f"key: R&D expense percentage is not in ticker:{ticker}"

    llm_rd_expense_percentage = float(x[ticker]['R&D expense percentage'])
    margin_tolerance = 0.05
    if abs(actual_rd_expense_percentage - llm_rd_expense_percentage) > margin_tolerance:
        return False, f"{ticker} R&D expense percentage error"
    return True, ""


@compare_func(name="yfinance.compare_companies_rd_expense_percentage")
async def compare_companies_rd_expense_percentage(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output.

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args

    # check the output format
    for ticker in op_args['tickers']:
        if not ticker in x:
            return False, f"{ticker} is not in llm response"
        if 'R&D expense percentage' not in x[ticker]:
            return False, f"key: [R&D expense percentage] is not in ticker:{ticker}"

    if "company with higher R&D expense percentage" not in x:
        return False, "key: [company with higher R&D expense percentage] is not in llm response"

    # get actual net profits
    actual_rd_expense_dict = {}
    for ticker in op_args['tickers']:
        actual_rd_expense_dict[ticker] = yfinance__get_lastest_year_raw_rd_expense(ticker) * 100  # percetange figure

    # check the higher R&D expense percentage
    actual_higher_ticker = max(actual_rd_expense_dict, key=actual_rd_expense_dict.get)

    if actual_higher_ticker == x['company with higher R&D expense percentage']:
        return True, ""
    return False, "the company with company with higher R&D expense percentage is wrong"


@compare_func(name="yfinance.check_total_revenue")
async def check_total_revenue(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args
    ticker = op_args['ticker']
    financial_data = yfinance__get_latest_financial_data(ticker_symbol=ticker)
    if financial_data is None:
        return False, f"get financial_data for ticket {ticker} error "

    actual_total_revenue = financial_data['total revenue']
    if ticker not in x:
        return False, f"ticker:{ticker} is not in llm response"
    if 'total revenue' not in x[ticker]:
        return False, f"key: total revenue is not in ticker:{ticker}"

    llm_total_revenue = float(x[ticker]['total revenue'])
    margin_tolerance = 0.05
    if abs(actual_total_revenue - llm_total_revenue) > margin_tolerance:
        return False, f"{ticker} total revenue error"
    return True, ""


@compare_func(name="yfinance.check_operating_income")
async def check_operating_income(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args
    ticker = op_args['ticker']
    financial_data = yfinance__get_latest_financial_data(ticker_symbol=ticker)
    if financial_data is None:
        return False, f"get financial_data for ticket {ticker} error "

    actual_operating_income = financial_data['operating income']
    if ticker not in x:
        return False, f"ticker:{ticker} is not in llm response"
    if 'operating income' not in x[ticker]:
        return False, f"key: operating income is not in ticker:{ticker}"

    llm_operating_income = float(x[ticker]['operating income'])
    margin_tolerance = 0.05
    if abs(actual_operating_income - llm_operating_income) > margin_tolerance:
        return False, f"{ticker} operating income error"
    return True, ""


@compare_func(name="yfinance.check_net_income")
async def check_net_income(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args
    ticker = op_args['ticker']
    period = op_args['period']
    assert period in ['annually', 'quarterly']

    financial_data = yfinance__get_latest_financial_data(ticker_symbol=ticker, period=period)
    if financial_data is None:
        return False, f"get financial_data for ticket {ticker} error "

    actual_net_income = financial_data['net income']
    if ticker not in x:
        return False, f"ticker: {ticker} is not in llm response"
    if f'net income common stockholders {period}' not in x[ticker]:
        return False, f"key: net income is not in ticker: {ticker}"

    llm_net_income = float(x[ticker][f'net income common stockholders {period}'])
    margin_tolerance = 0.05
    if abs(actual_net_income - llm_net_income) > margin_tolerance:
        return False, f"{ticker} net income error"
    return True, ""


@compare_func(name="yfinance.check_net_income_difference")
async def check_net_income_difference(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args
    ticker = op_args['ticker']
    periods = op_args['periods']
    for period in periods:
        assert period in ['annually', 'quarterly']

    actual_net_income_list = []
    for period in periods:
        financial_data = yfinance__get_latest_financial_data(ticker_symbol=ticker, period=period)
        if financial_data is None:
            return False, f"get financial_data for ticket {ticker} error "
        actual_net_income_list.append(financial_data['net income'])

    actual_net_income_difference = abs(actual_net_income_list[0] - actual_net_income_list[1])

    if ticker not in x:
        return False, f"ticker: {ticker} is not in llm response"
    if 'difference' not in x[ticker]:
        return False, f"key: difference is not in ticker: {ticker}"

    llm_net_income_difference = float(x[ticker]['difference'])
    margin_tolerance = 0.05
    if abs(actual_net_income_difference - llm_net_income_difference) > margin_tolerance:
        return False, f"{ticker} net income difference error"
    return True, ""


@compare_func(name="yfinance.check_percentage_change")
async def check_percentage_change(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """

    _, op_args = args
    min_pct_change = op_args['minPctChange']
    ticker = op_args['ticker']

    user_output_dict = x
    user_holders_list = user_output_dict['institutional holders']

    expected_data = yfinance__get_filtered_institutional_holders(ticker, min_pct_change)
    user_agg_value = user_output_dict['aggregate market value']
    expected_holders_list = expected_data['institutional holders']
    expected_agg_value = expected_data['aggregate market value']

    # Compare 'aggregate market value'
    # Using a relative tolerance for this large sum. 0.1% = 0.001
    agg_value_relative_tolerance = 0.001
    if expected_agg_value == 0:  # If expected is 0, user must also provide 0 or very close
        if abs(user_agg_value) > 1:  # Allow a tiny absolute diff if expected is 0
            return False, (f"Value error for 'aggregate market value': "
                           f"Expected {expected_agg_value:,.0f}, got {user_agg_value:,.0f}.")
    else:
        tolerance_val = abs(expected_agg_value) * agg_value_relative_tolerance
        if abs(user_agg_value - expected_agg_value) > tolerance_val:
            # Add a small absolute threshold too, so tiny relative diffs on huge numbers
            # don't fail if they are small absolutely
            min_threshold = max(1000, abs(expected_agg_value) * agg_value_relative_tolerance * 0.1)
            if abs(user_agg_value - expected_agg_value) > min_threshold:
                return False, (f"Value error for 'aggregate market value': "
                               f"Expected approximately {expected_agg_value:,.0f}, "
                               f"got {user_agg_value:,.0f}.")

    # Compare the list of 'institutional holders'
    if len(user_holders_list) != len(expected_holders_list):
        return False, (f"List length mismatch for 'institutional holders': "
                       f"Expected {len(expected_holders_list)} institutions, "
                       f"user provided {len(user_holders_list)}.")

    # Sort both lists by institution name (case-insensitive) for stable comparison
    try:
        user_list_sorted = sorted(user_holders_list, key=lambda x: str(x.get('institution', '')).lower())
        expected_list_sorted = sorted(expected_holders_list, key=lambda x: str(x.get('institution', '')).lower())
    except Exception as e_sort:
        return False, f"Internal error: Could not sort holder lists for comparison. Details: {e_sort}"

    # Tolerances for individual item comparison
    item_value_relative_tolerance = 0.001  # 0.1% for individual 'value'
    item_pct_change_absolute_tolerance = 0.00015  # For 'pctChange' values like 0.025 vs 0.0251

    for i, _ in enumerate(expected_list_sorted):
        exp_item = expected_list_sorted[i]
        usr_item = user_list_sorted[i]  # Assumes user list has same structure (checked by format validation)

        exp_inst_name = str(exp_item.get('institution', '')).lower()
        usr_inst_name = str(usr_item.get('institution', '')).lower()

        if exp_inst_name != usr_inst_name:
            return False, (f"List content mismatch at sorted index {i}: "
                           f"Expected institution '{exp_item.get('institution')}', "
                           f"but found '{usr_item.get('institution')}' at this position after sorting. "
                           f"Lists may contain different institutions or naming variations.")

        # Compare 'value' for the matched institution
        exp_val_item = exp_item.get('value', 0.0)
        usr_val_item = usr_item.get('value', 0.0)
        if exp_val_item == 0:
            if abs(usr_val_item) > 1:  # Allow small absolute diff if expected is 0
                return False, (f"Value error for institution '{exp_item.get('institution')}', "
                               f"field 'value': Expected {exp_val_item:,.0f}, "
                               f"got {usr_val_item:,.0f}.")
        elif abs(usr_val_item - exp_val_item) > (abs(exp_val_item) * item_value_relative_tolerance):
            max_allowed_diff = max(1000, abs(exp_val_item) * item_value_relative_tolerance * 0.1)
            if abs(usr_val_item - exp_val_item) > max_allowed_diff:
                return False, (f"Value error for institution '{exp_item.get('institution')}', "
                               f"field 'value': Expected ~{exp_val_item:,.0f}, "
                               f"got {usr_val_item:,.0f}.")

        # Compare 'pctChange' for the matched institution
        exp_pct_item = exp_item.get('pctChange', 0.0)
        usr_pct_item = usr_item.get('pctChange', 0.0)
        if abs(usr_pct_item - exp_pct_item) > item_pct_change_absolute_tolerance:
            return False, (f"Value error for institution '{exp_item.get('institution')}', "
                           f"field 'pctChange': Expected ~{exp_pct_item:.4f}, "
                           f"got {usr_pct_item:.4f}.")

    return True, ""


@compare_func(name="yfinance.check_largest_positive_increase")
async def check_largest_positive_increase(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args
    user_output_dict = x
    tickers = op_args['tickers']
    calculated_pct_changes = {}
    retrieval_fully_successful = True  # Assume success initially for all tickers

    largest_inc_company_user = user_output_dict.get("company with largest positive increase", None)

    for ticker in tickers:
        change = yfinance__get_blackrock_pct_change(ticker)
        calculated_pct_changes[ticker] = change  # Will store None if failed for this ticker

        user_val_for_ticker = float(user_output_dict[ticker]['pctChange'])  # Assumed to exist due to format check

        if change is None:
            retrieval_fully_successful = False
            return False, (f"Verification error for {ticker} 'pctChange': "
                           f"Could not retrieve/calculate expected value for Blackrock Inc. "
                           f"User provided {user_val_for_ticker:.4f}. "
                           f"This may be due to 'Blackrock Inc.' not being listed, or "
                           f"'pctChange' data being unavailable/unparseable in yfinance.")
        # Compare individual pctChange for this ticker
        pct_change_item_absolute_tolerance = 0.00015  # e.g. 0.0200 vs 0.0201
        if abs(user_val_for_ticker - change) > pct_change_item_absolute_tolerance:
            return False, (f"Value error for {ticker} 'pctChange' for Blackrock Inc.: "
                           f"Expected ~{change:.4f}, got {user_val_for_ticker:.4f}.")

    # --- Determine and Compare 'company with largest positive increase...' ---
    expected_largest_increase_company_ticker = None  # Default state

    if not retrieval_fully_successful:
        return False, ("Cannot definitively verify 'company with largest positive increase...' "
                       "because Blackrock Inc.'s pctChange data for one or more companies "
                       "could not be retrieved/calculated.")
    # All three pctChange values were successfully retrieved (are not None)
    positive_changes = {t: ch for t, ch in calculated_pct_changes.items() if ch is not None and ch > 0}

    if not positive_changes:
        expected_largest_increase_company_ticker = "NO_POSITIVE_INCREASE"
    else:
        # Find the max positive change
        # current_max_change = 0  # Smallest positive change will be > 0
        # Initialize to ensure any positive change is picked up
        # alternative: current_max_change = max(positive_changes.values()) if positive_changes else -1

        # Find the actual maximum value among positive changes
        actual_max_positive_change = -1.0
        for _, change_val in positive_changes.items():
            actual_max_positive_change = max(change_val, actual_max_positive_change)

        epsilon = 1e-9  # For float comparison for ties
        highest_companies_list = [ticker for ticker, change in positive_changes.items() if
                                  abs(change - actual_max_positive_change) < epsilon]

        if len(highest_companies_list) == 1:
            expected_largest_increase_company_ticker = highest_companies_list[0]
        else:  # Tie for the largest positive change
            expected_largest_increase_company_ticker = "TIE_FOR_LARGEST_POSITIVE"

    # Now compare with user's choice
    if expected_largest_increase_company_ticker == "NO_POSITIVE_INCREASE":
        return False, (f"Comparison error: No company showed a positive increase in "
                       f"Blackrock Inc.'s stake. User claimed '{largest_inc_company_user}' "
                       f"had the largest positive increase.")
    if expected_largest_increase_company_ticker == "TIE_FOR_LARGEST_POSITIVE":
        change_details = ", ".join([f"{t}:{calculated_pct_changes[t]:.4f}" for t in highest_companies_list])
        return False, (f"Comparison ambiguity: Multiple companies tied for the largest "
                       f"positive increase for Blackrock Inc. ({change_details}). "
                       f"User claimed '{largest_inc_company_user}'.")
    if largest_inc_company_user != expected_largest_increase_company_ticker:
        # This also catches if expected_largest_increase_company_ticker is None due to
        # an earlier logic path error not caught by retrieval_fully_successful
        return False, (f"Comparison error for 'company with largest positive increase...': "
                       f"Expected '{expected_largest_increase_company_ticker}', "
                       f"got '{largest_inc_company_user}'.")
    return True, ""


@compare_func(name="yfinance.check_holders_with_min_pct_held")
async def check_holders_with_min_pct_held(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """

    _, op_args = args
    user_output_dict = x['companies']
    tickers = op_args['tickers']
    min_pct_held = float(op_args['min_pct_held'])  # Convert string to float

    # --- Format seems valid, now get expected values and compare ---
    print("\nAttempting to fetch and calculate expected common significant holders...")
    all_ticker_holder_sets = []
    calculation_step_failed = False

    for ticker in tickers:
        holder_set = yfinance__get_significant_holders_for_ticker(ticker, min_pct_held)  # Pass the threshold
        if holder_set is None:  # Helper function failed for this ticker
            return False, (f"Internal calculation error: Could not retrieve or process "
                           f"institutional holder data for {ticker}. See console warnings.")
            # Continue to check other tickers if possible, but overall comparison will be affected
        all_ticker_holder_sets.append(holder_set)

    if calculation_step_failed:
        # Cannot reliably determine common holders if data for any ticker is missing.
        # If user provided a list, we can't confirm it.
        # Primary error is calculation failure
        return False, ("Cannot verify the list of common holders because data for "
                       "one or more companies was incomplete.")

    # Calculate the intersection if all sets were successfully retrieved
    if len(all_ticker_holder_sets) == len(tickers):  # Should be true if no calculation_step_failed
        expected_common_holders_set = all_ticker_holder_sets[0].intersection(*all_ticker_holder_sets[1:])
    else:  # Should have been caught by calculation_step_failed
        return False, "Internal logic error: Did not gather holder sets for all tickers despite no explicit failure."

    # --- Compare user's set with the expected set ---
    user_holder_names_set = set(name.lower() for name in user_output_dict)
    if user_holder_names_set == expected_common_holders_set:
        print("User's list of common significant holders matches the expected list.")
    else:
        missing_from_user = expected_common_holders_set - user_holder_names_set
        extra_in_user = user_holder_names_set - expected_common_holders_set

        if missing_from_user:
            return False, (f"Comparison error: User's list is missing the following "
                           f"required common significant holders: {sorted(list(missing_from_user))}")
        if extra_in_user:
            return False, (f"Comparison error: User's list includes the following institutions "
                           f"that are not common significant holders or do not meet criteria: "
                           f"{sorted(list(extra_in_user))}")

    return True, ""


@compare_func(name="yfinance.check_holders_pct_change")
async def check_holders_pct_change(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """

    _, op_args = args
    user_output_dict = x
    ticker = op_args['ticker']
    holder = op_args['holder']

    expected_pct_change = yfinance__get_specific_holder_pct_change(ticker, holder)

    holder_output_key = f"{holder} pctChange"
    user_pct_change = float(user_output_dict[ticker][holder_output_key])

    pct_change_item_absolute_tolerance = 0.00015  # For decimal percentages like 0.0250 vs 0.0251
    if abs(user_pct_change - expected_pct_change) > pct_change_item_absolute_tolerance:
        return False, (f"Value error for '{ticker} - {holder_output_key}': "
                       f"Expected ~{expected_pct_change:.4f}, got {user_pct_change:.4f}.")

    return True, ""


@compare_func(name="yfinance.check_holders_largest_pct_change")
async def check_holders_largest_pct_change(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args
    user_output_dict = x
    tickers = op_args['tickers']
    holder = op_args['holder']

    expected_pct_change_list = []
    for ticker in tickers:
        expected_pct_change = yfinance__get_specific_holder_pct_change(ticker, holder)
        expected_pct_change_list.append([ticker, expected_pct_change])
    expected_pct_change_list = sorted(expected_pct_change_list, key=lambda item: item[1])
    expected_company = expected_pct_change_list[-1][0]

    holder_key = f"company with largest positive increase in {holder}'s reported stake"
    if holder_key not in user_output_dict:
        return False, f"key: company with largest positive increase in {holder}'s reported stake does't exist"

    llm_company = user_output_dict[holder_key]

    if not expected_company.lower() == llm_company.lower():
        return False, f"Holder {holder}: the expected company is {expected_company}, but llm responses {llm_company}"
    return True, ""


@compare_func(name="yfinance.check_common_significant_holders")
async def check_common_significant_holders(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args
    user_output_dict = x
    tickers = op_args['tickers']
    threshold_pct_held = op_args['threshold_pct_held']

    expected_significant_holders = {}
    for ticker in tickers:
        expected_significant_holders[ticker] = yfinance__get_significant_holders_by_pct_held(
            ticker_symbol=ticker,
            threshold_pct_held_decimal=threshold_pct_held
        )
    expected_common_holders = set(expected_significant_holders[tickers[0]])
    for ticker in tickers[1:]:
        expected_common_holders = expected_common_holders.intersection(expected_significant_holders[ticker])
    llm_significant_holders = user_output_dict['holders']

    # sort
    expected_common_holders = sorted(expected_common_holders)
    llm_significant_holders = sorted(llm_significant_holders)

    # to lowercase
    expected_common_holders = [x.lower() for x in expected_common_holders]
    llm_significant_holders = [x.lower() for x in llm_significant_holders]

    if not expected_common_holders == llm_significant_holders:
        return False, (f"Expected significant holders are [{expected_common_holders}], "
                       f"but llm responses [{llm_significant_holders}]")
    return True, ""


@compare_func(name="yfinance.check_pct_values_with_durations")
async def check_pct_values_with_durations(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args
    user_output_dict = x
    ticker = op_args['ticker']

    print(f"\nAttempting to fetch and calculate expected data for {ticker}...")
    expected_data = yfinance__calculate_expected_price_changes(ticker_symbol=ticker)

    if expected_data is None:
        return False, (
            f"Internal calculation error: Could not retrieve or calculate "
            f"required data for {ticker} (Vanguard report date or "
            f"subsequent price changes). See console warnings."
        )

    # Compare 'Date Reported'
    if user_output_dict['Date Reported'] != expected_data['Date Reported']:
        return False, (
            f"Value error for 'Date Reported': Expected "
            f"'{expected_data['Date Reported']}', got "
            f"'{user_output_dict['Date Reported']}'."
        )

    # Compare percentage changes
    percentage_tolerance = 0.055  # Absolute difference in percentage points
    for key in ['7-day percentage change', '30-day percentage change']:
        user_val = float(user_output_dict.get(key))  # Already checked it's a number
        expected_val = float(expected_data.get(key))

        if expected_val is None:  # Means checker could not calculate it (e.g., future date)
            return False, (
                f"Verification issue for '{key}': Expected value could not be "
                f"calculated (e.g., target date might be in the future or price "
                f"data missing). User provided {user_val:.2f}%."
            )
        if user_val is None:  # User provided None, but format requires NUMBER (already caught by format check)
            return False, "the llm response is empty"
        if abs(user_val - expected_val) > percentage_tolerance:
            return False, f"Value error for '{key}': Expected ~{expected_val:.2f}%, got {user_val:.2f}%."
    return True, ""


@compare_func(name="yfinance.check_institutional_holding_values")
async def check_institutional_holding_values(x: dict, *args, **kwargs) -> (bool, str):
    """
    Checks the format and numerical values of the user's output

    Args:
        x: The user's output.
        args: The task details.

    Returns:
        A tuple: (is_correct: bool, errors: str)
    """
    _, op_args = args
    user_output_dict = x
    ticker = op_args['ticker']
    holder = op_args['holder']

    print("\nAttempting to fetch/calculate expected data for Task...")
    expected_data = yfinance__calculate_institutional_holding_values(ticker_symbol=ticker, holder_name=holder)

    if expected_data is None:
        return False, "Internal error: Could not get expected data. See console."

    if user_output_dict['Date Reported'] != expected_data['Date Reported']:
        return False, (
            f"Value error for 'Date Reported': Expected "
            f"'{expected_data['Date Reported']}', got "
            f"'{user_output_dict['Date Reported']}'."
        )

    comparison_fields_tolerances = {
        'originally reported value': {'rel_tol': 0.0005, 'abs_tol': 1.0},
        'calculated market value': {'rel_tol': 0.001, 'abs_tol': 0.015},
        'absolute difference': {'rel_tol': 0.001, 'abs_tol': 0.015}
    }
    for key, tols in comparison_fields_tolerances.items():
        user_val = user_output_dict.get(key)
        expected_val = expected_data.get(key)
        if isinstance(user_val, (int, float)) and isinstance(expected_val, (int, float)):
            if not math.isclose(float(user_val), float(expected_val), rel_tol=tols['rel_tol'], abs_tol=tols['abs_tol']):
                return False, f"Value error for '{key}': Expected ~{expected_val:.2f}, got {float(user_val):.2f}."

    return True, ""
