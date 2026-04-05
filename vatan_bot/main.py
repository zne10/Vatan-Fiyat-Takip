"""Vatan Fiyat Takip Botu — Ana giriş noktası"""

import asyncio
import logging
import sys
from typing import Optional

from vatan_bot.config import (
    PRIMARY_SCRAPER,
    FIRSAT_URL,
    KATEGORI_URLS,
    KATEGORI_MAX_SAYFA,
    PRICE_DROP_THRESHOLD,
)
from vatan_bot.db.models import init_db
from vatan_bot.db.operations import (
    upsert_product,
    add_price_record,
    get_product,
    get_tracked_urls,
    check_price_drop,
    check_target_alerts,
    mark_alert_sent,
    get_all_products,
)
from vatan_bot.parsers.product_parser import parse_category_page, parse_product_detail
from vatan_bot.proxy.manager import ProxyManager
from vatan_bot.scrapers.base import BaseScraper
from vatan_bot.notifications.telegram_bot import (
    send_price_drop_alert,
    send_target_price_alert,
    send_new_firsat_alert,
    send_status_report,
)
from vatan_bot.scheduler import create_scheduler, is_night_time

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("vatan_bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ── Global State ──
scraper: Optional[BaseScraper] = None
proxy_manager: Optional[ProxyManager] = None
stats = {"scanned": 0, "drops": 0, "errors": 0}


def get_scraper() -> BaseScraper:
    """Konfigürasyona göre aktif scraper'ı döner. Varsayılan: chain (IP gizli)."""
    global scraper, proxy_manager

    if scraper is not None:
        return scraper

    proxy_manager = ProxyManager()

    if PRIMARY_SCRAPER == "chain":
        # Fallback zinciri: Worker → Proxy → Crawl4AI (sunucu IP gizli)
        from vatan_bot.scrapers.chain_scraper import ChainScraper
        scraper = ChainScraper()
    elif PRIMARY_SCRAPER == "worker":
        from vatan_bot.scrapers.worker_scraper import WorkerScraper
        scraper = WorkerScraper()
    elif PRIMARY_SCRAPER == "proxy":
        from vatan_bot.scrapers.proxy_scraper import ProxyScraper
        scraper = ProxyScraper()
    elif PRIMARY_SCRAPER == "crawl4ai":
        from vatan_bot.scrapers.crawl4ai_scraper import Crawl4AIScraper
        scraper = Crawl4AIScraper(proxy_manager)
    elif PRIMARY_SCRAPER == "firecrawl":
        from vatan_bot.scrapers.firecrawl_scraper import FirecrawlScraper
        scraper = FirecrawlScraper()
    elif PRIMARY_SCRAPER == "requests":
        # DİKKAT: Bu mod sunucu IP'sini açığa çıkarır!
        from vatan_bot.scrapers.requests_scraper import RequestsScraper
        scraper = RequestsScraper(proxy_manager)
        logger.warning("⚠️ requests scraper kullanılıyor — sunucu IP'si gizli DEĞİL!")
    else:
        # Varsayılan: chain (her zaman IP gizli)
        from vatan_bot.scrapers.chain_scraper import ChainScraper
        scraper = ChainScraper()

    return scraper


def process_product(data: dict, url: str = ""):
    """Bir ürün verisini işler: DB'ye yaz, fiyat kontrolü yap, bildirim gönder."""
    sku = data.get("sku", "")
    if not sku:
        return

    name = data.get("name", "Bilinmeyen Ürün")
    price = data.get("price")
    if not price or price <= 0:
        return

    product_url = url or data.get("url", "")

    # Ürünü DB'ye ekle/güncelle
    upsert_product(
        sku=sku,
        name=name,
        url=product_url,
        mpn=data.get("mpn", ""),
        brand=data.get("brand", ""),
        category=data.get("category", ""),
    )

    # Fiyat düşüşü kontrolü
    drop = check_price_drop(sku, price, PRICE_DROP_THRESHOLD)
    if drop:
        logger.info(
            f"💰 Fiyat düşüşü: {name} — "
            f"{drop['old_price']} → {drop['new_price']} "
            f"(%{drop['drop_pct'] * 100:.1f})"
        )
        send_price_drop_alert(
            name=name,
            sku=sku,
            new_price=drop["new_price"],
            old_price=drop["old_price"],
            drop_pct=drop["drop_pct"],
            url=product_url,
            is_all_time_low=drop["is_all_time_low"],
        )
        stats["drops"] += 1

    # Hedef fiyat kontrolü
    target_alerts = check_target_alerts(sku, price)
    for alert in target_alerts:
        product = get_product(sku)
        send_target_price_alert(
            name=name,
            sku=sku,
            current_price=price,
            target_price=alert["target_price"],
            url=product_url,
        )
        mark_alert_sent(alert["id"])

    # Fiyatı kaydet
    add_price_record(
        product_sku=sku,
        price=price,
        old_price=data.get("old_price"),
        in_stock=data.get("in_stock", True),
    )

    stats["scanned"] += 1


# ── Tarama Görevleri ──

async def firsat_tarama():
    """Fırsat sayfasını tarar."""
    if is_night_time():
        return

    logger.info("🔍 Fırsat sayfası taranıyor...")
    s = get_scraper()

    page = 1
    while True:
        url = FIRSAT_URL if page == 1 else f"{FIRSAT_URL}?page={page}"
        html = await s.fetch_html(url)

        if not html:
            stats["errors"] += 1
            break

        products = parse_category_page(html)
        if not products:
            break

        for p in products:
            try:
                existing = get_product(p["sku"]) if p.get("sku") else None
                if not existing and p.get("sku"):
                    # Yeni fırsat ürünü
                    send_new_firsat_alert(
                        name=p["name"],
                        sku=p["sku"],
                        price=p["price"],
                        old_price=p.get("old_price"),
                        url=p.get("url", ""),
                    )
                process_product(p)
            except Exception as e:
                logger.error(f"Ürün işleme hatası: {e}")
                stats["errors"] += 1

        page += 1
        if len(products) < 24:
            break

    logger.info(f"✅ Fırsat tarama tamamlandı (sayfa: {page - 1})")


async def kategori_tarama():
    """Kategori sayfalarını tarar."""
    if is_night_time():
        return

    logger.info("🔍 Kategori sayfaları taranıyor...")
    s = get_scraper()

    for base_url in KATEGORI_URLS:
        for page in range(1, KATEGORI_MAX_SAYFA + 1):
            url = base_url if page == 1 else f"{base_url}?page={page}"
            html = await s.fetch_html(url)

            if not html:
                stats["errors"] += 1
                break

            products = parse_category_page(html)
            if not products:
                break

            for p in products:
                try:
                    process_product(p)
                except Exception as e:
                    logger.error(f"Ürün işleme hatası: {e}")
                    stats["errors"] += 1

            if len(products) < 24:
                break

    logger.info("✅ Kategori tarama tamamlandı")


async def urun_tarama():
    """Takip edilen ürünlerin detay sayfalarını tarar."""
    if is_night_time():
        return

    urls = get_tracked_urls()
    if not urls:
        return

    logger.info(f"🔍 {len(urls)} ürün detay sayfası taranıyor...")
    s = get_scraper()

    for url in urls:
        html = await s.fetch_html(url)
        if not html:
            stats["errors"] += 1
            continue

        data = parse_product_detail(html)
        if data:
            try:
                process_product(data, url)
            except Exception as e:
                logger.error(f"Ürün işleme hatası: {e}")
                stats["errors"] += 1

    logger.info("✅ Ürün detay tarama tamamlandı")


async def gunluk_rapor():
    """Günlük durum raporu gönderir."""
    products = get_all_products()
    send_status_report(
        total_products=len(products),
        total_scanned=stats["scanned"],
        drops_found=stats["drops"],
        errors=stats["errors"],
    )
    # İstatistikleri sıfırla
    stats["scanned"] = 0
    stats["drops"] = 0
    stats["errors"] = 0


# ── Ana Çalıştırma ──

async def run_once():
    """Tek seferlik tarama yapar (test/cron için)."""
    init_db()
    logger.info("🚀 Tek seferlik tarama başlıyor...")

    await firsat_tarama()
    await kategori_tarama()
    await urun_tarama()

    logger.info("✅ Tek seferlik tarama tamamlandı")

    s = get_scraper()
    await s.close()


async def run_scheduler():
    """Zamanlayıcı ile sürekli çalıştırma."""
    init_db()
    logger.info("🚀 Vatan Fiyat Takip Botu başlatılıyor...")

    scheduler = create_scheduler(
        firsat_job=firsat_tarama,
        kategori_job=kategori_tarama,
        urun_job=urun_tarama,
    )

    # Günlük rapor: 09:00
    from apscheduler.triggers.cron import CronTrigger
    scheduler.add_job(
        gunluk_rapor,
        CronTrigger(hour=9, minute=0),
        id="gunluk_rapor",
        name="Günlük Durum Raporu",
    )

    scheduler.start()
    logger.info("⏰ Zamanlayıcı başlatıldı")

    # İlk taramayı hemen yap
    await firsat_tarama()
    await kategori_tarama()
    await urun_tarama()

    # Sonsuz döngüde bekle
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Bot durduruluyor...")
        scheduler.shutdown()
        s = get_scraper()
        await s.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Vatan Fiyat Takip Botu")
    parser.add_argument(
        "--mode",
        choices=["once", "scheduler", "firsat", "kategori", "urun"],
        default="scheduler",
        help="Çalışma modu",
    )
    args = parser.parse_args()

    if args.mode == "once":
        asyncio.run(run_once())
    elif args.mode == "firsat":
        init_db()
        asyncio.run(firsat_tarama())
    elif args.mode == "kategori":
        init_db()
        asyncio.run(kategori_tarama())
    elif args.mode == "urun":
        init_db()
        asyncio.run(urun_tarama())
    else:
        asyncio.run(run_scheduler())


if __name__ == "__main__":
    main()
