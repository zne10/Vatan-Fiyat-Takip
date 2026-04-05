"""Crawl4AI tabanlı scraper — Playwright + anti-detect"""

import json
import logging
from typing import Optional

from vatan_bot.scrapers.base import BaseScraper
from vatan_bot.proxy.manager import ProxyManager

logger = logging.getLogger(__name__)


class Crawl4AIScraper(BaseScraper):
    def __init__(self, proxy_manager: Optional[ProxyManager] = None):
        self.proxy_manager = proxy_manager
        self._crawler = None

    async def _get_crawler(self):
        if self._crawler is None:
            try:
                from crawl4ai import AsyncWebCrawler
                self._crawler = AsyncWebCrawler(
                    headless=True,
                    browser_type="chromium",
                    verbose=False,
                )
                await self._crawler.__aenter__()
            except ImportError:
                logger.error("crawl4ai yüklü değil: pip install crawl4ai")
                raise
        return self._crawler

    async def fetch_html(self, url: str) -> Optional[str]:
        try:
            crawler = await self._get_crawler()

            kwargs = {
                "url": url,
                "magic": True,
                "simulate_user": True,
            }

            if self.proxy_manager:
                proxy = self.proxy_manager.get_proxy()
                if proxy:
                    kwargs["proxy"] = proxy

            result = await crawler.arun(**kwargs)

            if result and result.html:
                return result.html

            logger.warning(f"Crawl4AI boş sonuç: {url}")
            return None

        except Exception as e:
            logger.error(f"Crawl4AI hatası: {e} — {url}")
            return None

    async def fetch_category_structured(self, url: str) -> list[dict]:
        """Kategori sayfasını yapılandırılmış olarak çeker."""
        try:
            from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

            schema = {
                "name": "Vatan Ürün Listesi",
                "baseSelector": ".product-list--list-page",
                "fields": [
                    {"name": "name", "selector": ".product-list__product-name", "type": "text"},
                    {"name": "sku", "selector": ".product-list__product-code", "type": "text"},
                    {"name": "price", "selector": ".product-list__price", "type": "text"},
                    {"name": "old_price", "selector": ".product-list__current-price", "type": "text"},
                    {"name": "url", "selector": "a.product-list-link", "type": "attribute", "attribute": "href"},
                ],
            }

            crawler = await self._get_crawler()
            kwargs = {
                "url": url,
                "extraction_strategy": JsonCssExtractionStrategy(schema),
                "magic": True,
                "simulate_user": True,
            }

            if self.proxy_manager:
                proxy = self.proxy_manager.get_proxy()
                if proxy:
                    kwargs["proxy"] = proxy

            result = await crawler.arun(**kwargs)
            if result and result.extracted_content:
                return json.loads(result.extracted_content)

        except Exception as e:
            logger.error(f"Crawl4AI structured hatası: {e}")

        return []

    async def close(self):
        if self._crawler:
            await self._crawler.__aexit__(None, None, None)
            self._crawler = None
