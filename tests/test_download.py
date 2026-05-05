"""Tests for download helper routing and state-backed source IDs."""

import os
import sqlite3

from download import (
    _auto_create_web_source,
    _clinicaltrials_api_url,
    _pmc_article_url_from_pdf_url,
)
from helpers import init_session as _init_session


def test_clinicaltrials_study_url_rewrites_to_api():
    url = "https://clinicaltrials.gov/study/NCT01870193"
    assert _clinicaltrials_api_url(url) == "https://clinicaltrials.gov/api/v2/studies/NCT01870193"


def test_pmc_pdf_url_converts_to_html_for_both_hosts():
    assert (
        _pmc_article_url_from_pdf_url("https://pmc.ncbi.nlm.nih.gov/articles/PMC123456/pdf/")
        == "https://pmc.ncbi.nlm.nih.gov/articles/PMC123456/"
    )
    assert (
        _pmc_article_url_from_pdf_url("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC123456/pdf/")
        == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC123456/"
    )


def test_auto_create_web_source_returns_canonical_state_id(tmp_path):
    session_dir = str(tmp_path / "session")
    _init_session(session_dir)
    url = "https://clinicaltrials.gov/study/NCT01870193"
    meta = {"title": "Clinical trial record", "year": 2013}

    first_id = _auto_create_web_source(session_dir, url, meta)
    second_id = _auto_create_web_source(session_dir, url, meta)

    assert first_id == "src-001"
    assert second_id == "src-001"

    conn = sqlite3.connect(os.path.join(session_dir, "state.db"))
    count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    conn.close()
    assert count == 1
