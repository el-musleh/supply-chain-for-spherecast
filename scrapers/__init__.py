"""
scrapers — Production-ready data sourcing for Agnes.

Modules:
    ethics_checker      — robots.txt compliance and rate limiting
    supplier_scraper    — Playwright-based web scraping with anti-detection
    document_extractor  — PDF/HTML compliance data extraction

Usage:
    from scrapers import SupplierScraper, EthicsChecker, CoAExtractor
"""

from .ethics_checker import EthicsChecker, ScrapingPolicy
from .supplier_scraper import SupplierScraper
from .document_extractor import CoAExtractor, ComplianceProfile

__all__ = [
    "EthicsChecker",
    "ScrapingPolicy",
    "SupplierScraper",
    "CoAExtractor",
    "ComplianceProfile",
]
