"""Yahoo Finance provider — company profiles, price history, financials, options, dividends, holders."""

import math
import time

from _shared.output import error_response, log, success_response

TYPE_CHOICES = ("history", "financials", "profile", "options", "dividends", "holders")
PERIOD_CHOICES = ("1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max")
INTERVAL_CHOICES = ("1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo")
STATEMENT_CHOICES = ("income", "balance_sheet", "cash_flow")
FREQUENCY_CHOICES = ("annual", "quarterly")

MAX_TICKERS = 5
PER_TICKER_DELAY = 2.0  # seconds between tickers


def add_arguments(parser):
    parser.add_argument("--ticker", required=True, help="Comma-separated ticker symbols (max 5)")
    parser.add_argument("--type", required=True, choices=TYPE_CHOICES, help="Data type to retrieve")
    parser.add_argument("--period", default="1y", choices=PERIOD_CHOICES, help="Time period (history only)")
    parser.add_argument("--interval", default="1d", choices=INTERVAL_CHOICES, help="Data interval (history only)")
    parser.add_argument("--statement", default="income", choices=STATEMENT_CHOICES, help="Statement type (financials)")
    parser.add_argument("--frequency", default="annual", choices=FREQUENCY_CHOICES, help="Reporting frequency (financials)")
    parser.add_argument("--expiration", default=None, help="Options expiration date YYYY-MM-DD")


def search(args) -> str:
    try:
        import yfinance as yf
    except ImportError:
        return error_response(
            ["yfinance is not installed. Run: pip install yfinance"],
            error_code="missing_dependency",
        )

    tickers = [t.strip().upper() for t in args.ticker.split(",") if t.strip()]
    if not tickers:
        return error_response(["No ticker symbols provided"], error_code="missing_ticker")
    if len(tickers) > MAX_TICKERS:
        return error_response(
            [f"Max {MAX_TICKERS} tickers per call, got {len(tickers)}"],
            error_code="too_many_tickers",
        )

    data_type = args.type
    results = []

    for i, symbol in enumerate(tickers):
        if i > 0:
            time.sleep(PER_TICKER_DELAY)

        log(f"Fetching {data_type} for {symbol}")
        try:
            ticker = yf.Ticker(symbol)
            result = _dispatch(ticker, symbol, data_type, args)
            if result is not None:
                results.append(result)
        except Exception as e:
            log(f"Error fetching {symbol}: {e}", level="error")
            results.append({"ticker": symbol, "error": str(e)})

    return success_response(results, total_results=len(results), provider="yfinance")


def _dispatch(ticker, symbol: str, data_type: str, args) -> dict | None:
    if data_type == "history":
        return _get_history(ticker, symbol, args)
    if data_type == "financials":
        return _get_financials(ticker, symbol, args)
    if data_type == "profile":
        return _get_profile(ticker, symbol)
    if data_type == "options":
        return _get_options(ticker, symbol, args)
    if data_type == "dividends":
        return _get_dividends(ticker, symbol)
    if data_type == "holders":
        return _get_holders(ticker, symbol)
    return None


def _get_history(ticker, symbol: str, args) -> dict:
    df = ticker.history(period=args.period, interval=args.interval)
    if df.empty:
        return {"ticker": symbol, "period": args.period, "interval": args.interval, "data_points": 0, "data": []}

    data = []
    for date, row in df.iterrows():
        point: dict[str, str | int | float] = {"date": str(date.date()) if hasattr(date, "date") else str(date)}
        for col in ("Open", "High", "Low", "Close", "Volume"):
            if col in row and not _is_nan(row[col]):
                point[col.lower()] = round(row[col], 4) if col != "Volume" else int(row[col])
        data.append(point)

    return {
        "ticker": symbol,
        "period": args.period,
        "interval": args.interval,
        "data_points": len(data),
        "data": data,
    }


def _get_financials(ticker, symbol: str, args) -> dict:
    statement = args.statement
    quarterly = args.frequency == "quarterly"

    if statement == "income":
        df = ticker.quarterly_income_stmt if quarterly else ticker.income_stmt
    elif statement == "balance_sheet":
        df = ticker.quarterly_balance_sheet if quarterly else ticker.balance_sheet
    elif statement == "cash_flow":
        df = ticker.quarterly_cashflow if quarterly else ticker.cashflow
    else:
        return {"ticker": symbol, "error": f"Unknown statement type: {statement}"}

    if df is None or df.empty:
        return {"ticker": symbol, "statement": statement, "frequency": args.frequency, "periods": [], "data": {}}

    periods = [str(col.date()) if hasattr(col, "date") else str(col) for col in df.columns]
    data = {}
    for row_name in df.index:
        values = []
        for val in df.loc[row_name]:
            if _is_nan(val):
                values.append(None)
            elif isinstance(val, float):
                values.append(round(val, 2))
            else:
                values.append(val)
        # Only include rows that have at least one non-None value
        if any(v is not None for v in values):
            data[str(row_name)] = values

    return {
        "ticker": symbol,
        "statement": statement,
        "frequency": args.frequency,
        "periods": periods,
        "data": data,
    }


def _get_profile(ticker, symbol: str) -> dict:
    info = ticker.info or {}
    if not info or not info.get("marketCap"):
        return {"ticker": symbol, "error": f"Ticker '{symbol}' not found or delisted"}

    # Map yfinance info keys to our output schema, omitting None values
    field_map = {
        "name": "shortName",
        "sector": "sector",
        "industry": "industry",
        "market_cap": "marketCap",
        "trailing_pe": "trailingPE",
        "forward_pe": "forwardPE",
        "price_to_book": "priceToBook",
        "enterprise_value": "enterpriseValue",
        "revenue_ttm": "totalRevenue",
        "net_income_ttm": "netIncomeToCommon",
        "profit_margin": "profitMargins",
        "return_on_equity": "returnOnEquity",
        "debt_to_equity": "debtToEquity",
        "current_ratio": "currentRatio",
        "dividend_yield": "dividendYield",
        "beta": "beta",
        "fifty_two_week_high": "fiftyTwoWeekHigh",
        "fifty_two_week_low": "fiftyTwoWeekLow",
        "average_volume": "averageVolume",
        "current_price": "currentPrice",
        "target_mean_price": "targetMeanPrice",
        "recommendation_key": "recommendationKey",
        "number_of_analyst_opinions": "numberOfAnalystOpinions",
        "currency": "currency",
        "exchange": "exchange",
    }

    result = {"ticker": symbol}
    for out_key, yf_key in field_map.items():
        val = info.get(yf_key)
        if val is not None and not _is_nan(val):
            result[out_key] = val

    return result


def _get_options(ticker, symbol: str, args) -> dict:
    try:
        expirations = ticker.options
    except Exception:
        return {"ticker": symbol, "error": "No options data available"}

    if not expirations:
        return {"ticker": symbol, "expirations": [], "calls": [], "puts": []}

    exp_date = args.expiration if args.expiration else expirations[0]
    if exp_date not in expirations:
        # Find nearest expiration
        exp_date = expirations[0]
        log(f"Expiration {args.expiration} not found, using {exp_date}")

    try:
        chain = ticker.option_chain(exp_date)
    except Exception as e:
        return {"ticker": symbol, "error": f"Failed to get option chain: {e}"}

    def _df_to_list(df):
        records = []
        for _, row in df.iterrows():
            record = {}
            for col in df.columns:
                val = row[col]
                if _is_nan(val):
                    continue
                if isinstance(val, float):
                    record[col] = round(val, 4)
                elif hasattr(val, "isoformat"):
                    record[col] = val.isoformat()
                else:
                    record[col] = val
            records.append(record)
        return records

    return {
        "ticker": symbol,
        "expiration": exp_date,
        "available_expirations": list(expirations),
        "calls": _df_to_list(chain.calls),
        "puts": _df_to_list(chain.puts),
    }


def _get_dividends(ticker, symbol: str) -> dict:
    divs = ticker.dividends
    if divs is None or divs.empty:
        return {"ticker": symbol, "dividends": [], "count": 0}

    data = []
    for date, amount in divs.items():
        if not _is_nan(amount):
            data.append({
                "date": str(date.date()) if hasattr(date, "date") else str(date),
                "amount": round(float(amount), 4),
            })

    return {"ticker": symbol, "dividends": data, "count": len(data)}


def _get_holders(ticker, symbol: str) -> dict:
    try:
        inst = ticker.institutional_holders
    except Exception:
        inst = None

    if inst is None or inst.empty:
        return {"ticker": symbol, "institutional_holders": [], "count": 0}

    holders = []
    for _, row in inst.iterrows():
        holder = {}
        for col in inst.columns:
            val = row[col]
            if _is_nan(val):
                continue
            if hasattr(val, "isoformat"):
                holder[col] = val.isoformat()
            elif isinstance(val, float):
                holder[col] = round(val, 4)
            else:
                holder[col] = val
        holders.append(holder)

    return {"ticker": symbol, "institutional_holders": holders, "count": len(holders)}


def _is_nan(val) -> bool:
    """Check if a value is NaN, handling various types."""
    if val is None:
        return True
    try:
        return math.isnan(val)
    except (TypeError, ValueError):
        return False
