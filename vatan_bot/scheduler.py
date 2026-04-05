"""APScheduler ile görev zamanlama"""

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from vatan_bot.config import (
    FIRSAT_INTERVAL_MINUTES,
    KATEGORI_INTERVAL_HOURS,
    URUN_INTERVAL_HOURS,
    GECE_BASLANGIC,
    GECE_BITIS,
)

logger = logging.getLogger(__name__)


def is_night_time() -> bool:
    """Gece saatlerinde tarama yapılıp yapılmayacağını kontrol eder."""
    hour = datetime.now().hour
    return GECE_BASLANGIC <= hour < GECE_BITIS


def create_scheduler(
    firsat_job,
    kategori_job,
    urun_job,
) -> AsyncIOScheduler:
    """Zamanlayıcıyı oluşturur ve görevleri ekler."""
    scheduler = AsyncIOScheduler()

    # Fırsat sayfası: her 30 dakikada bir (gece hariç)
    scheduler.add_job(
        firsat_job,
        IntervalTrigger(minutes=FIRSAT_INTERVAL_MINUTES),
        id="firsat_tarama",
        name="Fırsat Sayfası Tarama",
        max_instances=1,
    )

    # Kategori sayfaları: her 2 saatte bir (gece hariç)
    scheduler.add_job(
        kategori_job,
        IntervalTrigger(hours=KATEGORI_INTERVAL_HOURS),
        id="kategori_tarama",
        name="Kategori Tarama",
        max_instances=1,
    )

    # Takip edilen ürünler: her 1 saatte bir (gece hariç)
    scheduler.add_job(
        urun_job,
        IntervalTrigger(hours=URUN_INTERVAL_HOURS),
        id="urun_tarama",
        name="Ürün Takip Tarama",
        max_instances=1,
    )

    # Günlük durum raporu: her gün 09:00
    # (main.py'de eklenir)

    logger.info(
        f"Zamanlayıcı oluşturuldu: "
        f"fırsat={FIRSAT_INTERVAL_MINUTES}dk, "
        f"kategori={KATEGORI_INTERVAL_HOURS}sa, "
        f"ürün={URUN_INTERVAL_HOURS}sa"
    )

    return scheduler
