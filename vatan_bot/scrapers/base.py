"""Scraper temel arayüzü"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseScraper(ABC):
    """Tüm scraper'ların uyması gereken arayüz."""

    @abstractmethod
    async def fetch_html(self, url: str) -> Optional[str]:
        """URL'den HTML içeriği çeker."""
        ...

    @abstractmethod
    async def close(self):
        """Kaynakları temizler."""
        ...
