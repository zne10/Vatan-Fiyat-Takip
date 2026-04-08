"""Cloudflare Worker tabanlı scraper — async + hızlı IP maskeleme"""

import logging
from typing import Optional

import aiohttp

from vatan_bot.scrapers.base import BaseScraper
from vatan_bot.config import CF_WORKER_URL

logger = logging.getLogger(__name__)


class WorkerScraper(BaseScraper):
    def __init__(self):
        if not CF_WORKER_URL:
            raise ValueError("CF_WORKER_URL tanımlanmamış")
        self.worker_url = CF_WORKER_URL
        self._session = None

    async def _get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def fetch_html(self, url: str) -> Optional[str]:
        try:
            session = await self._get_session()
            async with session.post(
                self.worker_url,
                json={"url": url},
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"Worker HTTP {resp.status}")
                    return None

                data = await resp.json()
                status = data.get("status", 0)

                if status == 200:
                    return data.get("html", "")

                logger.debug(f"Worker hedef site HTTP {status}: {url}")
                return None

        except Exception as e:
            logger.error(f"Worker hatası: {e} — {url}")
            return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
