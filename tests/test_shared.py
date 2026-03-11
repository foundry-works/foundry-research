"""Tests for shared modules: config.py, html_extract.py, pdf_utils.py."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from _shared.config import get_config, get_session_dir, _GLOBAL_CONFIG_PATH, _DEFAULT_CONFIG, _ENV_KEYS
from _shared.html_extract import html_to_text, extract_readable_content, strip_jats_xml
from _shared.pdf_utils import validate_pdf, download_pdf, generate_toc


# ---------------------------------------------------------------------------
# config.py
# ---------------------------------------------------------------------------

class TestConfig:
    def test_default_config_all_none(self, tmp_path):
        """get_config() with no env vars or files returns dict with all known keys set to None."""
        # Patch global config to a non-existent path and clear env vars
        fake_global = tmp_path / "nonexistent" / "config.json"
        env_clear = {v: "" for v in _ENV_KEYS.values()}
        with patch("_shared.config._GLOBAL_CONFIG_PATH", fake_global), \
             patch.dict(os.environ, env_clear, clear=False):
            # Remove env vars entirely (empty string won't override due to `if value:`)
            for v in _ENV_KEYS.values():
                os.environ.pop(v, None)
            cfg = get_config()

        for key in _DEFAULT_CONFIG:
            assert key in cfg
            assert cfg[key] is None, f"Expected {key} to be None, got {cfg[key]}"

    def test_env_var_override(self, tmp_path):
        """Setting SEMANTIC_SCHOLAR_API_KEY env var is returned by get_config()."""
        fake_global = tmp_path / "nonexistent" / "config.json"
        with patch("_shared.config._GLOBAL_CONFIG_PATH", fake_global), \
             patch.dict(os.environ, {"SEMANTIC_SCHOLAR_API_KEY": "test-key-123"}):
            cfg = get_config()

        assert cfg["semantic_scholar_api_key"] == "test-key-123"

    def test_global_config_file(self, tmp_path):
        """Global config file values are loaded correctly."""
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"openalex_api_key": "from-global-file"}))

        with patch("_shared.config._GLOBAL_CONFIG_PATH", config_file):
            # Clear the env var so it doesn't override
            env_clear = {v: "" for v in _ENV_KEYS.values()}
            with patch.dict(os.environ, env_clear, clear=False):
                for v in _ENV_KEYS.values():
                    os.environ.pop(v, None)
                cfg = get_config()

        assert cfg["openalex_api_key"] == "from-global-file"

    def test_session_dir_config(self, tmp_path):
        """Session-dir local .config.json is loaded."""
        session_config = tmp_path / ".config.json"
        session_config.write_text(json.dumps({"unpaywall_email": "user@example.com"}))

        fake_global = tmp_path / "nonexistent" / "config.json"
        with patch("_shared.config._GLOBAL_CONFIG_PATH", fake_global):
            env_clear = {v: "" for v in _ENV_KEYS.values()}
            with patch.dict(os.environ, env_clear, clear=False):
                for v in _ENV_KEYS.values():
                    os.environ.pop(v, None)
                cfg = get_config(session_dir=str(tmp_path))

        assert cfg["unpaywall_email"] == "user@example.com"

    def test_env_var_has_highest_priority(self, tmp_path):
        """Env var takes priority over both global and session config files."""
        # Set up global config
        global_config = tmp_path / "global_config.json"
        global_config.write_text(json.dumps({"semantic_scholar_api_key": "from-global"}))

        # Set up session config
        session_dir = tmp_path / "session"
        session_dir.mkdir()
        (session_dir / ".config.json").write_text(
            json.dumps({"semantic_scholar_api_key": "from-session"})
        )

        with patch("_shared.config._GLOBAL_CONFIG_PATH", global_config), \
             patch.dict(os.environ, {"SEMANTIC_SCHOLAR_API_KEY": "from-env"}):
            cfg = get_config(session_dir=str(session_dir))

        assert cfg["semantic_scholar_api_key"] == "from-env"

    def test_get_session_dir_from_args(self, tmp_path):
        """get_session_dir creates directory with sources/metadata subdirs."""
        session_path = tmp_path / "my_session"
        args = SimpleNamespace(session_dir=str(session_path))

        result = get_session_dir(args)

        assert result == str(session_path.resolve())
        assert (session_path / "sources" / "metadata").is_dir()

    @patch("_shared.config._discover_session_dir_from_marker", return_value=None)
    def test_get_session_dir_missing_exits(self, mock_discover):
        """Missing session_dir arg, no env var, and no marker file causes SystemExit."""
        args = SimpleNamespace()  # No session_dir attribute

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEEP_RESEARCH_SESSION_DIR", None)
            with pytest.raises(SystemExit):
                get_session_dir(args)


# ---------------------------------------------------------------------------
# html_extract.py
# ---------------------------------------------------------------------------

class TestHtmlExtract:
    def test_html_to_text_strips_tags(self):
        """Basic HTML tags are stripped, leaving readable text."""
        result = html_to_text("<p>Hello <b>world</b></p>")
        assert "Hello" in result
        assert "world" in result
        assert "<" not in result

    def test_html_to_text_removes_script(self):
        """Script tags and their contents are removed."""
        result = html_to_text("<p>hi</p><script>alert(1)</script>")
        assert "hi" in result
        assert "alert" not in result
        assert "script" not in result

    def test_extract_readable_content_finds_article(self):
        """extract_readable_content extracts article content, dropping nav."""
        html = "<html><body><nav>nav</nav><article>content</article></body></html>"
        result = extract_readable_content(html)
        assert "content" in result
        assert "nav" not in result

    def test_strip_jats_xml(self):
        """JATS XML tags are stripped from academic abstract text."""
        result = strip_jats_xml("<jats:p>text <jats:italic>italic</jats:italic></jats:p>")
        assert result == "text italic"

    def test_html_to_text_empty_input(self):
        """Empty string input returns empty string."""
        assert html_to_text("") == ""


# ---------------------------------------------------------------------------
# pdf_utils.py
# ---------------------------------------------------------------------------

class TestPdfUtils:
    def test_validate_pdf_valid(self, tmp_path):
        """File starting with %PDF magic bytes and >= 64 bytes is valid."""
        pdf_file = tmp_path / "valid.pdf"
        pdf_file.write_bytes(b"%PDF-1.4" + b"\x00" * 60)
        assert validate_pdf(str(pdf_file)) is True

    def test_validate_pdf_invalid(self, tmp_path):
        """File without PDF magic bytes is invalid."""
        pdf_file = tmp_path / "fake.pdf"
        pdf_file.write_bytes(b"<html>not a pdf</html>" + b"\x00" * 50)
        assert validate_pdf(str(pdf_file)) is False

    def test_validate_pdf_too_small(self, tmp_path):
        """File with PDF magic but < 64 bytes is invalid (truncated)."""
        pdf_file = tmp_path / "tiny.pdf"
        pdf_file.write_bytes(b"%PDF")
        assert validate_pdf(str(pdf_file)) is False

    def test_download_pdf_success(self, tmp_path):
        """Successful PDF download returns success with size."""
        dest = str(tmp_path / "paper.pdf")
        pdf_content = b"%PDF-1.4" + b"\x00" * 92

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Length": "100"}
        mock_response.iter_content.return_value = [pdf_content]

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        result = download_pdf("https://example.com/paper.pdf", dest, mock_client)

        assert result["success"] is True
        assert result["size_bytes"] == len(pdf_content)
        assert result["errors"] == []

    def test_download_pdf_html_error_page(self, tmp_path):
        """Server returning HTML instead of PDF is detected as failure."""
        dest = str(tmp_path / "error.pdf")
        html_content = b"<html><body>Access Denied</body></html>" + b"\x00" * 50

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Length": str(len(html_content))}
        mock_response.iter_content.return_value = [html_content]

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        result = download_pdf("https://example.com/paper.pdf", dest, mock_client)

        assert result["success"] is False
        assert any("HTML" in e for e in result["errors"])

    def test_generate_toc(self, tmp_path):
        """generate_toc extracts headings in LINE_NUM<tab>LEVEL<tab>TEXT format."""
        md_file = tmp_path / "doc.md"
        md_file.write_text(
            "# Introduction\n\nSome text here.\n\n## Methods\n\nMore text.\n\n### Subsection\n",
            encoding="utf-8",
        )
        toc_file = str(tmp_path / "doc.toc")

        result = generate_toc(str(md_file), toc_file)

        assert result["headings"] == 3
        assert result["toc_file"] == toc_file

        toc_content = Path(toc_file).read_text(encoding="utf-8")
        lines = toc_content.strip().splitlines()
        assert len(lines) == 3

        # First heading: line 1, level 1, "Introduction"
        parts = lines[0].split("\t")
        assert parts == ["1", "1", "Introduction"]

        # Second heading: line 5, level 2, "Methods"
        parts = lines[1].split("\t")
        assert parts == ["5", "2", "Methods"]

        # Third heading: line 7, level 3, "Subsection"  (corrected after content)
        parts = lines[2].split("\t")
        assert parts[1] == "3"
        assert parts[2] == "Subsection"
