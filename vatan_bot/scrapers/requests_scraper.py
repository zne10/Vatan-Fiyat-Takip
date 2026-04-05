"""Requests + BeautifulSoup tabanlı basit scraper"""

import asyncio
import random
import logging
from typing import Optional

import requests

from vatan_bot.scrapers.base import BaseScraper
from vatan_bot.config import (
    DEFAULT_HEADERS,
    REQUEST_DELAY_MIN,
    REQUEST_DELAY_MAX,
    MAX_RETRIES,
    BACKOFF_FACTOR,
)
from vatan_bot.proxy.manager import ProxyManager

logger = logging.getLogger(__name__)


class RequestsScraper(BaseScraper):
    def __init__(self, proxy_manager: Optional[ProxyManager] = None):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.proxy_manager = proxy_manager

    async def fetch_html(self, url: str) -> Optional[str]:
        """URL'den HTML çeker. Rate limit ve retry mantığı dahil."""
        for attempt in range(MAX_RETRIES):
            try:
                # Rastgele bekleme
                delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
                await asyncio.sleep(delay)

                proxies = None
                current_proxy = None
                if self.proxy_manager:
                    proxies = self.proxy_manager.get_proxy_dict()
                    current_proxy = proxies.get("http") if proxies else None

                response = self.session.get(
                    url, proxies=proxies, timeout=30
                )

                if response.status_code == 200:
                    if current_proxy and self.proxy_manager:
                        self.proxy_manager.report_success(current_proxy)
                    return response.text

                # Hata durumu
                logger.warning(
                    f"HTTP {response.status_code} — {url} (deneme {attempt + 1})"
                )
                if current_proxy and self.proxy_manager:
                    self.proxy_manager.report_error(current_proxy, response.status_code)

                if response.status_code in (429, 503):
                    wait = BACKOFF_FACTOR ** attempt * 60
                    logger.info(f"Backoff: {wait}s bekleniyor...")
                    await asyncio.sleep(wait)
                elif response.status_code == 403:
                    # Proxy değiştir ve tekrar dene
                    await asyncio.sleep(5)

            except requests.RequestException as e:
                logger.error(f"İstek hatası: {e} — {url} (deneme {attempt + 1})")
                wait = BACKOFF_FACTOR ** attempt * 2
                await asyncio.sleep(wait)

        logger.error(f"Tüm denemeler başarısız: {url}")
        return None

    async def close(self):
        self.session.close()
