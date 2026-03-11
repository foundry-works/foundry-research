"""Unit tests for search providers — all HTTP calls are mocked."""

import json
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client():
    """Create a mock HttpClient with a mock session."""
    client = MagicMock()
    client.session = MagicMock()
    client.session.headers = {}
    return client


def _mock_response(status_code=200, json_data=None, text=""):
    """Create a mock HTTP response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


def _parse_output(output_str):
    """Parse the JSON envelope returned by success_response/error_response."""
    return json.loads(output_str)


def _base_args(**overrides):
    """Create a Namespace with common defaults, merged with overrides."""
    defaults = {
        "query": None,
        "limit": 10,
        "offset": 0,
        "session_dir": "/tmp/test_session",
    }
    defaults.update(overrides)
    return Namespace(**defaults)


# ===========================================================================
# Semantic Scholar
# ===========================================================================

class TestSemanticScholar:

    @patch("providers.semantic_scholar.get_config", return_value={})
    @patch("providers.semantic_scholar.create_session")
    def test_keyword_search(self, mock_create, mock_config):
        from providers import semantic_scholar

        client = _make_mock_client()
        mock_create.return_value = client

        api_response = {
            "data": [{
                "paperId": "abc",
                "title": "Test Paper",
                "abstract": "test",
                "authors": [{"name": "John"}],
                "citationCount": 5,
                "year": 2024,
                "externalIds": {"DOI": "10.1234/test"},
                "url": "https://semanticscholar.org/paper/abc",
                "venue": "NeurIPS",
                "journal": None,
                "tldr": {"text": "A test paper"},
                "openAccessPdf": {"url": "http://example.com/paper.pdf"},
            }],
            "total": 1,
        }

        client.get.return_value = _mock_response(200, api_response)

        args = _base_args(
            query="test",
            year_range=None,
            fields_of_study=None,
            min_citations=None,
            sort=None,
            cited_by=None,
            references=None,
            recommendations=None,
            author=None,
        )
        result = _parse_output(semantic_scholar.search(args))

        assert result["status"] == "ok"
        assert result["total_results"] == 1
        assert len(result["results"]) == 1

        paper = result["results"][0]
        assert paper["title"] == "Test Paper"
        assert paper["tldr"] == "A test paper"
        assert paper["is_open_access"] is True
        client.get.assert_called_once()

    @patch("providers.semantic_scholar.get_config", return_value={})
    @patch("providers.semantic_scholar.create_session")
    def test_api_error_returns_error_envelope(self, mock_create, mock_config):
        from providers import semantic_scholar

        client = _make_mock_client()
        mock_create.return_value = client
        client.get.return_value = _mock_response(403, text="Forbidden")

        args = _base_args(
            query="test",
            year_range=None,
            fields_of_study=None,
            min_citations=None,
            sort=None,
            cited_by=None,
            references=None,
            recommendations=None,
            author=None,
        )

        with pytest.raises(SystemExit):
            semantic_scholar.search(args)

    @patch("providers.semantic_scholar.get_config", return_value={})
    @patch("providers.semantic_scholar.create_session")
    def test_min_citations_filter(self, mock_create, mock_config):
        from providers import semantic_scholar

        client = _make_mock_client()
        mock_create.return_value = client

        api_response = {
            "data": [
                {
                    "paperId": "abc",
                    "title": "High Cite Paper",
                    "abstract": "test",
                    "authors": [{"name": "John"}],
                    "citationCount": 100,
                    "year": 2024,
                    "externalIds": {},
                    "url": "https://example.com",
                    "venue": "",
                    "journal": {},
                    "tldr": None,
                    "openAccessPdf": None,
                },
                {
                    "paperId": "def",
                    "title": "Low Cite Paper",
                    "abstract": "test",
                    "authors": [],
                    "citationCount": 2,
                    "year": 2024,
                    "externalIds": {},
                    "url": "https://example.com",
                    "venue": "",
                    "journal": {},
                    "tldr": None,
                    "openAccessPdf": None,
                },
            ],
            "total": 2,
        }

        client.get.return_value = _mock_response(200, api_response)

        args = _base_args(
            query="test",
            year_range=None,
            fields_of_study=None,
            min_citations=50,
            sort=None,
            cited_by=None,
            references=None,
            recommendations=None,
            author=None,
        )
        result = _parse_output(semantic_scholar.search(args))

        assert result["status"] == "ok"
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "High Cite Paper"


# ===========================================================================
# OpenAlex
# ===========================================================================

class TestOpenAlex:

    @patch("providers.openalex.get_config", return_value={})
    @patch("providers.openalex.create_session")
    def test_keyword_search(self, mock_create, mock_config):
        from providers import openalex

        client = _make_mock_client()
        mock_create.return_value = client

        api_response = {
            "meta": {"count": 1, "next_cursor": None},
            "results": [{
                "id": "W123",
                "title": "Test Work",
                "authorships": [{"author": {"display_name": "Jane Doe"}}],
                "publication_year": 2024,
                "abstract_inverted_index": {"This": [0], "is": [1], "a": [2], "test": [3]},
                "doi": "https://doi.org/10.1234/test",
                "primary_location": {"source": {"display_name": "Nature"}},
                "cited_by_count": 10,
                "type": "article",
                "open_access": {"is_oa": True, "oa_url": "http://example.com/oa.pdf"},
                "cited_by_percentile_year": {"min": 95},
                "topics": [{"display_name": "Machine Learning"}],
            }],
        }

        client.get.return_value = _mock_response(200, api_response)

        args = _base_args(
            query="test",
            year_range=None,
            open_access_only=False,
            sort=None,
        )
        result = _parse_output(openalex.search(args))

        assert result["status"] == "ok"
        assert result["total_results"] == 1
        assert len(result["results"]) == 1

        paper = result["results"][0]
        assert paper["title"] == "Test Work"
        assert paper["is_open_access"] is True
        assert paper["topics"] == ["Machine Learning"]

    @patch("providers.openalex.get_config", return_value={})
    @patch("providers.openalex.create_session")
    def test_rate_limit_error(self, mock_create, mock_config):
        from providers import openalex

        client = _make_mock_client()
        mock_create.return_value = client

        error_resp = _mock_response(429, json_data={"message": "Rate limited"}, text="Rate limited")
        client.get.return_value = error_resp

        args = _base_args(
            query="test",
            year_range=None,
            open_access_only=False,
            sort=None,
        )

        with pytest.raises(SystemExit):
            openalex.search(args)

    @patch("providers.openalex.get_config", return_value={})
    @patch("providers.openalex.create_session")
    def test_missing_query_returns_error(self, mock_create, mock_config):
        from providers import openalex

        client = _make_mock_client()
        mock_create.return_value = client

        args = _base_args(query=None, year_range=None, open_access_only=False, sort=None)

        with pytest.raises(SystemExit):
            openalex.search(args)


# ===========================================================================
# arXiv
# ===========================================================================

ARXIV_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <opensearch:totalResults>1</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2301.12345v1</id>
    <title>Test arXiv Paper</title>
    <summary>An arXiv test abstract</summary>
    <author><name>Alice Author</name></author>
    <published>2024-01-15T00:00:00Z</published>
    <updated>2024-01-15T00:00:00Z</updated>
    <link href="http://arxiv.org/abs/2301.12345v1" rel="alternate" type="text/html"/>
    <link href="http://arxiv.org/pdf/2301.12345v1" title="pdf" rel="related" type="application/pdf"/>
    <arxiv:primary_category term="cs.AI"/>
    <category term="cs.AI"/>
    <category term="cs.LG"/>
  </entry>
</feed>
"""


class TestArxiv:

    @patch("providers.arxiv.create_session")
    def test_keyword_search(self, mock_create):
        from providers import arxiv

        client = _make_mock_client()
        mock_create.return_value = client

        resp = _mock_response(200, text=ARXIV_XML)
        resp.text = ARXIV_XML
        client.get.return_value = resp

        args = _base_args(
            query="test",
            categories=None,
            category_expr=None,
            sort="relevance",
            days=None,
            download=None,
            to_md=False,
            list_categories=None,
        )
        result = _parse_output(arxiv.search(args))

        assert result["status"] == "ok"
        assert result["total_results"] == 1
        assert len(result["results"]) == 1

        paper = result["results"][0]
        assert paper["title"] == "Test arXiv Paper"
        assert paper["arxiv_id"] == "2301.12345v1"
        assert paper["primary_category"] == "cs.AI"
        assert "cs.AI" in paper["categories"]
        assert "cs.LG" in paper["categories"]

    @patch("providers.arxiv.create_session")
    def test_api_error(self, mock_create):
        from providers import arxiv

        client = _make_mock_client()
        mock_create.return_value = client
        client.get.return_value = _mock_response(500, text="Server Error")

        args = _base_args(
            query="test",
            categories=None,
            category_expr=None,
            sort="relevance",
            days=None,
            download=None,
            to_md=False,
            list_categories=None,
        )

        with pytest.raises(SystemExit):
            arxiv.search(args)

    @patch("providers.arxiv.create_session")
    def test_category_filter(self, mock_create):
        from providers import arxiv

        client = _make_mock_client()
        mock_create.return_value = client

        resp = _mock_response(200, text=ARXIV_XML)
        resp.text = ARXIV_XML
        client.get.return_value = resp

        args = _base_args(
            query="transformers",
            categories=["cs.AI", "cs.LG"],
            category_expr=None,
            sort="relevance",
            days=None,
            download=None,
            to_md=False,
            list_categories=None,
        )
        result = _parse_output(arxiv.search(args))

        assert result["status"] == "ok"
        # Verify the query was built with category filters by checking the URL called
        call_args = client.get.call_args
        url_called = call_args[0][0]
        assert "cat%3Acs.AI" in url_called or "cat:cs.AI" in url_called


# ===========================================================================
# PubMed
# ===========================================================================

PUBMED_EFETCH_XML = """\
<?xml version="1.0"?>
<PubmedArticleSet>
<PubmedArticle>
<MedlineCitation>
<PMID>12345</PMID>
<Article>
<ArticleTitle>Test PubMed Paper</ArticleTitle>
<Abstract><AbstractText>A test abstract</AbstractText></Abstract>
<AuthorList>
<Author><LastName>Smith</LastName><ForeName>John</ForeName></Author>
</AuthorList>
<Journal>
<Title>Nature</Title>
<JournalIssue>
<Volume>1</Volume>
<Issue>1</Issue>
<PubDate><Year>2024</Year></PubDate>
</JournalIssue>
</Journal>
</Article>
</MedlineCitation>
<PubmedData>
<ArticleIdList>
<ArticleId IdType="doi">10.1234/test</ArticleId>
<ArticleId IdType="pmc">PMC12345</ArticleId>
</ArticleIdList>
</PubmedData>
</PubmedArticle>
</PubmedArticleSet>
"""


class TestPubMed:

    @patch("providers.pubmed.get_config", return_value={})
    @patch("providers.pubmed.create_session")
    def test_keyword_search_no_fetch(self, mock_create, mock_config):
        """Keyword search without --fetch returns PMIDs only (no EFetch call)."""
        from providers import pubmed

        client = _make_mock_client()
        mock_create.return_value = client

        esearch_response = _mock_response(200, json_data={
            "esearchresult": {
                "idlist": ["12345"],
                "count": "1",
                "querytranslation": "test[All Fields]",
            }
        })
        client.get.return_value = esearch_response

        # session_dir=None prevents auto-fetch (pubmed auto-enables fetch when session_dir is set)
        args = _base_args(
            query="test",
            session_dir=None,
            cited_by=None,
            references=None,
            related=None,
            mesh=None,
            fetch_pmids=None,
            year=None,
            pub_type=None,
            sort="relevance",
            fetch=False,
        )
        result = _parse_output(pubmed.search(args))

        assert result["status"] == "ok"
        assert result["total_results"] == 1
        assert result["results"][0]["pmid"] == "12345"
        # Only one call (ESearch), no EFetch
        assert client.get.call_count == 1

    @patch("providers.pubmed.get_config", return_value={})
    @patch("providers.pubmed.create_session")
    def test_keyword_search_with_fetch(self, mock_create, mock_config):
        """Keyword search with --fetch makes ESearch then EFetch calls."""
        from providers import pubmed

        client = _make_mock_client()
        mock_create.return_value = client

        esearch_resp = _mock_response(200, json_data={
            "esearchresult": {
                "idlist": ["12345"],
                "count": "1",
                "querytranslation": "test[All Fields]",
            }
        })

        efetch_resp = _mock_response(200, text=PUBMED_EFETCH_XML)
        efetch_resp.text = PUBMED_EFETCH_XML

        client.get.side_effect = [esearch_resp, efetch_resp]

        args = _base_args(
            query="test",
            cited_by=None,
            references=None,
            related=None,
            mesh=None,
            fetch_pmids=None,
            year=None,
            pub_type=None,
            sort="relevance",
            fetch=True,
        )
        result = _parse_output(pubmed.search(args))

        assert result["status"] == "ok"
        assert len(result["results"]) == 1

        paper = result["results"][0]
        assert paper["title"] == "Test PubMed Paper"
        assert paper["pmid"] == "12345"
        assert paper["pmcid"] == "PMC12345"
        assert paper["journal"] == "Nature"
        # Two calls: ESearch + EFetch
        assert client.get.call_count == 2

    @patch("providers.pubmed.get_config", return_value={})
    @patch("providers.pubmed.create_session")
    def test_esearch_failure_raises(self, mock_create, mock_config):
        """If ESearch itself fails, the exception propagates to error_response."""
        from providers import pubmed

        client = _make_mock_client()
        mock_create.return_value = client

        client.get.return_value = _mock_response(500, text="Server Error")

        args = _base_args(
            query="test",
            cited_by=None,
            references=None,
            related=None,
            mesh=None,
            fetch_pmids=None,
            year=None,
            pub_type=None,
            sort="relevance",
            fetch=False,
        )

        # _esearch raises RuntimeError on non-200, which is caught by search() and
        # forwarded to error_response -> sys.exit
        with pytest.raises(SystemExit):
            pubmed.search(args)


# ===========================================================================
# bioRxiv
# ===========================================================================

class TestBioRxiv:

    @patch("providers.biorxiv.create_session")
    def test_doi_lookup(self, mock_create):
        from providers import biorxiv

        client = _make_mock_client()
        mock_create.return_value = client

        api_response = {
            "messages": [{"status": "ok"}],
            "collection": [{
                "biorxiv_doi": "10.1101/2024.01.001",
                "doi": "10.1101/2024.01.001",
                "title": "Test Preprint",
                "authors": "Smith, J; Doe, J",
                "date": "2024-01-15",
                "category": "neuroscience",
                "version": "1",
                "abstract": "A preprint",
                "server": "biorxiv",
            }],
        }

        client.get.return_value = _mock_response(200, api_response)

        args = _base_args(
            query=None,
            doi="10.1101/2024.01.001",
            server="biorxiv",
            days=30,
            category=None,
        )
        result = _parse_output(biorxiv.search(args))

        assert result["status"] == "ok"
        assert len(result["results"]) == 1

        paper = result["results"][0]
        assert paper["title"] == "Test Preprint"
        assert paper["category"] == "neuroscience"
        assert paper["version"] == "1"

    @patch("providers.biorxiv.create_session")
    def test_doi_not_found(self, mock_create):
        from providers import biorxiv

        client = _make_mock_client()
        mock_create.return_value = client

        # First server returns 404, second also returns 404
        client.get.return_value = _mock_response(404, text="Not found")

        args = _base_args(
            query=None,
            doi="10.1101/nonexistent",
            server="both",
            days=30,
            category=None,
        )

        with pytest.raises(SystemExit):
            biorxiv.search(args)

    @patch("providers.biorxiv.get_config", return_value={})
    @patch("providers.biorxiv.create_session")
    def test_keyword_delegates_to_openalex(self, mock_create, mock_config):
        """Keyword search delegates to OpenAlex with biorxiv DOI prefix filter."""
        from providers import biorxiv

        client = _make_mock_client()
        mock_create.return_value = client

        openalex_response = {
            "meta": {"count": 1, "next_cursor": None},
            "results": [{
                "id": "W999",
                "title": "Bio Preprint",
                "authorships": [{"author": {"display_name": "Bio Author"}}],
                "publication_year": 2024,
                "abstract_inverted_index": {"Bio": [0], "test": [1]},
                "doi": "https://doi.org/10.1101/2024.01.999",
                "primary_location": {"source": {"display_name": "bioRxiv"}},
                "cited_by_count": 3,
                "type": "article",
                "open_access": {"is_oa": True, "oa_url": None},
            }],
        }

        client.get.return_value = _mock_response(200, openalex_response)

        args = _base_args(
            query="neural circuits",
            doi=None,
            server="biorxiv",
            days=30,
            category=None,
        )
        result = _parse_output(biorxiv.search(args))

        assert result["status"] == "ok"
        assert len(result["results"]) == 1
        # Verify the OpenAlex call used biorxiv DOI prefix filter
        call_kwargs = client.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert "10.1101" in str(params.get("filter", ""))


# ===========================================================================
# GitHub
# ===========================================================================

class TestGitHub:

    @patch("providers.github.get_config", return_value={})
    @patch("providers.github.create_session")
    def test_repo_search(self, mock_create, mock_config):
        from providers import github

        client = _make_mock_client()
        mock_create.return_value = client

        api_response = {
            "total_count": 1,
            "items": [{
                "full_name": "owner/repo",
                "description": "A test repo",
                "stargazers_count": 100,
                "forks_count": 10,
                "language": "Python",
                "topics": ["ml"],
                "updated_at": "2024-01-01T00:00:00Z",
                "license": {"spdx_id": "MIT"},
                "html_url": "https://github.com/owner/repo",
                "open_issues_count": 5,
            }],
        }

        client.get.return_value = _mock_response(200, api_response)

        args = _base_args(
            query="test",
            type="repos",
            sort=None,
            language=None,
            min_stars=None,
            repo=None,
            include_readme=False,
        )
        result = _parse_output(github.search(args))

        assert result["status"] == "ok"
        assert result["total_results"] == 1

        repo = result["results"][0]
        assert repo["full_name"] == "owner/repo"
        assert repo["stars"] == 100
        assert repo["license"] == "MIT"

    @patch("providers.github.get_config", return_value={})
    @patch("providers.github.create_session")
    def test_code_search_requires_auth(self, mock_create, mock_config):
        """Code search without a token returns an auth_required error."""
        from providers import github

        client = _make_mock_client()
        mock_create.return_value = client

        # No token in config or env
        args = _base_args(
            query="test",
            type="code",
            sort=None,
            language=None,
            min_stars=None,
            repo=None,
            include_readme=False,
        )

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(SystemExit):
                github.search(args)

    @patch("providers.github.get_config", return_value={})
    @patch("providers.github.create_session")
    def test_repo_search_api_error(self, mock_create, mock_config):
        from providers import github

        client = _make_mock_client()
        mock_create.return_value = client
        client.get.return_value = _mock_response(403, text="Forbidden")

        args = _base_args(
            query="test",
            type="repos",
            sort=None,
            language=None,
            min_stars=None,
            repo=None,
            include_readme=False,
        )

        with pytest.raises(SystemExit):
            github.search(args)


# ===========================================================================
# Reddit
# ===========================================================================

class TestReddit:

    @patch("providers.reddit.create_session")
    def test_global_search(self, mock_create):
        from providers import reddit

        client = _make_mock_client()
        mock_create.return_value = client

        api_response = {
            "data": {
                "children": [{
                    "data": {
                        "id": "abc",
                        "title": "Test Post",
                        "author": "testuser",
                        "subreddit": "test",
                        "score": 42,
                        "upvote_ratio": 0.95,
                        "num_comments": 10,
                        "url": "https://example.com",
                        "permalink": "/r/test/comments/abc/",
                        "selftext": "Test content",
                        "link_flair_text": "Discussion",
                        "created_utc": 1705276800,
                    }
                }],
                "after": None,
            }
        }

        client.get.return_value = _mock_response(200, api_response)

        args = _base_args(
            query="test",
            subreddits=None,
            sort="relevance",
            time="year",
            browse=None,
            post_url=None,
            post_id=None,
            comment_limit=20,
        )
        result = _parse_output(reddit.search(args))

        assert result["status"] == "ok"
        assert len(result["results"]) == 1

        post = result["results"][0]
        assert post["id"] == "abc"
        assert post["title"] == "Test Post"
        assert post["score"] == 42
        assert post["subreddit"] == "test"

    @patch("providers.reddit.create_session")
    def test_search_api_error(self, mock_create):
        from providers import reddit

        client = _make_mock_client()
        mock_create.return_value = client
        client.get.return_value = _mock_response(503, text="Service Unavailable")

        args = _base_args(
            query="test",
            subreddits=None,
            sort="relevance",
            time="year",
            browse=None,
            post_url=None,
            post_id=None,
            comment_limit=20,
        )

        with pytest.raises(SystemExit):
            reddit.search(args)

    @patch("providers.reddit.create_session")
    def test_no_results(self, mock_create):
        from providers import reddit

        client = _make_mock_client()
        mock_create.return_value = client

        api_response = {"data": {"children": [], "after": None}}
        client.get.return_value = _mock_response(200, api_response)

        args = _base_args(
            query="xyznonexistent",
            subreddits=None,
            sort="relevance",
            time="year",
            browse=None,
            post_url=None,
            post_id=None,
            comment_limit=20,
        )
        result = _parse_output(reddit.search(args))

        assert result["status"] == "ok"
        assert result["results"] == []
        assert result["has_more"] is False


# ===========================================================================
# Hacker News
# ===========================================================================

class TestHackerNews:

    @patch("providers.hn.create_session")
    def test_search_stories(self, mock_create):
        from providers import hn

        client = _make_mock_client()
        mock_create.return_value = client

        api_response = {
            "hits": [{
                "objectID": "123",
                "title": "Test HN Story",
                "author": "testuser",
                "url": "https://example.com",
                "points": 100,
                "num_comments": 50,
                "created_at_i": 1705276800,
                "created_at": "2024-01-15T00:00:00Z",
                "story_text": None,
            }],
            "nbHits": 1,
            "nbPages": 1,
            "page": 0,
        }

        client.get.return_value = _mock_response(200, api_response)

        args = _base_args(
            query="test",
            type="story",
            sort="relevance",
            days=None,
            tags=None,
            story_id=None,
            comment_limit=30,
        )
        result = _parse_output(hn.search(args))

        assert result["status"] == "ok"
        assert result["total_results"] == 1
        assert len(result["results"]) == 1

        story = result["results"][0]
        assert story["id"] == "123"
        assert story["title"] == "Test HN Story"
        assert story["points"] == 100
        assert story["hn_url"] == "https://news.ycombinator.com/item?id=123"

    @patch("providers.hn.create_session")
    def test_api_error(self, mock_create):
        from providers import hn

        client = _make_mock_client()
        mock_create.return_value = client
        client.get.return_value = _mock_response(500, text="Internal Error")

        args = _base_args(
            query="test",
            type="story",
            sort="relevance",
            days=None,
            tags=None,
            story_id=None,
            comment_limit=30,
        )

        with pytest.raises(SystemExit):
            hn.search(args)

    @patch("providers.hn.create_session")
    def test_pagination_has_more(self, mock_create):
        from providers import hn

        client = _make_mock_client()
        mock_create.return_value = client

        api_response = {
            "hits": [{
                "objectID": "456",
                "title": "Page 1 Story",
                "author": "user",
                "url": "",
                "points": 10,
                "num_comments": 2,
                "created_at_i": 1705276800,
                "created_at": "2024-01-15T00:00:00Z",
                "story_text": None,
            }],
            "nbHits": 100,
            "nbPages": 10,
            "page": 0,
        }

        client.get.return_value = _mock_response(200, api_response)

        args = _base_args(
            query="test",
            type="story",
            sort="relevance",
            days=None,
            tags=None,
            story_id=None,
            comment_limit=30,
        )
        result = _parse_output(hn.search(args))

        assert result["status"] == "ok"
        assert result["has_more"] is True
        assert result["total_results"] == 100


# ===========================================================================
# OpenCitations
# ===========================================================================

class TestOpenCitations:

    @patch("providers.opencitations.create_session")
    def test_forward_citations(self, mock_create):
        from providers import opencitations

        client = _make_mock_client()
        mock_create.return_value = client

        # Index API returns citation edges
        index_response = [
            {
                "oci": "062104250928-062203214404",
                "citing": "omid:br/062104250928 doi:10.5753/compbr.2022.47.4405",
                "cited": "omid:br/062203214404 doi:10.1145/3442188.3445922",
                "creation": "2022-07-01",
                "timespan": "P1Y4M",
                "journal_sc": "no",
                "author_sc": "no",
            },
        ]

        # Meta API returns metadata for the citing paper
        meta_response = [
            {
                "id": "omid:br/062104250928 doi:10.5753/compbr.2022.47.4405",
                "title": "Test Paper",
                "author": "Souza, Marlo",
                "pub_date": "2022-07-01",
                "venue": "Computação Brasil [issn:2965-9728 omid:br/062104250997]",
                "volume": "47",
                "issue": "",
                "page": "",
                "type": "journal article",
                "publisher": "SBC",
                "citation_count": "3",
            },
        ]

        client.get.side_effect = [
            _mock_response(200, index_response),
            _mock_response(200, meta_response),
        ]

        args = _base_args(
            query=None,
            cited_by="10.1145/3442188.3445922",
            references=None,
        )
        result = _parse_output(opencitations.search(args))

        assert result["status"] == "ok"
        assert result["total_results"] == 1
        assert result["mode"] == "citations"
        assert len(result["results"]) == 1

        paper = result["results"][0]
        assert paper["title"] == "Test Paper"
        assert paper["authors"] == ["Souza, Marlo"]
        assert paper["year"] == 2022
        assert paper["venue"] == "Computação Brasil"
        assert paper["timespan"] == "P1Y4M"
        assert paper["self_citation_journal"] is False
        assert paper["self_citation_author"] is False

    @patch("providers.opencitations.create_session")
    def test_backward_references(self, mock_create):
        from providers import opencitations

        client = _make_mock_client()
        mock_create.return_value = client

        index_response = [
            {
                "oci": "test-oci",
                "citing": "doi:10.1145/3442188.3445922",
                "cited": "doi:10.1145/2207676.2208562",
                "creation": "2021-03-01",
                "timespan": "P9Y",
                "journal_sc": "yes",
                "author_sc": "no",
            },
        ]

        meta_response = [
            {
                "id": "doi:10.1145/2207676.2208562",
                "title": "The Envisioning Cards",
                "author": "Friedman, Batya; Hendry, David",
                "pub_date": "2012",
                "venue": "CHI",
                "type": "conference paper",
            },
        ]

        client.get.side_effect = [
            _mock_response(200, index_response),
            _mock_response(200, meta_response),
        ]

        args = _base_args(
            query=None,
            cited_by=None,
            references="10.1145/3442188.3445922",
        )
        result = _parse_output(opencitations.search(args))

        assert result["status"] == "ok"
        assert result["mode"] == "references"
        assert len(result["results"]) == 1

        paper = result["results"][0]
        assert paper["title"] == "The Envisioning Cards"
        assert paper["authors"] == ["Friedman, Batya", "Hendry, David"]
        assert paper["self_citation_journal"] is True

    @patch("providers.opencitations.create_session")
    def test_keyword_search_returns_error(self, mock_create):
        from providers import opencitations

        client = _make_mock_client()
        mock_create.return_value = client

        args = _base_args(
            query="test",
            cited_by=None,
            references=None,
        )

        with pytest.raises(SystemExit):
            opencitations.search(args)

    @patch("providers.opencitations.create_session")
    def test_no_flags_returns_error(self, mock_create):
        from providers import opencitations

        client = _make_mock_client()
        mock_create.return_value = client

        args = _base_args(
            query=None,
            cited_by=None,
            references=None,
        )

        with pytest.raises(SystemExit):
            opencitations.search(args)

    @patch("providers.opencitations.create_session")
    def test_404_returns_not_found(self, mock_create):
        from providers import opencitations

        client = _make_mock_client()
        mock_create.return_value = client
        client.get.return_value = _mock_response(404, text="Not found")

        args = _base_args(
            query=None,
            cited_by="10.9999/nonexistent",
            references=None,
        )

        with pytest.raises(SystemExit):
            opencitations.search(args)

    @patch("providers.opencitations.create_session")
    def test_meta_api_failure_falls_back_to_minimal_records(self, mock_create):
        from providers import opencitations

        client = _make_mock_client()
        mock_create.return_value = client

        index_response = [
            {
                "citing": "doi:10.1234/citing",
                "cited": "doi:10.1234/cited",
                "timespan": "P2Y",
                "journal_sc": "no",
                "author_sc": "no",
            },
        ]

        client.get.side_effect = [
            _mock_response(200, index_response),
            _mock_response(500, text="Server Error"),  # Meta API fails
        ]

        args = _base_args(
            query=None,
            cited_by="10.1234/cited",
            references=None,
        )
        result = _parse_output(opencitations.search(args))

        assert result["status"] == "ok"
        assert len(result["results"]) == 1
        # Should still have DOI and edge metadata even without meta
        paper = result["results"][0]
        assert paper["doi"] == "10.1234/citing"
        assert paper["timespan"] == "P2Y"


# ===========================================================================
# DBLP
# ===========================================================================

class TestDBLP:

    @patch("providers.dblp.create_session")
    def test_publication_search(self, mock_create):
        from providers import dblp

        client = _make_mock_client()
        mock_create.return_value = client

        api_response = {
            "result": {
                "query": "anomaly detection",
                "status": {"@code": "200", "text": "OK"},
                "hits": {
                    "@total": "1",
                    "@computed": "1",
                    "@sent": "1",
                    "hit": [{
                        "@score": "5",
                        "@id": "123",
                        "info": {
                            "authors": {
                                "author": [
                                    {"@pid": "1", "text": "Alice Smith"},
                                    {"@pid": "2", "text": "Bob Jones"},
                                ]
                            },
                            "title": "Anomaly Detection in Streams.",
                            "venue": "KDD",
                            "pages": "1067-1075",
                            "year": "2017",
                            "type": "Conference and Workshop Papers",
                            "access": "closed",
                            "key": "conf/kdd/test17",
                            "doi": "10.1145/3097983.3098144",
                            "ee": "https://doi.org/10.1145/3097983.3098144",
                            "url": "https://dblp.org/rec/conf/kdd/test17",
                        },
                    }],
                },
            }
        }

        client.get.return_value = _mock_response(200, api_response)

        args = _base_args(
            query="anomaly detection",
            author=None,
            venue=None,
            year_range=None,
            pub_type=None,
        )
        result = _parse_output(dblp.search(args))

        assert result["status"] == "ok"
        assert result["total_results"] == 1
        assert len(result["results"]) == 1

        paper = result["results"][0]
        assert paper["title"] == "Anomaly Detection in Streams"  # trailing period stripped
        assert paper["venue"] == "KDD"
        assert paper["year"] == 2017
        assert paper["doi"] == "10.1145/3097983.3098144"
        assert paper["authors"] == ["Smith, Alice", "Jones, Bob"]

    @patch("providers.dblp.create_session")
    def test_author_search(self, mock_create):
        from providers import dblp

        client = _make_mock_client()
        mock_create.return_value = client

        api_response = {
            "result": {
                "hits": {
                    "@total": "1",
                    "hit": [{
                        "info": {
                            "author": "Yoshua Bengio",
                            "url": "https://dblp.org/pid/56/953",
                            "notes": {
                                "note": [
                                    {"@type": "affiliation", "text": "University of Montréal"},
                                    {"@type": "award", "text": "Turing Award"},
                                ]
                            },
                        },
                    }],
                },
            }
        }

        client.get.return_value = _mock_response(200, api_response)

        args = _base_args(
            query=None,
            author="Yoshua Bengio",
            venue=None,
            year_range=None,
            pub_type=None,
        )
        result = _parse_output(dblp.search(args))

        assert result["status"] == "ok"
        assert result["mode"] == "author_search"
        assert len(result["results"]) == 1

        author = result["results"][0]
        assert author["name"] == "Yoshua Bengio"
        assert author["notes"]["affiliation"] == "University of Montréal"
        assert author["notes"]["award"] == "Turing Award"

    @patch("providers.dblp.create_session")
    def test_venue_search(self, mock_create):
        from providers import dblp

        client = _make_mock_client()
        mock_create.return_value = client

        api_response = {
            "result": {
                "hits": {
                    "@total": "1",
                    "hit": [{
                        "info": {
                            "venue": "Conference on Neural Information Processing Systems (NeurIPS)",
                            "acronym": "NeurIPS",
                            "type": "Conference or Workshop",
                            "url": "https://dblp.org/db/conf/nips/",
                        },
                    }],
                },
            }
        }

        client.get.return_value = _mock_response(200, api_response)

        args = _base_args(
            query=None,
            author=None,
            venue="NeurIPS",
            year_range=None,
            pub_type=None,
        )
        result = _parse_output(dblp.search(args))

        assert result["status"] == "ok"
        assert result["mode"] == "venue_search"
        assert len(result["results"]) == 1

        venue = result["results"][0]
        assert venue["acronym"] == "NeurIPS"
        assert venue["type"] == "Conference or Workshop"

    @patch("providers.dblp.create_session")
    def test_no_flags_returns_error(self, mock_create):
        from providers import dblp

        client = _make_mock_client()
        mock_create.return_value = client

        args = _base_args(
            query=None,
            author=None,
            venue=None,
            year_range=None,
            pub_type=None,
        )

        with pytest.raises(SystemExit):
            dblp.search(args)

    @patch("providers.dblp.create_session")
    def test_mirror_failover(self, mock_create):
        """When primary returns 500, falls back to Trier mirror."""
        from providers import dblp

        client = _make_mock_client()
        mock_create.return_value = client

        ok_response = {
            "result": {
                "hits": {
                    "@total": "1",
                    "hit": [{
                        "info": {
                            "authors": {"author": {"text": "Solo Author"}},
                            "title": "Mirror Paper.",
                            "venue": "ICML",
                            "year": "2024",
                        },
                    }],
                },
            }
        }

        # First call (primary) returns 500, second call (mirror) succeeds
        client.get.side_effect = [
            _mock_response(500, text="Server Error"),
            _mock_response(200, ok_response),
        ]

        args = _base_args(
            query="test",
            author=None,
            venue=None,
            year_range=None,
            pub_type=None,
        )
        result = _parse_output(dblp.search(args))

        assert result["status"] == "ok"
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Mirror Paper"
        # Two GET calls: primary failed, mirror succeeded
        assert client.get.call_count == 2

    @patch("providers.dblp.create_session")
    def test_single_author_dict_format(self, mock_create):
        """DBLP returns a dict (not list) when there's only one author."""
        from providers import dblp

        client = _make_mock_client()
        mock_create.return_value = client

        api_response = {
            "result": {
                "hits": {
                    "@total": "1",
                    "hit": [{
                        "info": {
                            "authors": {"author": {"text": "Solo Author"}},
                            "title": "Single Author Paper.",
                            "venue": "AAAI",
                            "year": "2024",
                        },
                    }],
                },
            }
        }

        client.get.return_value = _mock_response(200, api_response)

        args = _base_args(
            query="test",
            author=None,
            venue=None,
            year_range=None,
            pub_type=None,
        )
        result = _parse_output(dblp.search(args))

        assert result["status"] == "ok"
        paper = result["results"][0]
        assert paper["authors"] == ["Author, Solo"]
