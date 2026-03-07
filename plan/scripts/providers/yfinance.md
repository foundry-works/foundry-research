# Provider: yfinance

## Modes

### Historical Prices
```bash
python search.py --provider yfinance \
  --ticker AAPL --type history \
  --period 1y --interval 1d
```

### Financial Statements
```bash
python search.py --provider yfinance \
  --ticker MSFT --type financials \
  --statement income --frequency annual

python search.py --provider yfinance \
  --ticker MSFT --type financials \
  --statement balance_sheet --frequency quarterly

python search.py --provider yfinance \
  --ticker MSFT --type financials \
  --statement cash_flow --frequency annual
```

### Company Profile & Key Ratios
```bash
python search.py --provider yfinance \
  --ticker NVDA --type profile
```

### Options Chain
```bash
python search.py --provider yfinance \
  --ticker TSLA --type options \
  --expiration 2026-06-19
```

### Multi-Ticker Screening
```bash
python search.py --provider yfinance \
  --ticker TSLA,F,GM --type profile
```

### Dividend History
```bash
python search.py --provider yfinance \
  --ticker JNJ --type dividends
```

### Institutional Holders
```bash
python search.py --provider yfinance \
  --ticker AAPL --type holders
```

## CLI Flags

| Flag | Required | Values | Default | Purpose |
|------|----------|--------|---------|---------|
| `--ticker` | Yes | Comma-separated symbols | — | One or more ticker symbols |
| `--type` | Yes | `history`, `financials`, `profile`, `options`, `dividends`, `holders` | — | Data type to retrieve |
| `--period` | No | `1d`, `5d`, `1mo`, `3mo`, `6mo`, `1y`, `2y`, `5y`, `10y`, `ytd`, `max` | `1y` | Time period (history only) |
| `--interval` | No | `1m`, `2m`, `5m`, `15m`, `30m`, `60m`, `90m`, `1h`, `1d`, `5d`, `1wk`, `1mo`, `3mo` | `1d` | Data interval (history only) |
| `--statement` | No | `income`, `balance_sheet`, `cash_flow` | `income` | Statement type (financials only) |
| `--frequency` | No | `annual`, `quarterly` | `annual` | Reporting frequency (financials only) |
| `--expiration` | No | `YYYY-MM-DD` | nearest | Options expiration date |

## Library API Mapping

`yfinance` has no REST API — it's a Python library wrapping Yahoo Finance's undocumented backend. All calls go through `yfinance.Ticker(symbol)`.

| Mode | Library Call | Returns |
|------|-------------|---------|
| `history` | `ticker.history(period=..., interval=...)` | DataFrame: Date, Open, High, Low, Close, Volume |
| `financials` (income) | `ticker.income_stmt` / `ticker.quarterly_income_stmt` | DataFrame: Revenue, Net Income, EBITDA, etc. |
| `financials` (balance) | `ticker.balance_sheet` / `ticker.quarterly_balance_sheet` | DataFrame: Total Assets, Total Debt, etc. |
| `financials` (cash) | `ticker.cashflow` / `ticker.quarterly_cashflow` | DataFrame: Operating CF, CapEx, Free CF, etc. |
| `profile` | `ticker.info` | Dict: marketCap, trailingPE, forwardPE, sector, industry, etc. |
| `options` | `ticker.option_chain(date=...)` | NamedTuple: `.calls` DataFrame, `.puts` DataFrame |
| `dividends` | `ticker.dividends` | Series: Date → dividend amount |
| `holders` | `ticker.institutional_holders` | DataFrame: Holder, Shares, Date Reported, % Out, Value |

## Output Fields

### Profile Result
```json
{
  "ticker": "NVDA",
  "name": "NVIDIA Corporation",
  "sector": "Technology",
  "industry": "Semiconductors",
  "market_cap": 3200000000000,
  "trailing_pe": 65.2,
  "forward_pe": 32.1,
  "price_to_book": 48.3,
  "enterprise_value": 3180000000000,
  "revenue_ttm": 130000000000,
  "net_income_ttm": 72000000000,
  "profit_margin": 0.554,
  "return_on_equity": 1.15,
  "debt_to_equity": 17.2,
  "current_ratio": 4.1,
  "dividend_yield": 0.0002,
  "beta": 1.65,
  "fifty_two_week_high": 153.13,
  "fifty_two_week_low": 75.61,
  "average_volume": 250000000,
  "current_price": 138.50,
  "target_mean_price": 160.0,
  "recommendation_key": "buy",
  "number_of_analyst_opinions": 45,
  "currency": "USD",
  "exchange": "NMS"
}
```

### History Result
```json
{
  "ticker": "AAPL",
  "period": "1y",
  "interval": "1d",
  "data_points": 252,
  "data": [
    {"date": "2025-03-07", "open": 175.20, "high": 177.50, "low": 174.80, "close": 176.90, "volume": 45000000},
    "..."
  ]
}
```

### Financials Result
```json
{
  "ticker": "MSFT",
  "statement": "income",
  "frequency": "annual",
  "periods": ["2025-06-30", "2024-06-30", "2023-06-30", "2022-06-30"],
  "data": {
    "Total Revenue": [245000000000, 227000000000, 212000000000, 198000000000],
    "Net Income": [88000000000, 82000000000, 72000000000, 67000000000],
    "..."
  }
}
```

## Rate Limiting & Reliability

Yahoo Finance has **no documented API** — `yfinance` scrapes internal endpoints that are subject to aggressive, undocumented rate limiting.

### Strategy

1. **Per-ticker delay:** Enforce `time.sleep(2)` between each ticker in multi-ticker requests. Do not parallelize ticker fetches.
2. **Exponential backoff on 429:** Base 5 seconds, max 60 seconds, 3 retries. Yahoo returns 429 without `Retry-After` headers.
3. **Session reuse:** Create a single `requests.Session` per provider invocation. Yahoo tracks session-level request patterns.
4. **Max batch size:** Cap multi-ticker requests at 5 tickers per invocation. Claude should split larger screens into multiple calls.
5. **Graceful degradation on `None`:** Many `ticker.info` fields return `None` when Yahoo throttles silently. Check for `None` on critical fields (marketCap, trailingPE) and report as partial result rather than crashing.

### Integration with `rate_limiter.py`

Register domain `query2.finance.yahoo.com` with:
- Capacity: 1 token
- Refill rate: 0.4 tokens/sec (1 request per 2.5 seconds)
- Burst: 1

This is more conservative than academic APIs. The shared rate limiter handles cross-process safety, but the 2-second per-ticker sleep is enforced locally within the provider to handle multi-ticker batch pacing.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Invalid ticker | `ticker.info` returns empty dict or minimal stub. Check for missing `marketCap` field → return `{"status": "error", "errors": ["Ticker 'XYZ' not found or delisted"]}` |
| 429 rate limit | Exponential backoff, 3 retries, then partial results with error |
| Network timeout | 30-second timeout per ticker, clean error in JSON envelope |
| `None` fields | Omit from output (don't serialize `null` for every missing field) |
| DataFrame empty | Return `{"status": "ok", "results": [], "total_results": 0}` |

## Deduplication

Not applicable — financial data is keyed by ticker + type + date, not by DOI/URL. No integration with `state.py` dedup logic.

Metrics are tracked separately via `state.py log-metric` (see state.py spec).

## Dependencies

**Required:** `yfinance` (add to `requirements.txt`)

`yfinance` transitively pulls `pandas`, `numpy`, `requests`, `lxml`, and others. These are heavy but unavoidable for this provider.

## When to Use

- Company fundamentals (revenue, earnings, margins, ratios)
- Historical price data for trend analysis
- Screening multiple tickers by key metrics
- Options chain analysis
- Comparing financials across companies in a sector
- Quick profile lookup before deeper SEC filing analysis

## When NOT to Use

- Real-time trading data (yfinance has 15-min delay on most exchanges)
- Historical intraday data older than 60 days (Yahoo limits granularity)
- Comprehensive SEC filing analysis (use EDGAR provider instead)
- Data requiring audit-grade accuracy (yfinance aggregates third-party data; cross-reference with SEC filings for precision)
