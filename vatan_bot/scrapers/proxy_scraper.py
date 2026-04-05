"""Ücretsiz proxy havuzu ile scraper — sunucu IP'si gizli kalır"""

import asyncio
import random
import logging
from typing import Optional

import requests

from vatan_bot.scrapers.base import BaseScraper
from vatan_bot.config import DEFAULT_HEADERS, REQUEST_DELAY_MIN, REQUEST_DELAY_MAX, MAX_RETRIES

logger = logging.getLogger(__name__)

# Ücretsiz proxy API'leri — her çağrıda taze proxy çeker
PROXY_APIS = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all&simplified=true",
    "https://www.proxy-list.download/api/v1/get?type=https",
]


class ProxyScraper(BaseScraper):
    """Ücretsiz proxy havuzundan rastgele proxy ile istek atar."""

    def __init__(self):
        self.proxies: list[str] = []
        self._last_fetch = 0

    def _refresh_proxies(self):
        """Proxy listesini günceller."""
        import time
        now = time.time()
        if self.proxies and now - self._last_fetch < 600:  # 10 dk cache
            return

        all_proxies = []
        for api_url in PROXY_APIS:
            try:
                resp = requests.get(api_url, timeout=10)
                if resp.status_code == 200:
                    lines = resp.text.strip().split("\n")
                    all_proxies.extend([p.strip() for p in lines if p.strip()])
            except Exception:
                continue

        if all_proxies:
            self.proxies = list(set(all_proxies))
            self._last_fetch = now
            logger.info(f"Proxy havuzu güncellendi: {len(self.proxies)} proxy")

    def _get_random_proxy(self) -> Optional[dict]:
        self._refresh_proxies()
        if not self.proxies:
            return None
        proxy = random.choice(self.proxies)
        if not proxy.startswith("http"):
            proxy = f"http://{proxy}"
        return {"http": proxy, "https": proxy}

    async def fetch_html(self, url: str) -> Optional[str]:
        headers = dict(DEFAULT_HEADERS)

        for attempt in range(MAX_RETRIES):
            try:
                delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
                await asyncio.sleep(delay)

                proxy_dict = self._get_random_proxy()

                resp = requests.get(
                    url,
                    headers=headers,
                    proxies=proxy_dict,
                    timeout=20,
                )

                if resp.status_code == 200 and len(resp.text) > 1000:
                    return resp.text

                logger.warning(f"Proxy HTTP {resp.status_code} — {url} (deneme {attempt+1})")

                # Kötü proxy'yi listeden çıkar
                if proxy_dict and resp.status_code in (403, 429, 503):
                    raw = proxy_dict.get("http", "")
                    if raw in self.proxies:
                        self.proxies.remove(raw)

            except Exception as e:
                logger.debug(f"Proxy hatası: {e} (deneme {attempt+1})")
                # Kötü proxy'yi çıkar
                continue

        return None

    async def close(self):
        pass
