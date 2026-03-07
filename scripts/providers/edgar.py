"""SEC EDGAR provider — full-text search, company filings, XBRL facts/concepts."""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _shared.http_client import create_session  # noqa: E402
from _shared.output import error_response, log, success_response  # noqa: E402

EFTS_BASE = "https://efts.sec.gov/LATEST/search-index"
DATA_BASE = "https://data.sec.gov"
SEC_BASE = "https://www.sec.gov"
TICKERS_URL = f"{SEC_BASE}/files/company_tickers.json"

USER_AGENT = "deep-research-skill admin@example.com"

TYPE_CHOICES = ("filings", "facts", "concept")
TAXONOMY_CHOICES = ("us-gaap", "ifrs-full", "dei")

# Module-level CIK cache (populated on first use per session)
_cik_cache: dict[str, tuple[str, str]] = {}  # ticker -> (cik_padded, entity_name)


def add_arguments(parser):
    parser.add_argument("--ticker", default=None, help="Company ticker symbol")
    parser.add_argument("--form-type", default=None, help="Form type filter (comma-separated, e.g. 10-K,10-Q)")
    parser.add_argument("--year", default=None, help="Date range filter: YYYY or YYYY-YYYY")
    parser.add_argument("--accession", default=None, help="Fetch specific filing by accession number")
    parser.add_argument("--type", default="filings", choices=TYPE_CHOICES, help="Data type (default: filings)")
    parser.add_argument("--taxonomy", default="us-gaap", choices=TAXONOMY_CHOICES, help="XBRL taxonomy (concept mode)")
    parser.add_argument("--concept", default=None, help="XBRL concept name (facts/concept mode)")
    parser.add_argument("--download", action="store_true", default=False, help="Download filing document")


def search(args) -> dict:
    session_dir = args.session_dir or tempfile.mkdtemp(prefix="edgar_")
    rate_limits = {"efts.sec.gov": 10.0, "data.sec.gov": 10.0, "www.sec.gov": 10.0}
    client = create_session(session_dir, rate_limits=rate_limits)
    client.session.headers.update({"User-Agent": USER_AGENT})

    try:
        if args.accession:
            return _fetch_filing(client, args)
        elif args.ticker and args.type == "facts":
            return _get_facts(client, args)
        elif args.ticker and args.type == "concept":
            return _get_concept(client, args)
        elif args.ticker:
            return _get_company_filings(client, args)
        elif args.query:
            return _efts_search(client, args)
        else:
            return error_response(
                ["Provide --query for full-text search, --ticker for company data, or --accession for a specific filing"],
                error_code="missing_input",
            )
    except Exception as e:
        log(f"EDGAR API error: {e}", level="error")
        return error_response([str(e)], error_code="api_error")
    finally:
        client.close()


def _resolve_cik(client, ticker: str) -> tuple[str, str] | None:
    """Resolve ticker to (CIK zero-padded to 10 digits, entity_name)."""
    ticker_upper = ticker.upper()
    if ticker_upper in _cik_cache:
        return _cik_cache[ticker_upper]

    try:
        resp = client.get(TICKERS_URL, timeout=(10, 30))
        if resp.status_code != 200:
            log(f"Failed to fetch company_tickers.json: HTTP {resp.status_code}", level="error")
            return None

        data = resp.json()
        for entry in data.values():
            t = entry.get("ticker", "").upper()
            cik = str(entry.get("cik_str", ""))
            name = entry.get("title", "")
            cik_padded = cik.zfill(10)
            _cik_cache[t] = (cik_padded, name)

        return _cik_cache.get(ticker_upper)
    except Exception as e:
        log(f"CIK resolution error: {e}", level="error")
        return None


def _efts_search(client, args) -> dict:
    """Full-text search across SEC filings via EFTS."""
    params = {
        "q": args.query,
        "dateRange": "custom",
        "from": str(args.offset),
        "size": str(min(args.limit, 100)),
    }

    if args.form_type:
        params["forms"] = args.form_type

    if args.year:
        if "-" in args.year:
            start, end = args.year.split("-", 1)
            params["startdt"] = f"{start}-01-01"
            params["enddt"] = f"{end}-12-31"
        else:
            params["startdt"] = f"{args.year}-01-01"
            params["enddt"] = f"{args.year}-12-31"

    resp = client.get(EFTS_BASE, params=params, timeout=(10, 30))
    if resp.status_code != 200:
        return error_response([f"EFTS search failed: HTTP {resp.status_code}"], error_code="api_error")

    data = resp.json()
    hits = data.get("hits", {}).get("hits", [])
    total = data.get("hits", {}).get("total", {}).get("value", 0)

    results = []
    for hit in hits:
        src = hit.get("_source", {})
        accession = src.get("adsh", "")
        ciks = src.get("ciks", [])
        cik = ciks[0] if ciks else ""
        display_names = src.get("display_names", [])
        entity_name = display_names[0] if display_names else ""

        filing = {
            "entity_name": entity_name,
            "form_type": src.get("file_type", "") or src.get("form", ""),
            "filing_date": src.get("file_date", ""),
            "period_of_report": src.get("period_ending", ""),
            "accession_number": accession,
            "description": src.get("file_description", ""),
        }
        # Add filing URL if we have CIK and accession
        if cik and accession:
            acc_clean = accession.replace("-", "")
            cik_num = cik.lstrip("0") or "0"
            filing["filing_url"] = f"{SEC_BASE}/Archives/edgar/data/{cik_num}/{acc_clean}/"

        results.append(filing)

    return success_response(results, total_results=total, provider="edgar", has_more=total > args.offset + len(results))


def _get_company_filings(client, args) -> dict:
    """Get filings for a company by ticker."""
    resolved = _resolve_cik(client, args.ticker)
    if not resolved:
        return error_response([f"Ticker '{args.ticker}' not found in SEC EDGAR"], error_code="ticker_not_found")

    cik_padded, entity_name = resolved

    url = f"{DATA_BASE}/submissions/CIK{cik_padded}.json"
    resp = client.get(url, timeout=(10, 30))
    if resp.status_code != 200:
        return error_response([f"Failed to fetch submissions: HTTP {resp.status_code}"], error_code="api_error")

    data = resp.json()
    recent = data.get("filings", {}).get("recent", {})

    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    descriptions = recent.get("primaryDocDescription", [])
    periods = recent.get("reportDate", [])

    # Filter by form type if specified
    form_filter = None
    if args.form_type:
        form_filter = set(f.strip().upper() for f in args.form_type.split(","))

    results = []
    cik_num = cik_padded.lstrip("0") or "0"

    for i in range(len(forms)):
        form = forms[i] if i < len(forms) else ""
        if form_filter and form.upper() not in form_filter:
            continue

        accession = accessions[i] if i < len(accessions) else ""
        acc_clean = accession.replace("-", "")
        primary_doc = primary_docs[i] if i < len(primary_docs) else ""

        filing = {
            "ticker": args.ticker.upper(),
            "cik": cik_padded,
            "entity_name": entity_name,
            "form_type": form,
            "filing_date": dates[i] if i < len(dates) else "",
            "period_of_report": periods[i] if i < len(periods) else "",
            "accession_number": accession,
            "description": descriptions[i] if i < len(descriptions) else "",
            "primary_document": primary_doc,
        }
        if accession:
            filing["filing_url"] = f"{SEC_BASE}/Archives/edgar/data/{cik_num}/{acc_clean}/{primary_doc}"

        results.append(filing)
        if len(results) >= args.limit:
            break

    return success_response(
        results, total_results=len(results), provider="edgar",
        ticker=args.ticker.upper(), cik=cik_padded, entity_name=entity_name,
    )


def _get_facts(client, args) -> dict:
    """Get XBRL company facts."""
    resolved = _resolve_cik(client, args.ticker)
    if not resolved:
        return error_response([f"Ticker '{args.ticker}' not found in SEC EDGAR"], error_code="ticker_not_found")

    cik_padded, entity_name = resolved

    url = f"{DATA_BASE}/api/xbrl/companyfacts/CIK{cik_padded}.json"
    resp = client.get(url, timeout=(10, 60))
    if resp.status_code != 200:
        return error_response([f"Failed to fetch company facts: HTTP {resp.status_code}"], error_code="api_error")

    data = resp.json()
    facts = data.get("facts", {})

    # If a specific concept is requested, filter to it
    if args.concept:
        return _extract_concept_from_facts(facts, args.concept, args.ticker.upper(), cik_padded, entity_name)

    # Otherwise, return a summary of available concepts
    taxonomy_summary = {}
    for taxonomy, concepts in facts.items():
        concept_list = []
        for concept_name, concept_data in concepts.items():
            label = concept_data.get("label", concept_name)
            units = list(concept_data.get("units", {}).keys())
            concept_list.append({"concept": concept_name, "label": label, "units": units})
        taxonomy_summary[taxonomy] = {
            "concept_count": len(concept_list),
            "concepts": concept_list[:50],  # Limit to first 50
        }

    return success_response(
        taxonomy_summary, total_results=sum(v["concept_count"] for v in taxonomy_summary.values()),
        provider="edgar", ticker=args.ticker.upper(), cik=cik_padded, entity_name=entity_name,
    )


def _extract_concept_from_facts(facts: dict, concept: str, ticker: str, cik: str, entity_name: str) -> dict:
    """Extract a specific concept from company facts."""
    for taxonomy, concepts in facts.items():
        if concept in concepts:
            concept_data = concepts[concept]
            label = concept_data.get("label", concept)
            units = concept_data.get("units", {})

            values = []
            for unit_name, entries in units.items():
                for entry in entries:
                    val = {
                        "period_end": entry.get("end", ""),
                        "value": entry.get("val"),
                        "form": entry.get("form", ""),
                        "fiscal_year": entry.get("fy"),
                        "fiscal_period": entry.get("fp", ""),
                        "filed": entry.get("filed", ""),
                        "unit": unit_name,
                    }
                    values.append(val)

            # Sort by period_end descending
            values.sort(key=lambda v: v.get("period_end", ""), reverse=True)

            return success_response(
                {"ticker": ticker, "cik": cik, "entity_name": entity_name,
                 "concept": concept, "taxonomy": taxonomy, "label": label,
                 "values": values},
                total_results=len(values), provider="edgar",
            )

    # Concept not found — list available concepts
    available = []
    for taxonomy, concepts in facts.items():
        available.extend(f"{taxonomy}:{name}" for name in list(concepts.keys())[:20])

    return error_response(
        [f"Concept '{concept}' not found. Available (sample): {', '.join(available[:10])}"],
        error_code="concept_not_found",
    )


def _get_concept(client, args) -> dict:
    """Get company concept time series."""
    if not args.concept:
        return error_response(["--concept is required for concept mode"], error_code="missing_concept")

    resolved = _resolve_cik(client, args.ticker)
    if not resolved:
        return error_response([f"Ticker '{args.ticker}' not found in SEC EDGAR"], error_code="ticker_not_found")

    cik_padded, entity_name = resolved
    taxonomy = args.taxonomy

    url = f"{DATA_BASE}/api/xbrl/companyconcept/CIK{cik_padded}/{taxonomy}/{args.concept}.json"
    resp = client.get(url, timeout=(10, 30))
    if resp.status_code == 404:
        return error_response(
            [f"Concept '{args.concept}' not found in taxonomy '{taxonomy}' for {args.ticker}"],
            error_code="concept_not_found",
        )
    if resp.status_code != 200:
        return error_response([f"Failed to fetch concept: HTTP {resp.status_code}"], error_code="api_error")

    data = resp.json()
    label = data.get("label", args.concept)
    units = data.get("units", {})

    values = []
    for unit_name, entries in units.items():
        for entry in entries:
            val = {
                "period_end": entry.get("end", ""),
                "value": entry.get("val"),
                "form": entry.get("form", ""),
                "fiscal_year": entry.get("fy"),
                "fiscal_period": entry.get("fp", ""),
                "filed": entry.get("filed", ""),
                "unit": unit_name,
            }
            values.append(val)

    values.sort(key=lambda v: v.get("period_end", ""), reverse=True)

    return success_response(
        {"ticker": args.ticker.upper(), "cik": cik_padded, "entity_name": entity_name,
         "concept": args.concept, "taxonomy": taxonomy, "label": label,
         "values": values[:args.limit]},
        total_results=len(values), provider="edgar",
    )


def _fetch_filing(client, args) -> dict:
    """Fetch a specific filing by accession number."""
    accession = args.accession.strip()

    # We need a CIK to construct the URL — try to find it via EFTS
    params = {"q": f'"{accession}"', "size": "1"}
    resp = client.get(EFTS_BASE, params=params, timeout=(10, 30))

    if resp.status_code == 200:
        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])
        if hits:
            src = hits[0].get("_source", {})
            cik = src.get("entity_id", "")
            acc_clean = accession.replace("-", "")

            filing = {
                "entity_name": src.get("entity_name", ""),
                "form_type": src.get("file_type", ""),
                "filing_date": src.get("display_date_filed", ""),
                "period_of_report": src.get("period_of_report", ""),
                "accession_number": accession,
                "description": src.get("file_description", ""),
            }
            if cik:
                filing["filing_url"] = f"{SEC_BASE}/Archives/edgar/data/{cik}/{acc_clean}/"
                filing["index_url"] = f"{SEC_BASE}/Archives/edgar/data/{cik}/{acc_clean}/index.json"

            return success_response(filing, total_results=1, provider="edgar")

    return error_response([f"Filing with accession '{accession}' not found"], error_code="filing_not_found")
