"""
ethics_checker.py — Legal and ethical compliance layer for web scraping.

Handles:
    - robots.txt parsing and caching
    - Crawl-delay enforcement
    - Fair use assessment for training data
    - Rate limiting between requests
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from typing import Optional


@dataclass
class ScrapingPolicy:
    """Result of ethics check for a URL."""
    can_scrape: bool
    crawl_delay: float
    respect_robots_txt: bool
    fair_use_assessment: str
    robots_txt_url: str


class EthicsChecker:
    """
    Ensure legal/ethical compliance for web scraping.
    
    Respects robots.txt, enforces crawl delays, and documents
    fair use rationale for training on scraped data.
    """
    
    def __init__(
        self,
        respect_robots_txt: bool = True,
        default_delay: float = 1.0,
        max_delay: float = 30.0,
        verbose: bool = False,
    ):
        self.respect_robots_txt = respect_robots_txt
        self.default_delay = default_delay
        self.max_delay = max_delay
        self.verbose = verbose
        self._robots_cache: dict[str, RobotFileParser] = {}
        self._domain_last_access: dict[str, datetime] = {}
    
    def check_url(self, url: str) -> ScrapingPolicy:
        """
        Check if scraping a URL is allowed and get crawl parameters.
        
        Args:
            url: The URL to check
            
        Returns:
            ScrapingPolicy with can_scrape flag and delay requirements
        """
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        
        if not self.respect_robots_txt:
            return ScrapingPolicy(
                can_scrape=True,
                crawl_delay=self.default_delay,
                respect_robots_txt=False,
                fair_use_assessment=self._assess_fair_use(url),
                robots_txt_url=robots_url,
            )
        
        # Get or create robots.txt parser
        rp = self._get_robots_parser(robots_url)
        
        if rp is None:
            # robots.txt not found or error - assume allowed with caution
            if self.verbose:
                print(f"  [ethics] robots.txt not accessible for {parsed.netloc}")
            return ScrapingPolicy(
                can_scrape=True,
                crawl_delay=self.default_delay,
                respect_robots_txt=True,
                fair_use_assessment=self._assess_fair_use(url),
                robots_txt_url=robots_url,
            )
        
        # Check if user-agent "*" is allowed (we use generic UA)
        can_fetch = rp.can_fetch("*", url)
        
        # Get crawl-delay directive
        crawl_delay = rp.crawl_delay("*")
        if crawl_delay is None:
            crawl_delay = self.default_delay
        else:
            crawl_delay = min(crawl_delay, self.max_delay)  # Cap extreme delays
        
        if self.verbose:
            status = "ALLOWED" if can_fetch else "BLOCKED"
            print(f"  [ethics] {status} by robots.txt for {url}")
        
        return ScrapingPolicy(
            can_scrape=can_fetch,
            crawl_delay=crawl_delay,
            respect_robots_txt=True,
            fair_use_assessment=self._assess_fair_use(url),
            robots_txt_url=robots_url,
        )
    
    def _get_robots_parser(self, robots_url: str) -> Optional[RobotFileParser]:
        """Get cached robots.txt parser or fetch and cache new one."""
        if robots_url in self._robots_cache:
            return self._robots_cache[robots_url]
        
        rp = RobotFileParser()
        rp.set_url(robots_url)
        
        try:
            rp.read()
            self._robots_cache[robots_url] = rp
            return rp
        except Exception as e:
            if self.verbose:
                print(f"  [ethics] Error reading robots.txt: {e}")
            return None
    
    def rate_limit(self, url: str) -> float:
        """
        Enforce rate limiting for a domain. Blocks until delay is satisfied.
        
        Args:
            url: The URL about to be scraped
            
        Returns:
            Actual seconds waited
        """
        parsed = urlparse(url)
        domain = parsed.netloc
        
        # Get required delay from policy
        policy = self.check_url(url)
        required_delay = policy.crawl_delay
        
        # Check last access time
        last_access = self._domain_last_access.get(domain)
        
        if last_access:
            elapsed = (datetime.now() - last_access).total_seconds()
            if elapsed < required_delay:
                sleep_time = required_delay - elapsed
                if self.verbose:
                    print(f"  [ethics] Rate limiting: sleeping {sleep_time:.2f}s for {domain}")
                time.sleep(sleep_time)
                return sleep_time
        
        self._domain_last_access[domain] = datetime.now()
        return 0.0
    
    def _assess_fair_use(self, url: str) -> str:
        """
        Assess fair use implications for training on scraped data.
        
        For Agnes: We extract factual compliance data (certifications,
        grades, lead times) - low creative content, factual information.
        """
        return (
            "FACTUAL_DATA_AGGREGATION: Extracting factual compliance information "
            "(certifications, grades, lead times, regulatory status). "
            "Low creative/transformative content. Recommend: Cite sources, "
            "don't reproduce verbatim text beyond short excerpts, "
            "respect robots.txt, maintain reasonable request rates."
        )
    
    def can_scrape(self, url: str) -> bool:
        """Quick check if URL can be scraped (respecting robots.txt)."""
        policy = self.check_url(url)
        return policy.can_scrape
    
    def get_stats(self) -> dict:
        """Get statistics about the ethics checker's state."""
        return {
            "robots_cache_size": len(self._robots_cache),
            "domains_rate_limited": len(self._domain_last_access),
            "respect_robots_txt": self.respect_robots_txt,
            "default_delay": self.default_delay,
        }
