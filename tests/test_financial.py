"""Tests for yfinance provider, EDGAR provider, and metrics state commands."""

import json
import sys
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from helpers import init_session as _init_session, run_state as _run_state, write_json_file as _write_json_file
from providers import yfinance_provider, edgar


def _parse_result(json_string):
    """Parse the JSON string returned by success_response."""
    return json.loads(json_string)


# ===========================================================================
# 1. yfinance provider
# ===========================================================================

class TestYfinanceArguments:
    def test_type_choices(self):
        assert "profile" in yfinance_provider.TYPE_CHOICES
        assert "history" in yfinance_provider.TYPE_CHOICES
        assert "financials" in yfinance_provider.TYPE_CHOICES
        assert "options" in yfinance_provider.TYPE_CHOICES
        assert "dividends" in yfinance_provider.TYPE_CHOICES
        assert "holders" in yfinance_provider.TYPE_CHOICES

    def test_max_tickers_constant(self):
        assert yfinance_provider.MAX_TICKERS == 5


class TestYfinanceMissingDependency:
    def test_missing_yfinance_returns_error(self):
        args = Namespace(ticker="AAPL", type="profile")
        saved = sys.modules.pop("yfinance", None)
        sys.modules["yfinance"] = None  # type: ignore[assignment]
        try:
            result = yfinance_provider.search(args)
            assert result is None or "missing_dependency" in str(result)
        except (ImportError, SystemExit):
            pass  # Expected when yfinance can't import
        finally:
            sys.modules.pop("yfinance", None)
            if saved is not None:
                sys.modules["yfinance"] = saved


class TestYfinanceTickerValidation:
    def _make_args(self, ticker="AAPL", dtype="profile"):
        return Namespace(
            ticker=ticker, type=dtype, period="1y", interval="1d",
            statement="income", frequency="annual", expiration=None,
        )

    def test_empty_ticker_returns_error(self):
        """Empty ticker string produces error."""
        args = self._make_args(ticker="")
        with patch.dict("sys.modules", {"yfinance": MagicMock()}):
            with pytest.raises(SystemExit):
                yfinance_provider.search(args)

    def test_too_many_tickers_returns_error(self):
        args = self._make_args(ticker="A,B,C,D,E,F")
        with patch.dict("sys.modules", {"yfinance": MagicMock()}):
            with pytest.raises(SystemExit):
                yfinance_provider.search(args)

    @patch.dict("sys.modules", {"yfinance": MagicMock()})
    def test_multi_ticker_parsed_correctly(self):
        """Comma-separated tickers are uppercased and split."""
        mock_yf = sys.modules["yfinance"]
        mock_ticker = MagicMock()
        mock_ticker.info = {"marketCap": 1e12, "shortName": "Test"}
        mock_yf.Ticker.return_value = mock_ticker

        args = self._make_args(ticker="aapl, msft")
        result = _parse_result(yfinance_provider.search(args))
        assert result["status"] == "ok"
        calls = mock_yf.Ticker.call_args_list
        assert calls[0][0][0] == "AAPL"
        assert calls[1][0][0] == "MSFT"


class TestYfinanceIsNan:
    def test_none_is_nan(self):
        assert yfinance_provider._is_nan(None) is True

    def test_float_nan_is_nan(self):
        assert yfinance_provider._is_nan(float("nan")) is True

    def test_normal_float_not_nan(self):
        assert yfinance_provider._is_nan(42.0) is False

    def test_string_not_nan(self):
        assert yfinance_provider._is_nan("hello") is False

    def test_zero_not_nan(self):
        assert yfinance_provider._is_nan(0) is False


class TestYfinanceProfileMode:
    @patch.dict("sys.modules", {"yfinance": MagicMock()})
    def test_profile_extracts_fields(self):
        mock_yf = sys.modules["yfinance"]
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "marketCap": 3000000000000,
            "shortName": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "trailingPE": 30.5,
            "currentPrice": 195.0,
            "currency": "USD",
        }
        mock_yf.Ticker.return_value = mock_ticker

        args = Namespace(
            ticker="AAPL", type="profile", period="1y", interval="1d",
            statement="income", frequency="annual", expiration=None,
        )
        result = _parse_result(yfinance_provider.search(args))
        assert result["status"] == "ok"
        item = result["results"][0]
        assert item["ticker"] == "AAPL"
        assert item["name"] == "Apple Inc."
        assert item["sector"] == "Technology"
        assert item["market_cap"] == 3000000000000
        assert item["trailing_pe"] == 30.5
        assert item["current_price"] == 195.0

    @patch.dict("sys.modules", {"yfinance": MagicMock()})
    def test_profile_missing_market_cap_returns_error(self):
        mock_yf = sys.modules["yfinance"]
        mock_ticker = MagicMock()
        mock_ticker.info = {}
        mock_yf.Ticker.return_value = mock_ticker

        args = Namespace(
            ticker="FAKE", type="profile", period="1y", interval="1d",
            statement="income", frequency="annual", expiration=None,
        )
        result = _parse_result(yfinance_provider.search(args))
        assert result["status"] == "ok"
        item = result["results"][0]
        assert "error" in item

    @patch.dict("sys.modules", {"yfinance": MagicMock()})
    def test_profile_skips_nan_values(self):
        mock_yf = sys.modules["yfinance"]
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "marketCap": 1e12,
            "shortName": "Test",
            "trailingPE": float("nan"),
            "beta": float("nan"),
        }
        mock_yf.Ticker.return_value = mock_ticker

        args = Namespace(
            ticker="TEST", type="profile", period="1y", interval="1d",
            statement="income", frequency="annual", expiration=None,
        )
        result = _parse_result(yfinance_provider.search(args))
        item = result["results"][0]
        assert "trailing_pe" not in item
        assert "beta" not in item
        assert item["name"] == "Test"


class TestYfinanceHistoryMode:
    @patch.dict("sys.modules", {"yfinance": MagicMock()})
    def test_empty_history_returns_zero_points(self):
        import pandas as pd
        mock_yf = sys.modules["yfinance"]
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_yf.Ticker.return_value = mock_ticker

        args = Namespace(
            ticker="AAPL", type="history", period="1y", interval="1d",
            statement="income", frequency="annual", expiration=None,
        )
        result = _parse_result(yfinance_provider.search(args))
        assert result["status"] == "ok"
        item = result["results"][0]
        assert item["data_points"] == 0
        assert item["data"] == []


class TestYfinanceDividendsMode:
    @patch.dict("sys.modules", {"yfinance": MagicMock()})
    def test_empty_dividends(self):
        import pandas as pd
        mock_yf = sys.modules["yfinance"]
        mock_ticker = MagicMock()
        mock_ticker.dividends = pd.Series(dtype=float)
        mock_yf.Ticker.return_value = mock_ticker

        args = Namespace(
            ticker="AAPL", type="dividends", period="1y", interval="1d",
            statement="income", frequency="annual", expiration=None,
        )
        result = _parse_result(yfinance_provider.search(args))
        assert result["status"] == "ok"
        item = result["results"][0]
        assert item["count"] == 0
        assert item["dividends"] == []


class TestYfinanceExceptionHandling:
    @patch.dict("sys.modules", {"yfinance": MagicMock()})
    def test_ticker_exception_captured(self):
        mock_yf = sys.modules["yfinance"]
        mock_yf.Ticker.side_effect = Exception("API down")

        args = Namespace(
            ticker="AAPL", type="profile", period="1y", interval="1d",
            statement="income", frequency="annual", expiration=None,
        )
        result = _parse_result(yfinance_provider.search(args))
        assert result["status"] == "ok"
        item = result["results"][0]
        assert "error" in item
        assert "API down" in item["error"]


# ===========================================================================
# 2. EDGAR provider
# ===========================================================================

class TestEdgarArguments:
    def test_type_choices(self):
        assert "filings" in edgar.TYPE_CHOICES
        assert "facts" in edgar.TYPE_CHOICES
        assert "concept" in edgar.TYPE_CHOICES

    def test_taxonomy_choices(self):
        assert "us-gaap" in edgar.TAXONOMY_CHOICES
        assert "ifrs-full" in edgar.TAXONOMY_CHOICES
        assert "dei" in edgar.TAXONOMY_CHOICES

    def test_user_agent_set(self):
        ua = edgar._get_user_agent()
        assert ua and len(ua) > 0
        assert "deep-research-skill" in ua


class TestEdgarCIKResolution:
    def test_cik_cache_is_dict(self):
        assert isinstance(edgar._cik_cache, dict)

    def test_resolve_cik_caches_results(self):
        """After resolution, subsequent lookups use cache."""
        edgar._cik_cache.clear()
        edgar._cik_cache["AAPL"] = ("0000320193", "Apple Inc.")

        mock_client = MagicMock()
        result = edgar._resolve_cik(mock_client, "AAPL")
        assert result == ("0000320193", "Apple Inc.")
        mock_client.get.assert_not_called()

        edgar._cik_cache.clear()

    def test_resolve_cik_case_insensitive(self):
        edgar._cik_cache.clear()
        edgar._cik_cache["AAPL"] = ("0000320193", "Apple Inc.")

        mock_client = MagicMock()
        result = edgar._resolve_cik(mock_client, "aapl")
        assert result == ("0000320193", "Apple Inc.")

        edgar._cik_cache.clear()

    def test_resolve_cik_http_failure(self):
        edgar._cik_cache.clear()
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_client.get.return_value = mock_resp

        result = edgar._resolve_cik(mock_client, "AAPL")
        assert result is None

        edgar._cik_cache.clear()

    def test_resolve_cik_from_api(self):
        edgar._cik_cache.clear()
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "0": {"ticker": "AAPL", "cik_str": "320193", "title": "Apple Inc."},
            "1": {"ticker": "MSFT", "cik_str": "789019", "title": "Microsoft Corp"},
        }
        mock_client.get.return_value = mock_resp

        result = edgar._resolve_cik(mock_client, "AAPL")
        assert result == ("0000320193", "Apple Inc.")
        # Also cached MSFT
        assert "MSFT" in edgar._cik_cache

        edgar._cik_cache.clear()


class TestEdgarSearchDispatch:
    def _make_args(self, **kwargs):
        defaults = dict(
            query=None, ticker=None, type="filings", form_type=None,
            year=None, accession=None, taxonomy="us-gaap", concept=None,
            download=False, limit=10, offset=0, session_dir=None,
        )
        defaults.update(kwargs)
        return Namespace(**defaults)

    def test_missing_input_returns_error(self):
        args = self._make_args()
        mock_client = MagicMock()

        with patch("providers.edgar.create_session", return_value=mock_client):
            with pytest.raises(SystemExit):
                edgar.search(args)

    def test_accession_dispatches_to_fetch_filing(self):
        args = self._make_args(accession="0000320193-23-000106")
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "hits": {"hits": [{
                "_source": {
                    "entity_id": "320193",
                    "entity_name": "Apple Inc.",
                    "file_type": "10-K",
                    "display_date_filed": "2023-11-03",
                    "period_of_report": "2023-09-30",
                    "file_description": "Annual Report",
                    "adsh": "0000320193-23-000106",
                }
            }], "total": {"value": 1}}
        }
        mock_client.get.return_value = mock_resp

        with patch("providers.edgar.create_session", return_value=mock_client):
            result = _parse_result(edgar.search(args))
        assert result["status"] == "ok"
        assert result["results"]["accession_number"] == "0000320193-23-000106"


class TestEdgarEFTSSearch:
    def test_efts_search_parses_results(self):
        args = Namespace(
            query="artificial intelligence", ticker=None, type="filings",
            form_type="10-K", year="2024", accession=None, taxonomy="us-gaap",
            concept=None, download=False, limit=10, offset=0, session_dir=None,
        )

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "hits": {
                "hits": [{
                    "_source": {
                        "adsh": "0001234567-24-000001",
                        "ciks": ["320193"],
                        "display_names": ["Apple Inc."],
                        "file_type": "10-K",
                        "file_date": "2024-01-15",
                        "period_ending": "2023-12-31",
                        "file_description": "Annual Report",
                    }
                }],
                "total": {"value": 42},
            }
        }
        mock_client.get.return_value = mock_resp

        with patch("providers.edgar.create_session", return_value=mock_client):
            result = _parse_result(edgar.search(args))

        assert result["status"] == "ok"
        assert result["total_results"] == 42
        assert len(result["results"]) == 1
        filing = result["results"][0]
        assert filing["entity_name"] == "Apple Inc."
        assert filing["form_type"] == "10-K"
        assert "filing_url" in filing

    def test_efts_year_range_parsing(self):
        args = Namespace(
            query="test", ticker=None, type="filings", form_type=None,
            year="2022-2024", accession=None, taxonomy="us-gaap",
            concept=None, download=False, limit=10, offset=0, session_dir=None,
        )

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"hits": {"hits": [], "total": {"value": 0}}}
        mock_client.get.return_value = mock_resp

        with patch("providers.edgar.create_session", return_value=mock_client):
            edgar.search(args)

        call_kwargs = mock_client.get.call_args
        params = call_kwargs[1].get("params") or call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get("params", {})
        assert params.get("startdt") == "2022-01-01"
        assert params.get("enddt") == "2024-12-31"

    def test_efts_http_error(self):
        args = Namespace(
            query="test", ticker=None, type="filings", form_type=None,
            year=None, accession=None, taxonomy="us-gaap",
            concept=None, download=False, limit=10, offset=0, session_dir=None,
        )
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_client.get.return_value = mock_resp

        with patch("providers.edgar.create_session", return_value=mock_client):
            with pytest.raises(SystemExit):
                edgar.search(args)


class TestEdgarXBRL:
    def _make_args(self, **kwargs):
        defaults = dict(
            query=None, ticker="AAPL", type="facts", form_type=None,
            year=None, accession=None, taxonomy="us-gaap", concept=None,
            download=False, limit=10, offset=0, session_dir=None,
        )
        defaults.update(kwargs)
        return Namespace(**defaults)

    def test_facts_summary_returns_concepts(self):
        edgar._cik_cache["AAPL"] = ("0000320193", "Apple Inc.")

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "facts": {
                "us-gaap": {
                    "Revenue": {"label": "Revenue", "units": {"USD": []}},
                    "Assets": {"label": "Total Assets", "units": {"USD": []}},
                }
            }
        }
        mock_client.get.return_value = mock_resp

        args = self._make_args()
        with patch("providers.edgar.create_session", return_value=mock_client):
            result = _parse_result(edgar.search(args))

        assert result["status"] == "ok"
        us_gaap = result["results"]["us-gaap"]
        assert us_gaap["concept_count"] == 2

        edgar._cik_cache.clear()

    def test_facts_specific_concept(self):
        edgar._cik_cache["AAPL"] = ("0000320193", "Apple Inc.")

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "facts": {
                "us-gaap": {
                    "Revenue": {
                        "label": "Revenue",
                        "units": {"USD": [
                            {"end": "2023-09-30", "val": 383285000000, "form": "10-K", "fy": 2023, "fp": "FY", "filed": "2023-11-03"},
                            {"end": "2022-09-24", "val": 394328000000, "form": "10-K", "fy": 2022, "fp": "FY", "filed": "2022-10-28"},
                        ]},
                    }
                }
            }
        }
        mock_client.get.return_value = mock_resp

        args = self._make_args(concept="Revenue")
        with patch("providers.edgar.create_session", return_value=mock_client):
            result = _parse_result(edgar.search(args))

        assert result["status"] == "ok"
        assert result["results"]["concept"] == "Revenue"
        assert len(result["results"]["values"]) == 2
        # Sorted descending by period_end
        assert result["results"]["values"][0]["period_end"] == "2023-09-30"

        edgar._cik_cache.clear()

    def test_concept_not_found_lists_available(self):
        edgar._cik_cache["AAPL"] = ("0000320193", "Apple Inc.")

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "facts": {
                "us-gaap": {
                    "Revenue": {"label": "Revenue", "units": {"USD": []}},
                }
            }
        }
        mock_client.get.return_value = mock_resp

        args = self._make_args(concept="NonExistent")
        with patch("providers.edgar.create_session", return_value=mock_client):
            with pytest.raises(SystemExit):
                edgar.search(args)

        edgar._cik_cache.clear()

    def test_concept_mode_requires_concept(self):
        edgar._cik_cache["AAPL"] = ("0000320193", "Apple Inc.")

        mock_client = MagicMock()
        args = self._make_args(type="concept", concept=None)
        with patch("providers.edgar.create_session", return_value=mock_client):
            with pytest.raises(SystemExit):
                edgar.search(args)

        edgar._cik_cache.clear()

    def test_concept_mode_404_returns_error(self):
        edgar._cik_cache["AAPL"] = ("0000320193", "Apple Inc.")

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_client.get.return_value = mock_resp

        args = self._make_args(type="concept", concept="FakeMetric")
        with patch("providers.edgar.create_session", return_value=mock_client):
            with pytest.raises(SystemExit):
                edgar.search(args)

        edgar._cik_cache.clear()


class TestEdgarTickerNotFound:
    def test_unknown_ticker_returns_error(self):
        edgar._cik_cache.clear()
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "0": {"ticker": "AAPL", "cik_str": "320193", "title": "Apple Inc."}
        }
        mock_client.get.return_value = mock_resp

        args = Namespace(
            query=None, ticker="FAKEXYZ", type="filings", form_type=None,
            year=None, accession=None, taxonomy="us-gaap", concept=None,
            download=False, limit=10, offset=0, session_dir=None,
        )
        with patch("providers.edgar.create_session", return_value=mock_client):
            with pytest.raises(SystemExit):
                edgar.search(args)

        edgar._cik_cache.clear()


class TestEdgarCompanyFilings:
    def test_company_filings_with_form_filter(self):
        edgar._cik_cache["AAPL"] = ("0000320193", "Apple Inc.")

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "filings": {
                "recent": {
                    "form": ["10-K", "10-Q", "8-K", "10-K"],
                    "filingDate": ["2024-01-01", "2024-02-01", "2024-03-01", "2023-01-01"],
                    "accessionNumber": ["0001-24-001", "0001-24-002", "0001-24-003", "0001-23-001"],
                    "primaryDocument": ["doc1.htm", "doc2.htm", "doc3.htm", "doc4.htm"],
                    "primaryDocDescription": ["Annual", "Quarterly", "Current", "Annual"],
                    "reportDate": ["2023-12-31", "2023-09-30", "2024-02-15", "2022-12-31"],
                }
            }
        }
        mock_client.get.return_value = mock_resp

        args = Namespace(
            query=None, ticker="AAPL", type="filings", form_type="10-K",
            year=None, accession=None, taxonomy="us-gaap", concept=None,
            download=False, limit=10, offset=0, session_dir=None,
        )
        with patch("providers.edgar.create_session", return_value=mock_client):
            result = _parse_result(edgar.search(args))

        assert result["status"] == "ok"
        assert len(result["results"]) == 2  # Only 10-K forms
        for r in result["results"]:
            assert r["form_type"] == "10-K"

        edgar._cik_cache.clear()

    def test_company_filings_respects_limit(self):
        edgar._cik_cache["AAPL"] = ("0000320193", "Apple Inc.")

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "filings": {
                "recent": {
                    "form": ["10-K"] * 20,
                    "filingDate": ["2024-01-01"] * 20,
                    "accessionNumber": [f"0001-24-{i:03d}" for i in range(20)],
                    "primaryDocument": [f"doc{i}.htm" for i in range(20)],
                    "primaryDocDescription": ["Annual"] * 20,
                    "reportDate": ["2023-12-31"] * 20,
                }
            }
        }
        mock_client.get.return_value = mock_resp

        args = Namespace(
            query=None, ticker="AAPL", type="filings", form_type=None,
            year=None, accession=None, taxonomy="us-gaap", concept=None,
            download=False, limit=5, offset=0, session_dir=None,
        )
        with patch("providers.edgar.create_session", return_value=mock_client):
            result = _parse_result(edgar.search(args))

        assert len(result["results"]) == 5

        edgar._cik_cache.clear()


class TestEdgarAccessionFormatting:
    def test_accession_to_url_strips_dashes(self):
        """Accession number dashes are removed for URL construction."""
        accession = "0000320193-23-000106"
        acc_clean = accession.replace("-", "")
        assert acc_clean == "000032019323000106"
        assert "-" not in acc_clean

    def test_cik_padding(self):
        """CIK is zero-padded to 10 digits."""
        cik = "320193"
        padded = cik.zfill(10)
        assert padded == "0000320193"
        assert len(padded) == 10


# ===========================================================================
# 3. Metrics state (CLI-based integration tests)
# ===========================================================================

class TestMetricsLogAndRetrieve:
    def test_log_metric_single(self, tmp_path):
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        result, data = _run_state(
            "log-metric", "--session-dir", session_dir,
            "--ticker", "AAPL", "--metric", "revenue",
            "--value", "383285000000", "--source", "yfinance",
            "--unit", "USD", "--period", "FY2023",
        )
        assert result.returncode == 0
        assert data["results"]["ticker"] == "AAPL"
        assert data["results"]["metric"] == "revenue"

    def test_get_metrics_by_ticker(self, tmp_path):
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        _run_state(
            "log-metric", "--session-dir", session_dir,
            "--ticker", "AAPL", "--metric", "revenue",
            "--value", "383285000000", "--source", "yfinance",
        )
        _run_state(
            "log-metric", "--session-dir", session_dir,
            "--ticker", "AAPL", "--metric", "net_income",
            "--value", "96995000000", "--source", "yfinance",
        )

        result, data = _run_state(
            "get-metrics", "--session-dir", session_dir,
            "--ticker", "AAPL",
        )
        assert result.returncode == 0
        assert len(data["results"]) == 2
        metrics = {r["metric"] for r in data["results"]}
        assert metrics == {"revenue", "net_income"}

    def test_get_metric_across_tickers(self, tmp_path):
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        _run_state(
            "log-metric", "--session-dir", session_dir,
            "--ticker", "AAPL", "--metric", "revenue",
            "--value", "383285000000", "--source", "yfinance",
        )
        _run_state(
            "log-metric", "--session-dir", session_dir,
            "--ticker", "MSFT", "--metric", "revenue",
            "--value", "211915000000", "--source", "yfinance",
        )

        result, data = _run_state(
            "get-metric", "--session-dir", session_dir,
            "--metric", "revenue",
        )
        assert result.returncode == 0
        assert len(data["results"]) == 2
        tickers = {r["ticker"] for r in data["results"]}
        assert tickers == {"AAPL", "MSFT"}


class TestMetricsDedup:
    def test_upsert_replaces_duplicate(self, tmp_path):
        """Same (ticker, metric, period, source) replaces previous value."""
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        _run_state(
            "log-metric", "--session-dir", session_dir,
            "--ticker", "AAPL", "--metric", "revenue",
            "--value", "OLD_VALUE", "--source", "yfinance",
            "--period", "FY2023",
        )
        _run_state(
            "log-metric", "--session-dir", session_dir,
            "--ticker", "AAPL", "--metric", "revenue",
            "--value", "NEW_VALUE", "--source", "yfinance",
            "--period", "FY2023",
        )

        result, data = _run_state(
            "get-metrics", "--session-dir", session_dir,
            "--ticker", "AAPL",
        )
        assert len(data["results"]) == 1
        assert data["results"][0]["value"] == "NEW_VALUE"


class TestMetricsBatch:
    def test_log_metrics_batch(self, tmp_path):
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        batch = [
            {"ticker": "AAPL", "metric": "revenue", "value": "383285000000", "source": "edgar"},
            {"ticker": "AAPL", "metric": "net_income", "value": "96995000000", "source": "edgar"},
            {"ticker": "MSFT", "metric": "revenue", "value": "211915000000", "source": "edgar"},
        ]
        json_path = _write_json_file(tmp_path, batch)

        result, data = _run_state(
            "log-metrics", "--session-dir", session_dir,
            "--from-json", json_path,
        )
        assert result.returncode == 0
        assert len(data["results"]) == 3

        # Verify all retrievable
        _, aapl_data = _run_state("get-metrics", "--session-dir", session_dir, "--ticker", "AAPL")
        assert len(aapl_data["results"]) == 2


class TestMetricsSummary:
    def test_summary_includes_metrics(self, tmp_path):
        session_dir = str(tmp_path / "session")
        _init_session(session_dir)

        _run_state(
            "log-metric", "--session-dir", session_dir,
            "--ticker", "AAPL", "--metric", "revenue",
            "--value", "383285000000", "--source", "yfinance",
        )

        result, data = _run_state("summary", "--session-dir", session_dir)
        assert result.returncode == 0
        assert "metrics" in data["results"]
        assert len(data["results"]["metrics"]) == 1
        assert data["results"]["metrics"][0]["ticker"] == "AAPL"
