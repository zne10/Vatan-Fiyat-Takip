"""Firecrawl API tabanlı scraper — managed servis"""

import logging
from typing import Optional

from vatan_bot.scrapers.base import BaseScraper
from vatan_bot.config import FIRECRAWL_API_KEY

logger = logging.getLogger(__name__)


class FirecrawlScraper(BaseScraper):
    def __init__(self):
        if not FIRECRAWL_API_KEY:
            raise ValueError("FIRECRAWL_API_KEY tanımlanmamış")

        try:
            from firecrawl import FirecrawlApp
            self.app = FirecrawlApp(api_key=FIRECRAWL_API_KEY)
        except ImportError:
            logger.error("firecrawl-py yüklü değil: pip install firecrawl-py")
            raise

    async def fetch_html(self, url: str) -> Optional[str]:
        try:
            result = self.app.scrape_url(
                url,
                params={"formats": ["html"]},
            )
            if result and "html" in result:
                return result["html"]
            return None
        except Exception as e:
            logger.error(f"Firecrawl hatası: {e} — {url}")
            return None

    async def scrape_product_data(self, url: str) -> Optional[dict]:
        """Firecrawl extract özelliği ile doğrudan yapılandırılmış veri çeker."""
        try:
            result = self.app.scrape_url(
                url,
                params={
                    "formats": ["extract"],
                    "extract": {
                        "schema": {
                            "name": "string",
                            "price": "number",
                            "old_price": "number",
                            "sku": "string",
                            "in_stock": "boolean",
                            "brand": "string",
                        }
                    },
                },
            )
            if result and "extract" in result:
                return result["extract"]
            return None
        except Exception as e:
            logger.error(f"Firecrawl extract hatası: {e} — {url}")
            return None

    async def close(self):
        pass
