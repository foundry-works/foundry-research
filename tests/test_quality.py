"""Tests for _shared/quality.py — assess_quality and check_content_mismatch."""

from _shared.quality import assess_quality, check_content_mismatch


# ---------------------------------------------------------------------------
# check_content_mismatch
# ---------------------------------------------------------------------------

class TestCheckContentMismatch:
    """Verify mismatch detection catches gross metadata-content disagreements."""

    def test_matching_content(self):
        """Content that contains title words and author names → not mismatched."""
        text = (
            "The Infant Behavior Questionnaire–Revised (IBQ-R) is a caregiver-report "
            "temperament measure developed by Rothbart and colleagues. This study examines "
            "the psychometric properties of the short form across multiple samples."
        )
        result = check_content_mismatch(
            text,
            title="Infant Behavior Questionnaire-Revised Short Form",
            authors=["Rothbart, Mary K.", "Putnam, Samuel P."],
        )
        assert not result["mismatched"]
        assert result["title_hits"] > 0

    def test_completely_wrong_content(self):
        """Content from a totally different paper → mismatched."""
        text = (
            "Inflammatory bowel disease (IBD) is a chronic condition affecting the "
            "gastrointestinal tract. This review examines thrombosis risk factors in "
            "patients with ulcerative colitis and Crohn's disease. Methods: We conducted "
            "a systematic review of randomized controlled trials published between 2010-2020."
        )
        result = check_content_mismatch(
            text,
            title="Multi-informant validity of temperament measures in preschoolers",
            authors=["Goldsmith, H. Hill", "Lemery-Chalfant, Kathryn"],
        )
        assert result["mismatched"]
        assert result["title_hits"] == 0
        assert result["author_hits"] == 0
        assert "wrong paper" in result["reason"]

    def test_italian_conference_proceedings(self):
        """Simulates src-051: declared IBQ-R short forms but content is Italian proceedings."""
        text = (
            "Atti del Convegno Nazionale di Psicologia dello Sviluppo. Sessione poster: "
            "sviluppo cognitivo e linguistico nei bambini prescolari. Università di Bologna, "
            "settembre 2019. Programma e riassunti delle comunicazioni scientifiche."
        )
        result = check_content_mismatch(
            text,
            title="Development of the IBQ-R Short Form: Psychometric Evaluation",
            authors=["Putnam, Samuel P.", "Helbig, Amy L."],
        )
        assert result["mismatched"]

    def test_no_metadata(self):
        """No title or authors → cannot check, returns not mismatched."""
        result = check_content_mismatch("Some random content", title="", authors=None)
        assert not result["mismatched"]

    def test_empty_text(self):
        """Empty content → not mismatched (nothing to check against)."""
        result = check_content_mismatch("", title="Some Paper Title", authors=["Smith, John"])
        assert not result["mismatched"]

    def test_title_match_no_authors(self):
        """Title words match but no author info → not mismatched."""
        text = "This study of temperament measurement in preschool children uses CBQ."
        result = check_content_mismatch(
            text,
            title="Temperament measurement in preschool children",
            authors=None,
        )
        assert not result["mismatched"]
        assert result["title_hits"] >= 2

    def test_author_match_no_title_keywords(self):
        """Author names match but title has only stopwords → not mismatched."""
        text = "Rothbart and Derryberry proposed a model of self-regulation based on temperament."
        result = check_content_mismatch(
            text,
            title="The",  # only stopword, no meaningful keywords
            authors=["Rothbart, Mary K."],
        )
        assert not result["mismatched"]

    def test_partial_title_match_with_author(self):
        """Some title words match + author match → not mismatched."""
        text = (
            "Rothbart developed the Children's Behavior Questionnaire to assess "
            "reactive and self-regulative dimensions of temperament."
        )
        result = check_content_mismatch(
            text,
            title="Children's Behavior Questionnaire: A measure of temperament",
            authors=["Rothbart, Mary K."],
        )
        assert not result["mismatched"]


# ---------------------------------------------------------------------------
# assess_quality
# ---------------------------------------------------------------------------

class TestAssessQuality:
    def test_good_content(self):
        """Well-formed academic text → ok."""
        text = (
            "This paper examines the psychometric properties of a temperament questionnaire. "
            "We collected data from 500 participants across three age groups. Results indicate "
            "strong internal consistency (alpha > 0.85) and test-retest reliability over a "
            "six-month interval. Factor analysis confirmed the expected three-factor structure "
            "corresponding to surgency, negative affectivity, and effortful control. "
            "These findings support the use of this instrument in developmental research. "
            "Convergent validity was demonstrated through correlations with observational "
            "measures of child behavior in laboratory settings. Discriminant validity was "
            "supported by low correlations with unrelated constructs such as cognitive ability."
        )
        result = assess_quality(text)
        assert result["quality"] == "ok"

    def test_empty_content(self):
        """Empty string → empty."""
        result = assess_quality("")
        assert result["quality"] == "empty"

    def test_none_content(self):
        """None → empty."""
        result = assess_quality(None)
        assert result["quality"] == "empty"

    def test_very_short_content(self):
        """Very short text → degraded or empty."""
        result = assess_quality("Access denied.")
        assert result["quality"] in ("degraded", "empty")

    def test_html_warning_only(self):
        """Content with only HTML warning comments → empty."""
        result = assess_quality("<!-- WARNING: paywall detected -->")
        assert result["quality"] == "empty"
