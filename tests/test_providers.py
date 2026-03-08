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
