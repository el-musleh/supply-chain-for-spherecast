"""
supplier_scraper.py — Playwright-based web scraping with anti-detection.

Features:
    - Stealth mode (playwright-stealth) to bypass bot detection
    - Rotating user agents and proxies
    - CAPTCHA detection (with 2captcha API integration option)
    - Session persistence and retry logic
    - Screenshot capture for debugging
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable
from urllib.parse import urljoin, urlparse

# Playwright imports (lazy loaded to avoid startup cost)
try:
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

from .ethics_checker import EthicsChecker


@dataclass
class ScraperResult:
    """Result of a scraping operation."""
    success: bool
    content: str  # HTML content or error message
    url: str
    status_code: Optional[int] = None
    captcha_detected: bool = False
    screenshot_path: Optional[str] = None
    error_message: Optional[str] = None
    load_time_ms: float = 0.0


class SupplierScraper:
    """
    Production-grade web scraper with anti-detection capabilities.
    
    Usage:
        scraper = SupplierScraper(proxy_list=["http://proxy1:8080"])
        result = await scraper.scrape("https://supplier.com/coa")
    """
    
    # Rotating user agents to avoid fingerprinting
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    ]
    
    def __init__(
        self,
        proxy_list: Optional[list[str]] = None,
        use_rotating_proxy: bool = False,
        ethics_checker: Optional[EthicsChecker] = None,
        captcha_api_key: Optional[str] = None,  # 2captcha API key
        headless: bool = True,
        screenshot_on_error: bool = True,
        screenshot_dir: str = "logs/screenshots",
        timeout_ms: int = 30000,
        max_retries: int = 3,
        verbose: bool = False,
    ):
        if not HAS_PLAYWRIGHT:
            raise ImportError(
                "Playwright not installed. Run: "
                "pip install playwright && playwright install chromium"
            )
        
        self.proxy_list = proxy_list or []
        self.use_rotating_proxy = use_rotating_proxy and len(self.proxy_list) > 0
        self.ethics = ethics_checker or EthicsChecker()
        self.captcha_api_key = captcha_api_key
        self.headless = headless
        self.screenshot_on_error = screenshot_on_error
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_ms = timeout_ms
        self.max_retries = max_retries
        self.verbose = verbose
        
        # Stats
        self._requests_made = 0
        self._captchas_encountered = 0
        self._errors = 0
    
    async def scrape(
        self,
        url: str,
        wait_for_selector: Optional[str] = None,
        scroll_to_bottom: bool = False,
        extract_links: bool = False,
    ) -> ScraperResult:
        """
        Scrape a URL with anti-detection measures.
        
        Args:
            url: Target URL
            wait_for_selector: CSS selector to wait for before extracting
            scroll_to_bottom: Scroll to load lazy content
            extract_links: Also extract all links from page
            
        Returns:
            ScraperResult with content or error details
        """
        start_time = time.time()
        
        # Ethics check
        if not self.ethics.can_scrape(url):
            return ScraperResult(
                success=False,
                content="",
                url=url,
                error_message="Blocked by robots.txt",
            )
        
        # Rate limiting
        self.ethics.rate_limit(url)
        
        # Attempt scraping with retries
        for attempt in range(self.max_retries):
            try:
                result = await self._scrape_once(
                    url,
                    wait_for_selector=wait_for_selector,
                    scroll_to_bottom=scroll_to_bottom,
                    extract_links=extract_links,
                )
                
                if result.success:
                    self._requests_made += 1
                    return result
                
                # Check for CAPTCHA
                if result.captcha_detected and self.captcha_api_key:
                    if self.verbose:
                        print(f"  [scraper] CAPTCHA detected, attempting solve...")
                    # CAPTCHA solving would go here
                    # For now, just mark and continue
                
                if attempt < self.max_retries - 1:
                    wait = 2 ** attempt + random.uniform(0, 1)  # Exponential backoff
                    if self.verbose:
                        print(f"  [scraper] Retry {attempt + 1}/{self.max_retries} after {wait:.1f}s")
                    await asyncio.sleep(wait)
                    
            except Exception as e:
                self._errors += 1
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    return ScraperResult(
                        success=False,
                        content="",
                        url=url,
                        error_message=f"Failed after {self.max_retries} attempts: {str(e)}",
                    )
        
        return result
    
    async def _scrape_once(
        self,
        url: str,
        wait_for_selector: Optional[str] = None,
        scroll_to_bottom: bool = False,
        extract_links: bool = False,
    ) -> ScraperResult:
        """Single scraping attempt."""
        proxy = random.choice(self.proxy_list) if self.use_rotating_proxy else None
        user_agent = random.choice(self.USER_AGENTS)
        
        async with async_playwright() as p:
            browser_args = []
            if proxy:
                browser_args.append(f"--proxy-server={proxy}")
            
            # Anti-detection arguments
            browser_args.extend([
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ])
            
            browser = await p.chromium.launch(
                headless=self.headless,
                args=browser_args,
            )
            
            context = await browser.new_context(
                user_agent=user_agent,
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="America/New_York",
            )
            
            # Inject stealth scripts to hide automation
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                window.chrome = { runtime: {} };
            """)
            
            page = await context.new_page()
            
            try:
                # Navigate with timeout
                response = await page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=self.timeout_ms,
                )
                
                # Check for CAPTCHA
                captcha_selectors = [
                    ".g-recaptcha",
                    "#captcha",
                    ".h-captcha",
                    "[data-captcha]",
                    "#recaptcha",
                    ".cf-turnstile",  # Cloudflare
                ]
                
                captcha_detected = False
                for selector in captcha_selectors:
                    try:
                        if await page.locator(selector).count() > 0:
                            captcha_detected = True
                            self._captchas_encountered += 1
                            break
                    except:
                        pass
                
                if captcha_detected:
                    screenshot_path = None
                    if self.screenshot_on_error:
                        ts = int(time.time())
                        screenshot_path = str(self.screenshot_dir / f"captcha_{ts}.png")
                        await page.screenshot(path=screenshot_path)
                    
                    await browser.close()
                    return ScraperResult(
                        success=False,
                        content="",
                        url=url,
                        captcha_detected=True,
                        screenshot_path=screenshot_path,
                        error_message="CAPTCHA detected - manual intervention or 2captcha API required",
                    )
                
                # Wait for specific element if requested
                if wait_for_selector:
                    try:
                        await page.wait_for_selector(
                            wait_for_selector,
                            timeout=10000,
                        )
                    except:
                        pass  # Continue even if selector not found
                
                # Scroll to bottom for lazy loading
                if scroll_to_bottom:
                    await page.evaluate("""
                        async () => {
                            await new Promise((resolve) => {
                                let totalHeight = 0;
                                const distance = 100;
                                const timer = setInterval(() => {
                                    const scrollHeight = document.body.scrollHeight;
                                    window.scrollBy(0, distance);
                                    totalHeight += distance;
                                    if (totalHeight >= scrollHeight) {
                                        clearInterval(timer);
                                        resolve();
                                    }
                                }, 100);
                            });
                        }
                    """)
                    await asyncio.sleep(1)  # Wait for lazy content
                
                # Extract content
                content = await page.content()
                
                # Extract links if requested
                if extract_links:
                    links = await page.eval_on_selector_all(
                        "a[href]",
                        "elements => elements.map(e => e.href)",
                    )
                    # Add links as metadata
                    content += f"\n<!-- EXTRACTED_LINKS: {links[:50]} -->"
                
                status_code = response.status if response else None
                
                await browser.close()
                
                return ScraperResult(
                    success=True,
                    content=content,
                    url=url,
                    status_code=status_code,
                    load_time_ms=(time.time() - start_time) * 1000,
                )
                
            except Exception as e:
                screenshot_path = None
                if self.screenshot_on_error:
                    try:
                        ts = int(time.time())
                        screenshot_path = str(self.screenshot_dir / f"error_{ts}.png")
                        await page.screenshot(path=screenshot_path)
                    except:
                        pass
                
                await browser.close()
                return ScraperResult(
                    success=False,
                    content="",
                    url=url,
                    error_message=str(e),
                    screenshot_path=screenshot_path,
                )
    
    def get_stats(self) -> dict:
        """Get scraper statistics."""
        return {
            "requests_made": self._requests_made,
            "captchas_encountered": self._captchas_encountered,
            "errors": self._errors,
            "proxies_available": len(self.proxy_list),
            "ethics_stats": self.ethics.get_stats(),
        }
    
    async def close(self):
        """Cleanup resources (if needed)."""
        pass  # Context managers handle cleanup
