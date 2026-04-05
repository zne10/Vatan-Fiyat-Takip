"""
Fetcher Chain — Fallback zinciri ile IP gizleme garantisi.

Sunucu IP'si ASLA hedef siteye gitmez.
Sırasıyla dener:
  1. Cloudflare Worker (ücretsiz, en hızlı)
  2. Ücretsiz proxy havuzu
  3. Crawl4AI (browser tabanlı, en güvenilir)

Hiçbiri çalışmazsa None döner.
"""

import logging
from typing import Optional

from vatan_bot.scrapers.base import BaseScraper
from vatan_bot.config import CF_WORKER_URL

logger = logging.getLogger(__name__)


class ChainScraper(BaseScraper):
    """Fallback chain: Worker → Proxy → Crawl4AI"""

    def __init__(self):
        self._scrapers: list[tuple[str, BaseScraper]] = []
        self._init_chain()

    def _init_chain(self):
        # 1. Crawl4AI (birincil — browser tabanlı, en güvenilir IP gizleme)
        try:
            from vatan_bot.scrapers.crawl4ai_scraper import Crawl4AIScraper
            self._scrapers.append(("crawl4ai", Crawl4AIScraper(None)))
            logger.info("Chain: Crawl4AI eklendi (birincil)")
        except Exception as e:
            logger.warning(f"Crawl4AI başlatılamadı: {e}")

        # 2. Cloudflare Worker (yedek)
        if CF_WORKER_URL:
            try:
                from vatan_bot.scrapers.worker_scraper import WorkerScraper
                self._scrapers.append(("worker", WorkerScraper()))
                logger.info("Chain: Cloudflare Worker eklendi (yedek)")
            except Exception as e:
                logger.warning(f"Worker başlatılamadı: {e}")

        # 3. Ücretsiz proxy havuzu (son çare)
        try:
            from vatan_bot.scrapers.proxy_scraper import ProxyScraper
            self._scrapers.append(("proxy", ProxyScraper()))
            logger.info("Chain: Proxy havuzu eklendi (son çare)")
        except Exception as e:
            logger.warning(f"Proxy scraper başlatılamadı: {e}")

        if not self._scrapers:
            logger.error("UYARI: Hiçbir scraper başlatılamadı!")

    async def fetch_html(self, url: str) -> Optional[str]:
        """Zincirdeki scraper'ları sırayla dener."""
        for name, scraper in self._scrapers:
            try:
                html = await scraper.fetch_html(url)
                if html and len(html) > 500:
                    logger.debug(f"Chain: {name} başarılı — {url}")
                    return html
                logger.debug(f"Chain: {name} başarısız (boş/kısa yanıt) — {url}")
            except Exception as e:
                logger.warning(f"Chain: {name} hata — {e}")
                continue

        logger.error(f"Chain: Tüm scraper'lar başarısız — {url}")
        return None

    async def close(self):
        for _, scraper in self._scrapers:
            try:
                await scraper.close()
            except Exception:
                pass
