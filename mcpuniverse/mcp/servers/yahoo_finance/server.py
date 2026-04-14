"""
Yahoo finance MCP server.
Adapted from https://github.com/shzhiqi/yahoo-finance-mcp/blob/main/server.py.
"""
# pylint: disable=broad-exception-caught,too-many-statements,line-too-long,too-many-return-statements,invalid-name
import asyncio
import json
import time
from collections import deque
from enum import Enum
from typing import Deque

import click
import pandas as pd
# Patch peewee before yfinance import to avoid race condition where peewee 4.x
# sets sqlite3=None under concurrent subprocess spawning.
try:
    import peewee as _peewee  # noqa: F401
    if _peewee.sqlite3 is None:
        import sqlite3 as _sqlite3
        _peewee.sqlite3 = _sqlite3
except ImportError:
    pass
import yfinance as yf
from mcp.server.fastmcp import FastMCP
from mcpuniverse.common.logger import get_logger


class AsyncRateLimiter:
    """Async rate limiter using sliding window algorithm.
    
    This rate limiter ensures that no more than max_requests requests
    are sent within any time_window period, preventing rate limit errors.
    
    When multiple requests arrive simultaneously (e.g., 8 concurrent requests),
    they are automatically queued and executed in a controlled manner,
    ensuring the rate limit is NEVER exceeded.
    
    Key features:
    - Thread-safe: Uses asyncio.Lock for atomic operations
    - Prevents errors: Guarantees no more than max_requests per time_window
    - Efficient: Only waits when necessary
    - Concurrent-friendly: Allows max_requests concurrent requests
    
    Attributes:
        max_requests: Maximum number of requests allowed in the time window.
        time_window: Time window in seconds.
        _tokens: Deque storing timestamps of recent requests.
        _lock: Async lock for thread-safe operations.
    """
    
    def __init__(self, max_requests: int = 4, time_window: float = 1.0):
        """Initialize rate limiter.
        
        Args:
            max_requests: Maximum requests allowed in time window.
            time_window: Time window in seconds.
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self._tokens: Deque[float] = deque()
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> None:
        """Acquire a token, waiting if necessary.
        
        This method ensures that requests are spaced out to respect
        the rate limit. If 8 requests arrive simultaneously:
        - First 4 requests will execute immediately (if within limit)
        - Remaining 4 requests will wait until tokens become available
        - This prevents ANY requests from being sent when rate limit is exceeded
        
        Returns:
            None. This method blocks until a token is available.
        """
        while True:
            async with self._lock:
                now = time.time()
                
                # Remove expired tokens (older than time_window)
                while self._tokens and now - self._tokens[0] > self.time_window:
                    self._tokens.popleft()
                
                # If we have available tokens, use one immediately
                if len(self._tokens) < self.max_requests:
                    self._tokens.append(now)
                    return  # Successfully acquired token, can proceed
            
            # Rate limit is full - need to wait
            # Calculate wait time based on oldest token expiration
            async with self._lock:
                if not self._tokens:
                    # Edge case: no tokens but still blocked? Retry immediately
                    continue
                
                now = time.time()
                oldest_token_time = self._tokens[0]
                # Wait until oldest token expires + small buffer for safety
                wait_time = self.time_window - (now - oldest_token_time) + 0.01
                
                if wait_time <= 0:
                    # Token already expired, retry immediately
                    continue
            
            # Wait outside the lock to allow other coroutines to check
            # This ensures fair queuing when multiple requests are waiting
            await asyncio.sleep(wait_time)


# Global rate limiter instance
# Configure: max 2 requests per 1 second (very conservative setting to avoid Yahoo Finance rate limits)
# Yahoo Finance is very strict - with high concurrency (rollout=8), even 3 requests/sec can cause issues
# This ensures that even with 8+ concurrent requests, we never exceed Yahoo Finance's limits
_rate_limiter = AsyncRateLimiter(max_requests=8, time_window=1.0)


# Define an enum for the type of financial statement
class FinancialType(str, Enum):
    """Financial type."""
    income_stmt = "income_stmt"
    quarterly_income_stmt = "quarterly_income_stmt"
    balance_sheet = "balance_sheet"
    quarterly_balance_sheet = "quarterly_balance_sheet"
    cashflow = "cashflow"
    quarterly_cashflow = "quarterly_cashflow"


class HolderType(str, Enum):
    """Holder type."""
    major_holders = "major_holders"
    institutional_holders = "institutional_holders"
    mutualfund_holders = "mutualfund_holders"
    insider_transactions = "insider_transactions"
    insider_purchases = "insider_purchases"
    insider_roster_holders = "insider_roster_holders"


class RecommendationType(str, Enum):
    """Recommendation type."""
    recommendations = "recommendations"
    upgrades_downgrades = "upgrades_downgrades"


def build_server(port: int) -> FastMCP:
    """
    Initializes the MCP server.

    :param port: Port for SSE.
    :return: The MCP server.
    """

    yfinance_server = FastMCP(
        "yfinance",
        port=port,
        instructions="""
    # Yahoo Finance MCP Server
    
    This server is used to get information about a given ticker symbol from yahoo finance.
    
    Available tools:
    - get_historical_stock_prices: Get historical stock prices for a given ticker symbol from yahoo finance. Include the following information: Date, Open, High, Low, Close, Volume, Adj Close.
    - get_stock_price_on_date: Get the stock price for a given ticker symbol on a specific date. Returns the Open, High, Low, Close, Volume prices for that date. If the date is a weekend/holiday, returns the closest trading day.
    - get_stock_info: Get stock information for a given ticker symbol from yahoo finance. Include the following information: Stock Price & Trading Info, Company Information, Financial Metrics, Earnings & Revenue, Margins & Returns, Dividends, Balance Sheet, Ownership, Analyst Coverage, Risk Metrics, Other.
    - get_yahoo_finance_news: Get news for a given ticker symbol from yahoo finance.
    - get_stock_actions: Get stock dividends and stock splits for a given ticker symbol from yahoo finance.
    - get_financial_statement: Get financial statement for a given ticker symbol from yahoo finance. You can choose from the following financial statement types: income_stmt, quarterly_income_stmt, balance_sheet, quarterly_balance_sheet, cashflow, quarterly_cashflow.
    - get_holder_info: Get holder information for a given ticker symbol from yahoo finance. You can choose from the following holder types: major_holders, institutional_holders, mutualfund_holders, insider_transactions, insider_purchases, insider_roster_holders.
    - get_option_expiration_dates: Fetch the available options expiration dates for a given ticker symbol.
    - get_option_chain: Fetch the option chain for a given ticker symbol, expiration date, and option type.
    - get_recommendations: Get recommendations or upgrades/downgrades for a given ticker symbol from yahoo finance. You can also specify the number of months back to get upgrades/downgrades for, default is 12.
    """,
    )

    @yfinance_server.tool(
        name="get_historical_stock_prices",
        description="""Get historical stock prices for a given ticker symbol from yahoo finance. Include the following information: Date, Open, High, Low, Close, Volume, Adj Close.
    Args:
        ticker: str
            The ticker symbol of the stock to get historical prices for, e.g. "AAPL"
        start_date: str
            format: yyyy-mm-dd
        end_date: str
            format: yyyy-mm-dd
        interval: str
            Valid intervals: 1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo
            Intraday data cannot extend last 60 days
            Default is "1d"
    """,
    )
    async def get_historical_stock_prices(
            ticker: str, start_date: str, end_date: str, interval: str = "1d"
    ) -> str:
        """Get historical stock prices for a given ticker symbol

        Args:
            ticker: str
                The ticker symbol of the stock to get historical prices for, e.g. "AAPL"
            start_date: str
                format: yyyy-mm-dd
            end_date: str
                format: yyyy-mm-dd
            interval: str
                Valid intervals: 1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo
                Intraday data cannot extend last 60 days
                Default is "1d"
        """
        await _rate_limiter.acquire()
        try:
            company = yf.Ticker(ticker)
            # Check if ticker is valid
            try:
                if company.isin is None:
                    return f"Company ticker {ticker} not found."
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error checking ticker {ticker}"
                logger = get_logger("yahoo_finance")
                logger.error(f"Error checking ticker {ticker}: {error_msg}")
                return f"Error: getting historical stock prices for {ticker}: {error_msg}"

            # Get the historical data
            try:
                hist_data = company.history(start=start_date, end=end_date, interval=interval)
                if hist_data.empty:
                    return f"No historical data found for {ticker} between {start_date} and {end_date}"
                hist_data = hist_data.reset_index(names="Date")
                hist_data = hist_data.to_json(orient="records", date_format="iso")
                return hist_data
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error fetching history for {ticker}"
                logger = get_logger("yahoo_finance")
                logger.error(f"Error fetching history for {ticker}: {error_msg}")
                return f"Error: getting historical stock prices for {ticker}: {error_msg}"
        except Exception as e:
            error_msg = str(e) if str(e) else f"Unknown error for {ticker}"
            logger = get_logger("yahoo_finance")
            logger.error(f"Unexpected error for {ticker}: {error_msg}")
            return f"Error: getting historical stock prices for {ticker}: {error_msg}"

    @yfinance_server.tool(
        name="get_stock_info",
        description="""Get stock information for a given ticker symbol from yahoo finance. Include the following information:
    Stock Price & Trading Info, Company Information, Financial Metrics, Earnings & Revenue, Margins & Returns, Dividends, Balance Sheet, Ownership, Analyst Coverage, Risk Metrics, Other.
    
    Args:
        ticker: str
            The ticker symbol of the stock to get information for, e.g. "AAPL"
        fields: str
            Optional. Comma-separated list of specific fields to return, e.g. "currentPrice,marketCap,trailingPE".
            If not provided, returns all available fields.
            Common fields: currentPrice, previousClose, open, dayHigh, dayLow, volume, marketCap,
            trailingPE, forwardPE, trailingEps, forwardEps, dividendYield, beta, 52WeekHigh, 52WeekLow,
            sector, industry, fullTimeEmployees, country, website, longBusinessSummary
    """,
    )
    async def get_stock_info(ticker: str, fields: str = "") -> str:
        """Get stock information for a given ticker symbol"""
        await _rate_limiter.acquire()
        logger = get_logger("yahoo_finance")
        try:
            company = yf.Ticker(ticker)
            try:
                if company.isin is None:
                    return f"Company ticker {ticker} not found."
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error checking ticker {ticker}"
                logger.error(f"Error checking ticker {ticker}: {error_msg}")
                return f"Error: getting stock information for {ticker}: {error_msg}"
            
            try:
                info = company.info
                if not info:
                    return f"No information found for ticker {ticker}"
                
                # Filter fields if specified
                if fields:
                    field_list = [f.strip() for f in fields.split(",")]
                    filtered_info = {k: info.get(k) for k in field_list if k in info}
                    if not filtered_info:
                        available_fields = ", ".join(list(info.keys())[:20]) + "..."
                        return f"None of the requested fields found. Available fields include: {available_fields}"
                    return json.dumps(filtered_info)
                
                return json.dumps(info)
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error fetching info for {ticker}"
                logger.error(f"Error fetching info for {ticker}: {error_msg}")
                return f"Error: getting stock information for {ticker}: {error_msg}"
        except Exception as e:
            error_msg = str(e) if str(e) else f"Unknown error for {ticker}"
            logger.error(f"Unexpected error for {ticker}: {error_msg}")
            return f"Error: getting stock information for {ticker}: {error_msg}"

    @yfinance_server.tool(
        name="get_yahoo_finance_news",
        description="""Get news for a given ticker symbol from yahoo finance.
    
    Args:
        ticker: str
            The ticker symbol of the stock to get news for, e.g. "AAPL"
        max_news: int
            Optional. Maximum number of news articles to return. Default is 10.
            Use a smaller number (e.g. 3-5) if you only need recent headlines.
    """,
    )
    async def get_yahoo_finance_news(ticker: str, max_news: int = 10) -> str:
        """Get news for a given ticker symbol

        Args:
            ticker: str
                The ticker symbol of the stock to get news for, e.g. "AAPL"
            max_news: int
                Maximum number of news articles to return. Default is 10.
        """
        await _rate_limiter.acquire()
        logger = get_logger("yahoo_finance")
        try:
            company = yf.Ticker(ticker)
            try:
                if company.isin is None:
                    return f"Company ticker {ticker} not found."
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error checking ticker {ticker}"
                logger.error(f"Error checking ticker {ticker}: {error_msg}")
                return f"Error: getting news for {ticker}: {error_msg}"

            # Get the news
            try:
                news = company.news
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error fetching news for {ticker}"
                logger.error(f"Error fetching news for {ticker}: {error_msg}")
                return f"Error: getting news for {ticker}: {error_msg}"

            news_list = []
            for news_item in news:
                if len(news_list) >= max_news:
                    break
                if news_item.get("content", {}).get("contentType", "") == "STORY":
                    title = news_item.get("content", {}).get("title", "")
                    summary = news_item.get("content", {}).get("summary", "")
                    description = news_item.get("content", {}).get("description", "")
                    url = news_item.get("content", {}).get("canonicalUrl", {}).get("url", "")
                    news_list.append(
                        f"Title: {title}\nSummary: {summary}\nDescription: {description}\nURL: {url}"
                    )
            if not news_list:
                return f"No news found for company that searched with {ticker} ticker."
            return "\n\n".join(news_list)
        except Exception as e:
            error_msg = str(e) if str(e) else f"Unknown error for {ticker}"
            logger.error(f"Unexpected error for {ticker}: {error_msg}")
            return f"Error: getting news for {ticker}: {error_msg}"

    @yfinance_server.tool(
        name="get_stock_actions",
        description="""Get stock dividends and stock splits for a given ticker symbol from yahoo finance.
    
    Args:
        ticker: str
            The ticker symbol of the stock to get stock actions for, e.g. "AAPL"
    """,
    )
    async def get_stock_actions(ticker: str) -> str:
        """Get stock dividends and stock splits for a given ticker symbol"""
        await _rate_limiter.acquire()
        logger = get_logger("yahoo_finance")
        try:
            company = yf.Ticker(ticker)
            try:
                if company.isin is None:
                    return f"Company ticker {ticker} not found."
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error checking ticker {ticker}"
                logger.error(f"Error checking ticker {ticker}: {error_msg}")
                return f"Error: getting stock actions for {ticker}: {error_msg}"

            try:
                actions_df = company.actions
                if actions_df.empty:
                    return f"No stock actions found for {ticker}"
                actions_df = actions_df.reset_index(names="Date")
                return actions_df.to_json(orient="records", date_format="iso")
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error fetching actions for {ticker}"
                logger.error(f"Error fetching actions for {ticker}: {error_msg}")
                return f"Error: getting stock actions for {ticker}: {error_msg}"
        except Exception as e:
            error_msg = str(e) if str(e) else f"Unknown error for {ticker}"
            logger.error(f"Unexpected error for {ticker}: {error_msg}")
            return f"Error: getting stock actions for {ticker}: {error_msg}"

    @yfinance_server.tool(
        name="get_financial_statement",
        description="""Get financial statement for a given ticker symbol from yahoo finance. You can choose from the following financial statement types: income_stmt, quarterly_income_stmt, balance_sheet, quarterly_balance_sheet, cashflow, quarterly_cashflow.
    
    Args:
        ticker: str
            The ticker symbol of the stock to get financial statement for, e.g. "AAPL"
        financial_type: str
            The type of financial statement to get. You can choose from the following financial statement types: income_stmt, quarterly_income_stmt, balance_sheet, quarterly_balance_sheet, cashflow, quarterly_cashflow.
        num_periods: int
            Optional. Number of periods (years for annual, quarters for quarterly) to return.
            Default is 0 which returns all available periods. Use 1 for most recent only.
    """,
    )
    async def get_financial_statement(ticker: str, financial_type: str, num_periods: int = 0) -> str:
        """Get financial statement for a given ticker symbol"""
        await _rate_limiter.acquire()
        logger = get_logger("yahoo_finance")
        try:
            company = yf.Ticker(ticker)
            try:
                if company.isin is None:
                    return f"Company ticker {ticker} not found."
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error checking ticker {ticker}"
                logger.error(f"Error checking ticker {ticker}: {error_msg}")
                return f"Error: getting financial statement for {ticker}: {error_msg}"

            # Get the financial statement
            try:
                if financial_type == FinancialType.income_stmt:
                    financial_statement = company.income_stmt
                elif financial_type == FinancialType.quarterly_income_stmt:
                    financial_statement = company.quarterly_income_stmt
                elif financial_type == FinancialType.balance_sheet:
                    financial_statement = company.balance_sheet
                elif financial_type == FinancialType.quarterly_balance_sheet:
                    financial_statement = company.quarterly_balance_sheet
                elif financial_type == FinancialType.cashflow:
                    financial_statement = company.cashflow
                elif financial_type == FinancialType.quarterly_cashflow:
                    financial_statement = company.quarterly_cashflow
                else:
                    return f"Error: invalid financial type {financial_type}. Please use one of the following: {FinancialType.income_stmt}, {FinancialType.quarterly_income_stmt}, {FinancialType.balance_sheet}, {FinancialType.quarterly_balance_sheet}, {FinancialType.cashflow}, {FinancialType.quarterly_cashflow}."
                
                if financial_statement is None or financial_statement.empty:
                    return f"No {financial_type} data found for {ticker}"
                
                # Limit number of periods if specified
                if num_periods > 0 and len(financial_statement.columns) > num_periods:
                    financial_statement = financial_statement.iloc[:, :num_periods]
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error fetching {financial_type} for {ticker}"
                logger.error(f"Error fetching {financial_type} for {ticker}: {error_msg}")
                return f"Error: getting financial statement for {ticker}: {error_msg}"

            # Create a list to store all the json objects
            result = []

            # Loop through each column (date)
            for column in financial_statement.columns:
                if isinstance(column, pd.Timestamp):
                    date_str = column.strftime("%Y-%m-%d")  # Format as YYYY-MM-DD
                else:
                    date_str = str(column)

                # Create a dictionary for each date
                date_obj = {"date": date_str}

                # Add each metric as a key-value pair
                for index, value in financial_statement[column].items():
                    # Add the value, handling NaN values
                    date_obj[index] = None if pd.isna(value) else value

                result.append(date_obj)

            return json.dumps(result)
        except Exception as e:
            error_msg = str(e) if str(e) else f"Unknown error for {ticker}"
            logger.error(f"Unexpected error for {ticker}: {error_msg}")
            return f"Error: getting financial statement for {ticker}: {error_msg}"

    @yfinance_server.tool(
        name="get_holder_info",
        description="""Get holder information for a given ticker symbol from yahoo finance. You can choose from the following holder types: major_holders, institutional_holders, mutualfund_holders, insider_transactions, insider_purchases, insider_roster_holders.
    
    Args:
        ticker: str
            The ticker symbol of the stock to get holder information for, e.g. "AAPL"
        holder_type: str
            The type of holder information to get. You can choose from the following holder types: major_holders, institutional_holders, mutualfund_holders, insider_transactions, insider_purchases, insider_roster_holders.
        top_n: int
            Optional. Maximum number of holders/transactions to return. Default is 0 (return all).
            Use a smaller number (e.g. 5-10) to reduce response size.
    """,
    )
    async def get_holder_info(ticker: str, holder_type: str, top_n: int = 0) -> str:
        """Get holder information for a given ticker symbol"""
        await _rate_limiter.acquire()
        logger = get_logger("yahoo_finance")
        try:
            company = yf.Ticker(ticker)
            try:
                if company.isin is None:
                    return f"Company ticker {ticker} not found."
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error checking ticker {ticker}"
                logger.error(f"Error checking ticker {ticker}: {error_msg}")
                return f"Error: getting holder info for {ticker}: {error_msg}"

            try:
                if holder_type == HolderType.major_holders:
                    data = company.major_holders
                    if data is None or data.empty:
                        return f"No major holders data found for {ticker}"
                    data = data.reset_index(names="metric")
                    if top_n > 0:
                        data = data.head(top_n)
                    return data.to_json(orient="records")
                if holder_type == HolderType.institutional_holders:
                    data = company.institutional_holders
                    if data is None or data.empty:
                        return f"No institutional holders data found for {ticker}"
                    if top_n > 0:
                        data = data.head(top_n)
                    return data.to_json(orient="records")
                if holder_type == HolderType.mutualfund_holders:
                    data = company.mutualfund_holders
                    if data is None or data.empty:
                        return f"No mutual fund holders data found for {ticker}"
                    if top_n > 0:
                        data = data.head(top_n)
                    return data.to_json(orient="records", date_format="iso")
                if holder_type == HolderType.insider_transactions:
                    data = company.insider_transactions
                    if data is None or data.empty:
                        return f"No insider transactions data found for {ticker}"
                    if top_n > 0:
                        data = data.head(top_n)
                    return data.to_json(orient="records", date_format="iso")
                if holder_type == HolderType.insider_purchases:
                    data = company.insider_purchases
                    if data is None or data.empty:
                        return f"No insider purchases data found for {ticker}"
                    if top_n > 0:
                        data = data.head(top_n)
                    return data.to_json(orient="records", date_format="iso")
                if holder_type == HolderType.insider_roster_holders:
                    data = company.insider_roster_holders
                    if data is None or data.empty:
                        return f"No insider roster holders data found for {ticker}"
                    if top_n > 0:
                        data = data.head(top_n)
                    return data.to_json(orient="records", date_format="iso")
                return f"Error: invalid holder type {holder_type}. Please use one of the following: {HolderType.major_holders}, {HolderType.institutional_holders}, {HolderType.mutualfund_holders}, {HolderType.insider_transactions}, {HolderType.insider_purchases}, {HolderType.insider_roster_holders}."
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error fetching {holder_type} for {ticker}"
                logger.error(f"Error fetching {holder_type} for {ticker}: {error_msg}")
                return f"Error: getting holder info for {ticker}: {error_msg}"
        except Exception as e:
            error_msg = str(e) if str(e) else f"Unknown error for {ticker}"
            logger.error(f"Unexpected error for {ticker}: {error_msg}")
            return f"Error: getting holder info for {ticker}: {error_msg}"

    @yfinance_server.tool(
        name="get_option_expiration_dates",
        description="""Fetch the available options expiration dates for a given ticker symbol.
    
    Args:
        ticker: str
            The ticker symbol of the stock to get option expiration dates for, e.g. "AAPL"
    """,
    )
    async def get_option_expiration_dates(ticker: str) -> str:
        """Fetch the available options expiration dates for a given ticker symbol."""
        await _rate_limiter.acquire()
        logger = get_logger("yahoo_finance")
        try:
            company = yf.Ticker(ticker)
            try:
                if company.isin is None:
                    return f"Company ticker {ticker} not found."
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error checking ticker {ticker}"
                logger.error(f"Error checking ticker {ticker}: {error_msg}")
                return f"Error: getting option expiration dates for {ticker}: {error_msg}"
            
            try:
                options = company.options
                if not options:
                    return f"No options expiration dates found for {ticker}"
                return json.dumps(options)
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error fetching options for {ticker}"
                logger.error(f"Error fetching options for {ticker}: {error_msg}")
                return f"Error: getting option expiration dates for {ticker}: {error_msg}"
        except Exception as e:
            error_msg = str(e) if str(e) else f"Unknown error for {ticker}"
            logger.error(f"Unexpected error for {ticker}: {error_msg}")
            return f"Error: getting option expiration dates for {ticker}: {error_msg}"

    @yfinance_server.tool(
        name="get_option_chain",
        description="""Fetch the option chain for a given ticker symbol, expiration date, and option type.
    
    Args:
        ticker: str
            The ticker symbol of the stock to get option chain for, e.g. "AAPL"
        expiration_date: str
            The expiration date for the options chain (format: 'YYYY-MM-DD')
        option_type: str
            The type of option to fetch ('calls' or 'puts')
        strike_min: float
            Optional. Minimum strike price to filter options. Default is 0 (no minimum).
        strike_max: float
            Optional. Maximum strike price to filter options. Default is 0 (no maximum).
        top_n: int
            Optional. Maximum number of options to return (sorted by volume). Default is 0 (return all).
    """,
    )
    async def get_option_chain(
        ticker: str, expiration_date: str, option_type: str,
        strike_min: float = 0, strike_max: float = 0, top_n: int = 0
    ) -> str:
        """Fetch the option chain for a given ticker symbol, expiration date, and option type.

        Args:
            ticker: The ticker symbol of the stock
            expiration_date: The expiration date for the options chain (format: 'YYYY-MM-DD')
            option_type: The type of option to fetch ('calls' or 'puts')
            strike_min: Minimum strike price to filter (0 = no minimum)
            strike_max: Maximum strike price to filter (0 = no maximum)
            top_n: Maximum number of options to return (0 = return all)

        Returns:
            str: JSON string containing the option chain data
        """
        await _rate_limiter.acquire()
        logger = get_logger("yahoo_finance")
        try:
            company = yf.Ticker(ticker)
            try:
                if company.isin is None:
                    return f"Company ticker {ticker} not found."
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error checking ticker {ticker}"
                logger.error(f"Error checking ticker {ticker}: {error_msg}")
                return f"Error: getting option chain for {ticker}: {error_msg}"

            # Check if the option type is valid
            if option_type not in ["calls", "puts"]:
                return "Error: Invalid option type. Please use 'calls' or 'puts'."

            try:
                # Check if the expiration date is valid
                options = company.options
                if expiration_date not in options:
                    return f"Error: No options available for the date {expiration_date}. You can use `get_option_expiration_dates` to get the available expiration dates."

                # Get the option chain
                option_chain = company.option_chain(expiration_date)
                if option_type == "calls":
                    data = option_chain.calls
                    if data is None or data.empty:
                        return f"No calls data found for {ticker} on {expiration_date}"
                elif option_type == "puts":
                    data = option_chain.puts
                    if data is None or data.empty:
                        return f"No puts data found for {ticker} on {expiration_date}"
                else:
                    return f"Error: invalid option type {option_type}. Please use one of the following: calls, puts."
                
                # Apply strike price filters
                if strike_min > 0:
                    data = data[data["strike"] >= strike_min]
                if strike_max > 0:
                    data = data[data["strike"] <= strike_max]
                
                # Apply top_n limit (sort by volume descending)
                if top_n > 0:
                    data = data.sort_values("volume", ascending=False).head(top_n)
                
                if data.empty:
                    return f"No {option_type} data found for {ticker} on {expiration_date} with the specified filters."
                
                return data.to_json(orient="records", date_format="iso")
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error fetching option chain for {ticker}"
                logger.error(f"Error fetching option chain for {ticker}: {error_msg}")
                return f"Error: getting option chain for {ticker}: {error_msg}"
        except Exception as e:
            error_msg = str(e) if str(e) else f"Unknown error for {ticker}"
            logger.error(f"Unexpected error for {ticker}: {error_msg}")
            return f"Error: getting option chain for {ticker}: {error_msg}"

    @yfinance_server.tool(
        name="get_recommendations",
        description="""Get recommendations or upgrades/downgrades for a given ticker symbol from yahoo finance. You can also specify the number of months back to get upgrades/downgrades for, default is 12.
    
    Args:
        ticker: str
            The ticker symbol of the stock to get recommendations for, e.g. "AAPL"
        recommendation_type: str
            The type of recommendation to get. You can choose from the following recommendation types: recommendations, upgrades_downgrades.
        months_back: int
            The number of months back to get upgrades/downgrades for, default is 12.
    """,
    )
    async def get_recommendations(ticker: str, recommendation_type: str, months_back: int = 12) -> str:
        """Get recommendations or upgrades/downgrades for a given ticker symbol"""
        await _rate_limiter.acquire()
        logger = get_logger("yahoo_finance")
        try:
            company = yf.Ticker(ticker)
            try:
                if company.isin is None:
                    return f"Company ticker {ticker} not found."
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error checking ticker {ticker}"
                logger.error(f"Error checking ticker {ticker}: {error_msg}")
                return f"Error: getting recommendations for {ticker}: {error_msg}"
            
            try:
                if recommendation_type == RecommendationType.recommendations:
                    recommendations = company.recommendations
                    if recommendations is None or recommendations.empty:
                        return f"No recommendations data found for {ticker}"
                    return recommendations.to_json(orient="records")
                if recommendation_type == RecommendationType.upgrades_downgrades:
                    # Get the upgrades/downgrades based on the cutoff date
                    upgrades_downgrades = company.upgrades_downgrades.reset_index()
                    if upgrades_downgrades is None or upgrades_downgrades.empty:
                        return f"No upgrades/downgrades data found for {ticker}"
                    cutoff_date = pd.Timestamp.now() - pd.DateOffset(months=months_back)
                    upgrades_downgrades = upgrades_downgrades[
                        upgrades_downgrades["GradeDate"] >= cutoff_date
                    ]
                    if upgrades_downgrades.empty:
                        return f"No upgrades/downgrades found for {ticker} in the last {months_back} months"
                    upgrades_downgrades = upgrades_downgrades.sort_values("GradeDate", ascending=False)
                    # Get the first occurrence (most recent) for each firm
                    latest_by_firm = upgrades_downgrades.drop_duplicates(subset=["Firm"])
                    return latest_by_firm.to_json(orient="records", date_format="iso")
                return f"Error: invalid recommendation type {recommendation_type}. Please use one of: {RecommendationType.recommendations}, {RecommendationType.upgrades_downgrades}."
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error fetching {recommendation_type} for {ticker}"
                logger.error(f"Error fetching {recommendation_type} for {ticker}: {error_msg}")
                return f"Error: getting recommendations for {ticker}: {error_msg}"
        except Exception as e:
            error_msg = str(e) if str(e) else f"Unknown error for {ticker}"
            logger.error(f"Unexpected error for {ticker}: {error_msg}")
            return f"Error: getting recommendations for {ticker}: {error_msg}"

    @yfinance_server.tool(
        name="get_stock_price_on_date",
        description="""Get the stock price for a given ticker symbol on a specific date from yahoo finance. Returns the Open, High, Low, Close, Volume, and Adj Close prices for that date.
    
    Args:
        ticker: str
            The ticker symbol of the stock to get price for, e.g. "AAPL"
        date: str
            The specific date to get stock price for, format: yyyy-mm-dd (e.g. "2024-01-15")
    """,
    )
    async def get_stock_price_on_date(ticker: str, date: str) -> str:
        """Get the stock price for a given ticker symbol on a specific date.

        Args:
            ticker: str
                The ticker symbol of the stock to get price for, e.g. "AAPL"
            date: str
                The specific date to get stock price for, format: yyyy-mm-dd (e.g. "2024-01-15")
        
        Returns:
            str: JSON string containing the stock price data for the specified date,
                 including Open, High, Low, Close, Volume, and other available fields.
        """
        await _rate_limiter.acquire()
        logger = get_logger("yahoo_finance")
        try:
            company = yf.Ticker(ticker)
            # Check if ticker is valid
            try:
                if company.isin is None:
                    return f"Company ticker {ticker} not found."
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error checking ticker {ticker}"
                logger.error(f"Error checking ticker {ticker}: {error_msg}")
                return f"Error: getting stock price for {ticker} on {date}: {error_msg}"

            # Parse the date and create a range to fetch data
            try:
                target_date = pd.Timestamp(date)
                # Fetch data for a small range around the target date to handle weekends/holidays
                start_date = (target_date - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
                end_date = (target_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                
                hist_data = company.history(start=start_date, end=end_date, interval="1d")
                if hist_data.empty:
                    return f"No stock price data found for {ticker} around {date}"
                
                hist_data = hist_data.reset_index(names="Date")
                # Convert Date column to string for comparison
                hist_data["DateStr"] = hist_data["Date"].dt.strftime("%Y-%m-%d")
                
                # Try to find exact date match
                exact_match = hist_data[hist_data["DateStr"] == date]
                if not exact_match.empty:
                    result = exact_match.drop(columns=["DateStr"]).to_json(orient="records", date_format="iso")
                    return result
                
                # If no exact match (weekend/holiday), find the closest trading day before or on the target date
                # Remove timezone info to allow comparison with timezone-naive target_date
                hist_data["Date"] = pd.to_datetime(hist_data["Date"]).dt.tz_localize(None)
                before_or_on = hist_data[hist_data["Date"] <= target_date]
                if not before_or_on.empty:
                    closest = before_or_on.iloc[-1:]
                    actual_date = closest["DateStr"].values[0]
                    result = closest.drop(columns=["DateStr"]).to_json(orient="records", date_format="iso")
                    return f"Note: {date} is not a trading day. Returning data for the closest trading day ({actual_date}).\n{result}"
                
                return f"No trading data found for {ticker} on or before {date}"
            except Exception as e:
                error_msg = str(e) if str(e) else f"Unknown error fetching price for {ticker} on {date}"
                logger.error(f"Error fetching price for {ticker} on {date}: {error_msg}")
                return f"Error: getting stock price for {ticker} on {date}: {error_msg}"
        except Exception as e:
            error_msg = str(e) if str(e) else f"Unknown error for {ticker}"
            logger.error(f"Unexpected error for {ticker}: {error_msg}")
            return f"Error: getting stock price for {ticker} on {date}: {error_msg}"

    return yfinance_server


@click.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport type",
)
@click.option("--port", default="8000", help="Port to listen on for SSE")
def main(transport: str, port: str):
    """
    Starts the initialized MCP server.

    :param port: Port for SSE.
    :param transport: The transport type, e.g., `stdio` or `sse`.
    """
    assert transport.lower() in ["stdio", "sse"], \
        "Transport should be `stdio` or `sse`"
    logger = get_logger("Service:yahoo_finance")
    logger.info("Starting the MCP server")
    mcp = build_server(int(port))
    mcp.run(transport=transport.lower())
