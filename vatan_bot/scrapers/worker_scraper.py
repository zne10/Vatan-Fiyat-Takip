"""Cloudflare Worker tabanlı scraper — ücretsiz IP maskeleme"""

import logging
from typing import Optional

import requests

from vatan_bot.scrapers.base import BaseScraper
from vatan_bot.config import CF_WORKER_URL

logger = logging.getLogger(__name__)


class WorkerScraper(BaseScraper):
    def __init__(self):
        if not CF_WORKER_URL:
            raise ValueError("CF_WORKER_URL tanımlanmamış")
        self.worker_url = CF_WORKER_URL

    async def fetch_html(self, url: str) -> Optional[str]:
        try:
            resp = requests.post(
                self.worker_url,
                json={"url": url},
                timeout=30,
            )

            if resp.status_code != 200:
                logger.warning(f"Worker HTTP {resp.status_code}")
                return None

            data = resp.json()
            status = data.get("status", 0)

            if status == 200:
                return data.get("html", "")

            logger.warning(f"Worker hedef site HTTP {status}: {url}")
            return None

        except Exception as e:
            logger.error(f"Worker hatası: {e} — {url}")
            return None

    async def close(self):
        pass
