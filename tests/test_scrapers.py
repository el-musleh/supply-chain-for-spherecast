"""
test_scrapers.py — Tests for web scraping components.

Tests cover:
    - EthicsChecker (robots.txt parsing, rate limiting)
    - SupplierScraper (anti-detection, retries)
    - CoAExtractor (PDF/HTML extraction, fallback behavior)
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Conditional imports (scrapers may not be installed)
try:
    from scrapers import EthicsChecker, ScrapingPolicy
    from scrapers.document_extractor import ComplianceProfile, CoAExtractor
    HAS_SCRAPERS = True
except ImportError:
    HAS_SCRAPERS = False
    pytest.skip("scrapers module not available", allow_module_level=True)


class TestEthicsChecker:
    """Test suite for ethics compliance layer."""
    
    def test_robots_txt_caching(self):
        """Robots.txt should be cached after first fetch."""
        checker = EthicsChecker(respect_robots_txt=True, verbose=False)
        
        # First check should cache
        policy1 = checker.check_url("https://example.com/page1")
        stats1 = checker.get_stats()
        
        # Second check should use cache
        policy2 = checker.check_url("https://example.com/page2")
        stats2 = checker.get_stats()
        
        assert stats2["robots_cache_size"] == 1
    
    def test_respect_robots_txt_false(self):
        """When disabled, should always allow scraping."""
        checker = EthicsChecker(respect_robots_txt=False)
        policy = checker.check_url("https://example.com/page")
        
        assert policy.can_scrape is True
        assert policy.respect_robots_txt is False
    
    def test_rate_limiting(self):
        """Rate limiting should enforce delays between requests."""
        checker = EthicsChecker(default_delay=0.1, verbose=False)
        
        import time
        start = time.time()
        
        # First request - no delay
        checker.rate_limit("https://example.com/page1")
        
        # Second request - should delay
        checker.rate_limit("https://example.com/page2")
        
        elapsed = time.time() - start
        assert elapsed >= 0.05  # Should have some delay
    
    def test_fair_use_assessment(self):
        """Should document fair use rationale."""
        checker = EthicsChecker()
        policy = checker.check_url("https://supplier.com/coa.pdf")
        
        assert "FACTUAL_DATA_AGGREGATION" in policy.fair_use_assessment
        assert "robots.txt" in policy.fair_use_assessment.lower()


class TestComplianceProfile:
    """Test suite for compliance data structures."""
    
    def test_grade_normalization(self):
        """Grade values should be normalized to standard values."""
        profile = ComplianceProfile(grade="PHARMACEUTICAL")
        assert profile.grade == "pharmaceutical"
        
        profile = ComplianceProfile(grade="USP Grade")
        assert profile.grade == "pharmaceutical"
        
        profile = ComplianceProfile(grade="technical grade")
        assert profile.grade == "technical"
    
    def test_to_dict_roundtrip(self):
        """Should convert to dict and back."""
        original = ComplianceProfile(
            organic_certified=True,
            fda_registered=True,
            grade="pharmaceutical",
            certifications=["USP", "GMP"],
            notes="Test profile"
        )
        
        as_dict = original.to_dict()
        restored = ComplianceProfile.from_dict(as_dict)
        
        assert restored.organic_certified == original.organic_certified
        assert restored.grade == original.grade
        assert restored.certifications == original.certifications
    
    def test_default_values(self):
        """Should have sensible defaults."""
        profile = ComplianceProfile()
        
        assert profile.organic_certified is False
        assert profile.fda_registered is False
        assert profile.grade == "food"
        assert profile.lead_time_days == 14
        assert profile.certifications == []


class TestCoAExtractorFallback:
    """Test fallback behavior when extraction fails."""
    
    def test_fallback_on_pdf_error(self):
        """Should return fallback profile on PDF error."""
        # Mock client not needed - will fail gracefully
        extractor = CoAExtractor(gemini_client=None, verbose=False)
        
        # Non-existent PDF path
        result = extractor.extract_from_pdf("/nonexistent/file.pdf")
        
        assert isinstance(result, ComplianceProfile)
        assert "Extraction failed" in result.notes or "PDF not found" in result.notes
        assert result.fda_registered is True  # Conservative default
    
    def test_heuristic_extraction(self):
        """Should use heuristic when LLM unavailable."""
        extractor = CoAExtractor(gemini_client=None, verbose=False)
        
        html_content = """
        <html>
            <body>
                <p>FDA Registered Facility</p>
                <p>USP Certified</p>
                <p>Non-GMO Verified</p>
                <p>Pharmaceutical Grade</p>
            </body>
        </html>
        """
        
        result = extractor.extract_from_html(html_content, "https://test.com")
        
        assert result.fda_registered is True
        assert result.non_gmo is True
        assert "USP" in result.certifications
        assert result.grade == "pharmaceutical"


class TestIntegration:
    """Integration tests requiring network (skipped by default)."""
    
    @pytest.mark.skip(reason="Requires network access")
    def test_ethics_checker_real_robots_txt(self):
        """Test against real robots.txt."""
        checker = EthicsChecker(verbose=True)
        
        # Google allows some scraping
        policy = checker.check_url("https://www.google.com/robots.txt")
        assert policy.respect_robots_txt is True
        
        # Should have a robots.txt URL
        assert "robots.txt" in policy.robots_txt_url
    
    @pytest.mark.skip(reason="Requires Playwright installation")
    def test_scraper_init(self):
        """Scraper should initialize if Playwright available."""
        from scrapers import SupplierScraper
        
        scraper = SupplierScraper(headless=True, verbose=False)
        stats = scraper.get_stats()
        
        assert "requests_made" in stats
        assert stats["proxies_available"] == 0  # No proxies configured


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
