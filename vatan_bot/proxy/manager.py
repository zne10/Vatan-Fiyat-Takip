"""Proxy rotasyon ve kara liste yönetimi"""

import random
import time
import logging
from typing import Optional

from vatan_bot.config import PROXY_LIST

logger = logging.getLogger(__name__)


class ProxyManager:
    def __init__(self, proxies: list[str] = None):
        self.proxies = list(proxies or PROXY_LIST)
        self.blacklist: dict[str, float] = {}  # proxy → unban timestamp
        self.usage_count: dict[str, int] = {}
        self.max_consecutive = 10  # aynı proxy ile max ardışık istek
        self._current_streak: dict[str, int] = {}

    def get_proxy(self) -> Optional[str]:
        """Kullanılabilir rastgele bir proxy döner."""
        if not self.proxies:
            return None

        now = time.time()
        available = [
            p for p in self.proxies
            if p not in self.blacklist or self.blacklist[p] < now
        ]

        # Süresi dolan banları temizle
        expired = [p for p, t in self.blacklist.items() if t < now]
        for p in expired:
            del self.blacklist[p]

        if not available:
            logger.warning("Tüm proxy'ler kara listede! En kısa süreli ban bekleniyor.")
            return None

        # Streak limiti aşanları filtrele
        filtered = [
            p for p in available
            if self._current_streak.get(p, 0) < self.max_consecutive
        ]
        if not filtered:
            # Tüm streak'leri sıfırla
            self._current_streak.clear()
            filtered = available

        proxy = random.choice(filtered)

        # Streak takibi
        for p in self._current_streak:
            if p != proxy:
                self._current_streak[p] = 0
        self._current_streak[proxy] = self._current_streak.get(proxy, 0) + 1
        self.usage_count[proxy] = self.usage_count.get(proxy, 0) + 1

        return proxy

    def get_proxy_dict(self) -> Optional[dict]:
        """requests kütüphanesi formatında proxy dict döner."""
        proxy = self.get_proxy()
        if not proxy:
            return None
        return {"http": proxy, "https": proxy}

    def ban_proxy(self, proxy: str, duration: int = 86400):
        """Proxy'yi belirtilen süre (saniye) kadar kara listeye al."""
        self.blacklist[proxy] = time.time() + duration
        logger.info(f"Proxy kara listeye alındı ({duration}s): {proxy[:30]}...")

    def report_error(self, proxy: str, status_code: int):
        """HTTP hata koduna göre proxy'yi yönet."""
        if status_code == 429:
            # Rate limit — 5 dakika ban
            self.ban_proxy(proxy, 300)
        elif status_code == 403:
            # Yasaklandı — 1 saat ban
            self.ban_proxy(proxy, 3600)
        elif status_code == 503:
            # Cloudflare challenge — 2 saat ban
            self.ban_proxy(proxy, 7200)

    def report_success(self, proxy: str):
        """Başarılı istek sonrası proxy'yi ödüllendir (ban varsa kaldır)."""
        self.blacklist.pop(proxy, None)

    @property
    def available_count(self) -> int:
        now = time.time()
        return sum(
            1 for p in self.proxies
            if p not in self.blacklist or self.blacklist[p] < now
        )

    @property
    def stats(self) -> dict:
        return {
            "total": len(self.proxies),
            "available": self.available_count,
            "blacklisted": len(self.proxies) - self.available_count,
            "usage": dict(self.usage_count),
        }
