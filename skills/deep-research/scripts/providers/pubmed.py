"""PubMed search provider — keyword search, citations, references, related articles, MeSH lookup."""

import re
import tempfile
import xml.etree.ElementTree as ET

from _shared.config import get_config
from _shared.html_extract import strip_jats_xml
from _shared.http_client import create_session
from _shared.metadata import normalize_paper
from _shared.output import error_response, log, success_response

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# ELink linkname mapping
_ELINK_CITED_BY = "pubmed_pubmed_citedin"
_ELINK_REFS = "pubmed_pubmed_refs"

# Publication type filter mapping
_PUB_TYPE_MAP = {
    "review": '"review"[pt]',
    "trial": '"clinical trial"[pt]',
    "meta-analysis": '"meta-analysis"[pt]',
}

_YEAR_RE = re.compile(r"(19|20)\d{2}")


def add_arguments(parser):
    parser.add_argument("--cited-by", default=None, metavar="PMID", help="Forward citations via ELink")
    parser.add_argument("--references", default=None, metavar="PMID", help="Backward references via ELink")
    parser.add_argument("--related", default=None, metavar="PMID", help="Related articles with relevance scores")
    parser.add_argument("--mesh", default=None, metavar="TERM", help="MeSH term lookup")
    parser.add_argument("--fetch-pmids", nargs="+", default=None, metavar="PMID", help="Fetch specific PMIDs")
    parser.add_argument("--year", default=None, metavar="YYYY-YYYY", help="Year range filter")
    parser.add_argument("--type", default=None, choices=["review", "trial", "meta-analysis"],
                        help="Publication type filter", dest="pub_type")
    parser.add_argument("--sort", default="relevance", choices=["relevance", "date"], help="Sort order (default: relevance)")
    parser.add_argument("--fetch", action="store_true", default=False,
                        help="Fetch full details (abstracts) for search results")


def search(args) -> dict:
    session_dir = args.session_dir or tempfile.mkdtemp(prefix="pubmed_")
    config = get_config(session_dir)
    api_key = config.get("ncbi_api_key")
    rps = 10.0 if api_key else 3.0
    client = create_session(session_dir, rate_limits={"eutils.ncbi.nlm.nih.gov": rps})

    # Auto-enable fetch when a session is active — bare PMIDs (no title/abstract)
    # get silently dropped by state tracking, causing silent data loss.
    if args.session_dir and not args.fetch:
        args.fetch = True

    try:
        if args.fetch_pmids:
            return _fetch_pmids(client, args.fetch_pmids, api_key)
        if args.cited_by:
            return _elink_search(client, args, api_key, args.cited_by, _ELINK_CITED_BY, "citations")
        if args.references:
            return _elink_search(client, args, api_key, args.references, _ELINK_REFS, "references")
        if args.related:
            return _related_search(client, args, api_key)
        if args.mesh:
            return _mesh_search(client, args, api_key)
        if args.query:
            if not args.query.strip():
                return error_response(
                    ["Query is required for PubMed keyword search"],
                    error_code="missing_query",
                )
            return _keyword_search(client, args, api_key)
        return error_response(
            ["No search mode specified. Use --query, --cited-by, --references, --related, --mesh, or --fetch-pmids."],
            error_code="missing_query",
        )
    except Exception as e:
        log(f"PubMed API error: {e}", level="error")
        return error_response([str(e)], error_code="api_error")
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Search modes
# ---------------------------------------------------------------------------

def _keyword_search(client, args, api_key) -> dict:
    query = _build_query(args.query, args)
    pmids, count, query_translation = _esearch(client, query, args.limit, args.offset, args.sort, api_key)

    if not pmids:
        return success_response([], total_results=count, provider="pubmed", query=args.query,
                                query_translation=query_translation, has_more=False)

    if args.fetch:
        papers = _efetch_papers(client, pmids, api_key)
    else:
        papers = [{"pmid": pmid, "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"} for pmid in pmids]

    return success_response(
        papers,
        total_results=count,
        provider="pubmed",
        query=args.query,
        query_translation=query_translation,
        has_more=(args.offset + args.limit) < count,
    )


def _elink_search(client, args, api_key, pmid, linkname, mode) -> dict:
    params = {"dbfrom": "pubmed", "db": "pubmed", "id": pmid, "linkname": linkname, "retmode": "json"}
    if api_key:
        params["api_key"] = api_key

    url = f"{BASE_URL}/elink.fcgi"
    resp = client.get(url, params=params)
    if resp.status_code != 200:
        return error_response([f"ELink returned {resp.status_code}: {resp.text[:500]}"], error_code="api_error")

    data = resp.json()
    linked_pmids = _extract_elink_ids(data)

    if not linked_pmids:
        return success_response([], total_results=0, provider="pubmed", mode=mode, pmid=pmid, has_more=False)

    # Apply limit/offset
    total = len(linked_pmids)
    page = linked_pmids[args.offset:args.offset + args.limit]

    papers = _efetch_papers(client, page, api_key)

    return success_response(
        papers,
        total_results=total,
        provider="pubmed",
        mode=mode,
        pmid=pmid,
        has_more=(args.offset + args.limit) < total,
    )


def _related_search(client, args, api_key) -> dict:
    pmid = args.related
    params = {"dbfrom": "pubmed", "db": "pubmed", "id": pmid, "cmd": "neighbor_score", "retmode": "json"}
    if api_key:
        params["api_key"] = api_key

    url = f"{BASE_URL}/elink.fcgi"
    resp = client.get(url, params=params)
    if resp.status_code != 200:
        return error_response([f"ELink returned {resp.status_code}: {resp.text[:500]}"], error_code="api_error")

    data = resp.json()
    scored_ids = _extract_elink_scored_ids(data)

    if not scored_ids:
        return success_response([], total_results=0, provider="pubmed", mode="related", pmid=pmid, has_more=False)

    total = len(scored_ids)
    page = scored_ids[args.offset:args.offset + args.limit]
    page_pmids = [item["pmid"] for item in page]

    papers = _efetch_papers(client, page_pmids, api_key)

    # Attach relevance scores
    score_map = {item["pmid"]: item["score"] for item in page}
    for paper in papers:
        paper["relevance_score"] = score_map.get(paper.get("pmid", ""), 0)

    return success_response(
        papers,
        total_results=total,
        provider="pubmed",
        mode="related",
        pmid=pmid,
        has_more=(args.offset + args.limit) < total,
    )


def _mesh_search(client, args, api_key) -> dict:
    query = f'"{args.mesh}"[MeSH Terms]'
    query = _apply_filters(query, args)
    pmids, count, query_translation = _esearch(client, query, args.limit, args.offset, args.sort, api_key)

    if not pmids:
        return success_response([], total_results=count, provider="pubmed", mode="mesh", mesh_term=args.mesh,
                                query_translation=query_translation, has_more=False)

    if args.fetch:
        papers = _efetch_papers(client, pmids, api_key)
    else:
        papers = [{"pmid": pmid, "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"} for pmid in pmids]

    return success_response(
        papers,
        total_results=count,
        provider="pubmed",
        mode="mesh",
        mesh_term=args.mesh,
        query_translation=query_translation,
        has_more=(args.offset + args.limit) < count,
    )


def _fetch_pmids(client, pmids, api_key) -> dict:
    papers = _efetch_papers(client, pmids, api_key)
    return success_response(papers, total_results=len(papers), provider="pubmed", mode="fetch", has_more=False)


# ---------------------------------------------------------------------------
# NCBI API helpers
# ---------------------------------------------------------------------------

def _build_query(query, args):
    """Build the full ESearch query with year range and type filters."""
    # Warn when query has 5+ space-separated terms without Boolean operators.
    # PubMed ANDs every token — over-specified queries return 0 results.
    terms = query.strip().split()
    has_boolean = any(t.upper() in ("AND", "OR", "NOT") for t in terms)
    has_brackets = "(" in query or "[" in query
    if len(terms) >= 5 and not has_boolean and not has_brackets:
        log(f"PubMed query has {len(terms)} terms with no Boolean operators — "
            f"likely to return 0 results. Use 2-3 core terms with OR groups: "
            f'e.g., \'"term1" AND (term2 OR term3 OR term4)\'', level="warn")
    return _apply_filters(query, args)


def _apply_filters(query, args):
    """Append year range and publication type filters to query."""
    if args.year:
        parts = args.year.split("-")
        query = f"{query} AND {parts[0]}:{parts[1]}[dp]" if len(parts) == 2 else f"{query} AND {parts[0]}[dp]"

    if args.pub_type and args.pub_type in _PUB_TYPE_MAP:
        query = f"{query} AND {_PUB_TYPE_MAP[args.pub_type]}"

    return query


def _esearch(client, query, limit, offset, sort, api_key):
    """Run ESearch and return (pmid_list, total_count, query_translation)."""
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": limit,
        "retstart": offset,
        "sort": sort,
    }
    if api_key:
        params["api_key"] = api_key

    url = f"{BASE_URL}/esearch.fcgi"
    log(f"ESearch: {query}")
    resp = client.get(url, params=params)

    if resp.status_code != 200:
        raise RuntimeError(f"ESearch returned {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    result = data.get("esearchresult", {})
    pmids = result.get("idlist", [])
    count = int(result.get("count", 0))
    query_translation = result.get("querytranslation", "")

    return pmids, count, query_translation


def _efetch_papers(client, pmids, api_key):
    """Fetch full paper details via EFetch XML and parse them."""
    if not pmids:
        return []

    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "xml",
        "retmode": "xml",
    }
    if api_key:
        params["api_key"] = api_key

    url = f"{BASE_URL}/efetch.fcgi"
    log(f"EFetch: {len(pmids)} PMIDs")
    resp = client.get(url, params=params)

    if resp.status_code != 200:
        raise RuntimeError(f"EFetch returned {resp.status_code}: {resp.text[:500]}")

    return _parse_pubmed_xml(resp.text)


def _extract_elink_ids(data):
    """Extract linked PMIDs from ELink JSON response."""
    pmids = []
    linksets = data.get("linksets", [])
    for linkset in linksets:
        link_set_dbs = linkset.get("linksetdbs", [])
        for lsdb in link_set_dbs:
            for link in lsdb.get("links", []):
                pmids.append(str(link))
    return pmids


def _extract_elink_scored_ids(data):
    """Extract scored linked PMIDs from ELink neighbor_score JSON response."""
    results = []
    linksets = data.get("linksets", [])
    for linkset in linksets:
        link_set_dbs = linkset.get("linksetdbs", [])
        for lsdb in link_set_dbs:
            for link in lsdb.get("links", []):
                if isinstance(link, dict):
                    results.append({"pmid": str(link.get("id", "")), "score": int(link.get("score", 0))})
                else:
                    results.append({"pmid": str(link), "score": 0})
    return results


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------

def _parse_pubmed_xml(xml_text):
    """Parse PubmedArticleSet XML into a list of normalized paper dicts."""
    papers = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log(f"XML parse error: {e}", level="error")
        return papers

    for article_elem in root.findall(".//PubmedArticle"):
        raw = _parse_article(article_elem)
        if not raw.get("pmid"):
            continue

        paper = normalize_paper(raw, "pubmed")

        # Add PubMed-specific extra fields
        paper["pmid"] = raw.get("pmid", "")
        paper["pmcid"] = raw.get("pmcid", "")
        paper["journal"] = raw.get("journal", "")
        paper["journal_abbrev"] = raw.get("journal_abbrev", "")
        paper["volume"] = raw.get("volume", "")
        paper["issue"] = raw.get("issue", "")
        paper["pages"] = raw.get("pages", "")
        paper["abstract_sections"] = raw.get("abstract_sections", [])
        paper["publication_types"] = raw.get("publication_types", [])
        paper["mesh_terms"] = raw.get("mesh_terms", [])

        if raw.get("pmcid"):
            paper["pmc_url"] = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{raw['pmcid']}/"

        papers.append(paper)

    return papers


def _parse_article(article_elem):
    """Parse a single <PubmedArticle> element into a raw dict."""
    raw = {}
    medline = article_elem.find("MedlineCitation")
    if medline is None:
        return raw

    # PMID
    pmid_elem = medline.find("PMID")
    if pmid_elem is not None and pmid_elem.text:
        raw["pmid"] = pmid_elem.text.strip()
        raw["url"] = f"https://pubmed.ncbi.nlm.nih.gov/{raw['pmid']}/"

    article = medline.find("Article")
    if article is None:
        return raw

    # Title
    title_elem = article.find("ArticleTitle")
    if title_elem is not None:
        raw["title"] = strip_jats_xml(_elem_text_content(title_elem))

    # Abstract
    abstract_elem = article.find("Abstract")
    if abstract_elem is not None:
        raw["abstract"], raw["abstract_sections"] = _parse_abstract(abstract_elem)

    # Authors
    raw["authors"] = _parse_authors(article.find("AuthorList"))

    # Journal info
    journal_elem = article.find("Journal")
    if journal_elem is not None:
        journal_title = journal_elem.find("Title")
        if journal_title is not None and journal_title.text:
            raw["journal"] = journal_title.text.strip()
            raw["source"] = raw["journal"]  # for normalize_paper venue extraction

        iso_abbrev = journal_elem.find("ISOAbbreviation")
        if iso_abbrev is not None and iso_abbrev.text:
            raw["journal_abbrev"] = iso_abbrev.text.strip()

        # Year from JournalIssue/PubDate
        ji = journal_elem.find("JournalIssue")
        if ji is not None:
            volume_elem = ji.find("Volume")
            if volume_elem is not None and volume_elem.text:
                raw["volume"] = volume_elem.text.strip()

            issue_elem = ji.find("Issue")
            if issue_elem is not None and issue_elem.text:
                raw["issue"] = issue_elem.text.strip()

            pubdate = ji.find("PubDate")
            if pubdate is not None:
                raw["year"] = _parse_pubdate(pubdate)

    # Pages
    pagination = article.find("Pagination")
    if pagination is not None:
        pgn = pagination.find("MedlinePgn")
        if pgn is not None and pgn.text:
            raw["pages"] = pgn.text.strip()

    # Publication types
    pub_types = []
    for pt in article.findall("PublicationTypeList/PublicationType"):
        if pt.text:
            pub_types.append(pt.text.strip())
    if pub_types:
        raw["publication_types"] = pub_types

    # Article IDs (DOI, PMC)
    pubmed_data = article_elem.find("PubmedData")
    if pubmed_data is not None:
        for aid in pubmed_data.findall("ArticleIdList/ArticleId"):
            id_type = aid.get("IdType", "")
            if aid.text:
                if id_type == "doi":
                    raw["doi"] = aid.text.strip()
                elif id_type == "pmc":
                    raw["pmcid"] = aid.text.strip()

    # MeSH terms
    mesh_terms = []
    for mh in medline.findall("MeshHeadingList/MeshHeading"):
        descriptor = mh.find("DescriptorName")
        if descriptor is not None and descriptor.text:
            mesh_terms.append(descriptor.text.strip())
    if mesh_terms:
        raw["mesh_terms"] = mesh_terms

    return raw


def _parse_abstract(abstract_elem):
    """Parse abstract, handling structured abstracts with labels."""
    sections = []
    texts = []

    for at in abstract_elem.findall("AbstractText"):
        label = at.get("Label", "")
        text = strip_jats_xml(_elem_text_content(at))
        if not text:
            continue

        if label:
            sections.append({"label": label, "text": text})
            texts.append(f"{label}: {text}")
        else:
            sections.append({"label": "", "text": text})
            texts.append(text)

    full_abstract = "\n".join(texts)
    return full_abstract, sections


def _parse_authors(author_list_elem):
    """Parse AuthorList into list of author name strings."""
    if author_list_elem is None:
        return []

    authors = []
    for author in author_list_elem.findall("Author"):
        collective = author.find("CollectiveName")
        if collective is not None and collective.text:
            authors.append(collective.text.strip())
            continue

        last = author.find("LastName")
        fore = author.find("ForeName")
        if last is not None and last.text:
            name = last.text.strip()
            if fore is not None and fore.text:
                name = f"{name}, {fore.text.strip()}"
            authors.append(name)

    return authors


def _parse_pubdate(pubdate_elem):
    """Extract year from PubDate element (Year or MedlineDate)."""
    year_elem = pubdate_elem.find("Year")
    if year_elem is not None and year_elem.text:
        try:
            return int(year_elem.text.strip())
        except ValueError:
            pass

    medline_date = pubdate_elem.find("MedlineDate")
    if medline_date is not None and medline_date.text:
        match = _YEAR_RE.search(medline_date.text)
        if match:
            return int(match.group(0))

    return 0


def _elem_text_content(elem):
    """Get all text content from an element including mixed content (text + tail of children)."""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        # Include text inside child tags (e.g., <i>text</i>)
        if child.text:
            parts.append(child.text)
        if child.tail:
            parts.append(child.tail)
    return "".join(parts).strip()
