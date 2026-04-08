"""
Vatan Fiyat Takip Botu — Ana giriş noktası

3 bağımsız modül:
  1. KEŞIF   — llmmap.txt → tüm URL'leri DB'ye toplu kaydet (saniyeler)
  2. KATEGORİ — kategori sayfalarını dolaş → ürün bilgileri (isim, SKU, marka, ilk fiyat)
  3. FİYAT   — kayıtlı ürünlerin fiyatını kontrol et, fark varsa sinyal (5 paralel worker)
"""

import asyncio
import logging
import sys
from typing import Optional

from vatan_bot.config import (
    PRIMARY_SCRAPER,
    FIRSAT_URL,
    KATEGORI_URLS,
    PRICE_DROP_THRESHOLD,
)
from vatan_bot.scrapers.sitemap_parser import (
    discover_categories_from_homepage,
    fetch_llmmap,
)
from vatan_bot.db.models import init_db
from vatan_bot.db.operations import (
    upsert_product,
    add_price_record,
    get_product,
    get_tracked_urls,
    get_unpriced_urls,
    check_price_drop,
    check_target_alerts,
    mark_alert_sent,
    get_all_products,
    bulk_register_urls,
    bulk_update_products,
    create_opportunity,
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

# ── Sabitler ──
PARALEL_WORKER = 3  # eşzamanlı tarayıcı (her biri ayrı browser)

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
        from vatan_bot.scrapers.requests_scraper import RequestsScraper
        scraper = RequestsScraper(proxy_manager)
        logger.warning("requests scraper — sunucu IP'si gizli DEĞİL!")
    else:
        from vatan_bot.scrapers.chain_scraper import ChainScraper
        scraper = ChainScraper()

    return scraper


# ═══════════════════════════════════════════════════════════════════
# MODÜL 1: KEŞİF — llmmap.txt → DB'ye toplu URL kayıt
# ═══════════════════════════════════════════════════════════════════

async def kesif_tarama():
    """llmmap.txt'den tüm ürün URL'lerini çek ve DB'ye toplu kaydet. Saniyeler sürer."""
    logger.info("🗺️ [KEŞİF] URL keşfi başlıyor...")
    s = get_scraper()

    try:
        product_urls, category_urls = await fetch_llmmap(s)
    except Exception as e:
        logger.error(f"[KEŞİF] llmmap.txt hatası: {e}")
        return 0

    if not product_urls:
        logger.warning("[KEŞİF] Ürün URL'si bulunamadı")
        return 0

    product_rows = [{"url": u, "category": ""} for u in product_urls]
    added = bulk_register_urls(product_rows)
    logger.info(f"✅ [KEŞİF] {len(product_urls)} URL, {added} yeni ürün DB'ye kaydedildi")
    return added


# ═══════════════════════════════════════════════════════════════════
# MODÜL 2: DETAY — fiyatsız ürünlerin detay sayfalarını tarar
# ═══════════════════════════════════════════════════════════════════

async def detay_tarama(worker_id: int = 0, total_workers: int = 1):
    """
    DB'de fiyatı olmayan ürünlerin detay sayfalarını tarar.
    llmmap.txt'den gelen ama kategori sayfasında çıkmayan ürünler için.
    """
    if is_night_time():
        return

    all_urls = get_unpriced_urls(limit=10000)
    # Bu worker'ın payı
    my_urls = [u for i, u in enumerate(all_urls) if i % total_workers == worker_id]

    if not my_urls:
        logger.info(f"[DETAY-{worker_id}] Fiyatsız ürün kalmadı")
        return

    logger.info(f"📦 [DETAY-{worker_id}] {len(my_urls)}/{len(all_urls)} fiyatsız ürün taranacak")
    s = get_scraper()
    taranan = 0
    hatalar = 0

    for i, url in enumerate(my_urls):
        try:
            html = await s.fetch_html(url)
            if not html:
                hatalar += 1
                continue

            data = parse_product_detail(html, url=url)
            if data and data.get("price", 0) > 0:
                try:
                    sku = data.get("sku", "")
                    if not sku:
                        continue
                    # URL ile mevcut ürünü bul, SKU'yu ve bilgileri güncelle
                    upsert_product(
                        sku=sku,
                        name=data.get("name", ""),
                        url=url,
                        brand=data.get("brand", ""),
                        category=data.get("category", ""),
                    )
                    add_price_record(sku, data["price"], data.get("in_stock", True))
                    # Eski url- kaydını temizle
                    from vatan_bot.db.models import get_connection
                    conn = get_connection()
                    conn.execute("DELETE FROM products WHERE url = ? AND sku LIKE 'url-%'", (url,))
                    conn.commit()
                    conn.close()
                    taranan += 1
                except Exception as e:
                    logger.error(f"[DETAY-{worker_id}] DB hatası: {e}")
                    hatalar += 1

            if (i + 1) % 50 == 0:
                logger.info(f"[DETAY-{worker_id}] {i+1}/{len(my_urls)} tarandi, {taranan} fiyat bulundu")

        except Exception as e:
            logger.error(f"[DETAY-{worker_id}] Hata: {e}")
            hatalar += 1

    logger.info(f"✅ [DETAY-{worker_id}] {taranan} fiyat bulundu, {hatalar} hata, {len(my_urls)} tarandı")
    await s.close()


# ═══════════════════════════════════════════════════════════════════
# MODÜL 3: FİYAT TAKİP — 5 paralel worker, fark varsa sinyal
# ═══════════════════════════════════════════════════════════════════

def _new_scraper() -> BaseScraper:
    """Her worker için yeni scraper instance oluşturur."""
    from vatan_bot.scrapers.chain_scraper import ChainScraper
    return ChainScraper()


async def _fiyat_kontrol_tek_kategori(s, base_url: str) -> dict:
    """Tek kategoriyi dolaşır, her üründe fiyat farkı varsa sinyal verir. ASLA çökmez."""
    sonuc = {"kontrol": 0, "dusus": 0, "hatalar": 0}
    page = 1

    while True:
        try:
            url = base_url if page == 1 else f"{base_url}?page={page}"
            html = await s.fetch_html(url)

            if not html:
                break

            products = parse_category_page(html)
            if not products:
                break

            for p in products:
                try:
                    sku = p.get("sku", "")
                    price = p.get("price")
                    if not sku or not price:
                        continue

                    # ÖNCE fiyat düşüşü kontrol et (DB'deki eski fiyatla karşılaştır)
                    # SONRA güncelle — yoksa yeni fiyat yazılır ve düşüş tespit edilemez
                    drop = check_price_drop(sku, price, PRICE_DROP_THRESHOLD)
                    if drop:
                        logger.info(
                            f"💰 [FİYAT] {p.get('name', '')} — "
                            f"{drop['old_price']:.0f} → {drop['new_price']:.0f} TL "
                            f"(%{drop['drop_pct'] * 100:.1f}) "
                            f"[eski fiyat tarihi: {drop['old_price_date']}]"
                        )
                        send_price_drop_alert(
                            name=p.get("name", ""),
                            sku=sku,
                            new_price=drop["new_price"],
                            old_price=drop["old_price"],
                            drop_pct=drop["drop_pct"],
                            url=p.get("url", ""),
                            is_all_time_low=drop["is_all_time_low"],
                        )
                        sonuc["dusus"] += 1
                        stats["drops"] += 1

                    # Hedef fiyat alarmları
                    target_alerts = check_target_alerts(sku, price)
                    for alert in target_alerts:
                        send_target_price_alert(
                            name=p.get("name", ""),
                            sku=sku,
                            current_price=price,
                            target_price=alert["target_price"],
                            url=p.get("url", ""),
                        )
                        mark_alert_sent(alert["id"])

                    # SONRA fiyatı DB'ye yaz (kontrol bittikten sonra)
                    try:
                        bulk_update_products([p])
                    except Exception:
                        pass

                    sonuc["kontrol"] += 1
                except Exception as e:
                    logger.error(f"[FİYAT] Sinyal hatası: {e}")
                    sonuc["hatalar"] += 1

            if len(products) < 24:
                break
            page += 1
            if page > 50:
                break

        except Exception as e:
            logger.error(f"[FİYAT] Sayfa hatası ({base_url} p{page}): {e}")
            sonuc["hatalar"] += 1
            break

    return sonuc


async def fiyat_tarama(worker_id: int = 0, total_workers: int = 1):
    """
    Kategori sayfalarını dolaşır, fiyat farkı varsa sinyal.
    worker_id / total_workers ile kategoriler bölünür — paralel process'ler çakışmaz.
    """
    if is_night_time():
        return

    s = get_scraper()

    # Kategori listesi
    kategori_urls = KATEGORI_URLS
    try:
        discovered = await discover_categories_from_homepage(s)
        if discovered and len(discovered) > len(KATEGORI_URLS):
            kategori_urls = [c["url"] for c in discovered]
    except Exception as e:
        logger.warning(f"[FİYAT-{worker_id}] Kategori keşfi başarısız: {e}")

    # Bu worker'ın payına düşen kategoriler
    my_urls = [u for i, u in enumerate(kategori_urls) if i % total_workers == worker_id]
    logger.info(f"💰 [FİYAT-{worker_id}] Başlıyor — {len(my_urls)}/{len(kategori_urls)} kategori")

    toplam = {"kontrol": 0, "dusus": 0, "hatalar": 0, "tamamlanan": 0}

    for base_url in my_urls:
        try:
            sonuc = await _fiyat_kontrol_tek_kategori(s, base_url)
            toplam["kontrol"] += sonuc["kontrol"]
            toplam["dusus"] += sonuc["dusus"]
            toplam["hatalar"] += sonuc["hatalar"]
            toplam["tamamlanan"] += 1
            if toplam["tamamlanan"] % 20 == 0:
                logger.info(
                    f"[FİYAT-{worker_id}] {toplam['tamamlanan']}/{len(my_urls)} kategori, "
                    f"{toplam['kontrol']} kontrol, {toplam['dusus']} düşüş"
                )
        except Exception as e:
            logger.error(f"[FİYAT-{worker_id}] Hata: {e}")
            toplam["hatalar"] += 1

    stats["scanned"] += toplam["kontrol"]
    logger.info(
        f"✅ [FİYAT-{worker_id}] {toplam['tamamlanan']} kategori, "
        f"{toplam['kontrol']} fiyat, {toplam['dusus']} düşüş, "
        f"{toplam['hatalar']} hata"
    )
    await s.close()


# ═══════════════════════════════════════════════════════════════════
# BONUS: Fırsat sayfası tarama
# ═══════════════════════════════════════════════════════════════════

async def firsat_tarama():
    """Fırsat sayfasını tarar — yeni fırsat ürünlerini bildirir."""
    if is_night_time():
        return

    logger.info("🔥 [FIRSAT] Fırsat sayfası taranıyor...")
    s = get_scraper()

    page = 1
    toplam = 0
    while True:
        try:
            url = FIRSAT_URL if page == 1 else f"{FIRSAT_URL}?page={page}"
            html = await s.fetch_html(url)

            if not html:
                break

            products = parse_category_page(html)
            if not products:
                break

            for p in products:
                try:
                    sku = p.get("sku", "")
                    if not sku:
                        continue
                    existing = get_product(sku)
                    if not existing:
                        send_new_firsat_alert(
                            name=p["name"],
                            sku=sku,
                            price=p["price"],
                            old_price=None,  # kampanya fiyatı kullanılmaz
                            url=p.get("url", ""),
                        )
                    # Ürünü kaydet/güncelle
                    upsert_product(
                        sku=sku,
                        name=p.get("name", ""),
                        url=p.get("url", ""),
                        brand=p.get("brand", ""),
                        category=p.get("category", ""),
                    )
                    if p.get("price"):
                        add_price_record(sku, p["price"], p.get("in_stock", True))
                    toplam += 1
                except Exception as e:
                    logger.error(f"[FIRSAT] Ürün hatası: {e}")

            page += 1
            if len(products) < 24:
                break
        except Exception as e:
            logger.error(f"[FIRSAT] Sayfa hatası: {e}")
            break

    logger.info(f"✅ [FIRSAT] {toplam} ürün, {page - 1} sayfa")


# ═══════════════════════════════════════════════════════════════════
# Günlük rapor
# ═══════════════════════════════════════════════════════════════════

async def gunluk_rapor():
    """Günlük durum raporu gönderir."""
    products = get_all_products()
    send_status_report(
        total_products=len(products),
        total_scanned=stats["scanned"],
        drops_found=stats["drops"],
        errors=stats["errors"],
    )
    stats["scanned"] = 0
    stats["drops"] = 0
    stats["errors"] = 0


# ═══════════════════════════════════════════════════════════════════
# Ana çalıştırma
# ═══════════════════════════════════════════════════════════════════

async def run_once():
    """
    Tek seferlik tam tarama:
      1) KEŞİF  → URL'leri DB'ye kaydet (saniyeler)
      2) KATEGORİ → ürün bilgileri + ilk fiyat (paralel)
      3) FİYAT  → fiyat karşılaştırma + sinyal (paralel)
      4) FIRSAT → fırsat sayfası
    """
    init_db()
    logger.info("🚀 Tek seferlik tam tarama başlıyor...")

    await kesif_tarama()
    await fiyat_tarama()
    await detay_tarama()
    await firsat_tarama()

    logger.info("✅ Tek seferlik tarama tamamlandı")
    s = get_scraper()
    await s.close()


async def run_scheduler():
    """Zamanlayıcı ile sürekli çalıştırma."""
    init_db()
    logger.info("🚀 Vatan Fiyat Takip Botu başlatılıyor...")

    scheduler = create_scheduler(
        firsat_job=firsat_tarama,
        kategori_job=fiyat_tarama,
        urun_job=detay_tarama,
        sitemap_job=kesif_tarama,
    )

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
    await kesif_tarama()
    await fiyat_tarama()
    await detay_tarama()
    await firsat_tarama()

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
        choices=["once", "scheduler", "kesif", "fiyat", "detay", "firsat"],
        default="scheduler",
        help="kesif=URL keşfi | fiyat=fiyat takip | detay=fiyatsız ürün tarama | firsat=fırsat sayfası",
    )
    parser.add_argument("--worker-id", type=int, default=0, help="Worker ID (0-based)")
    parser.add_argument("--total-workers", type=int, default=1, help="Toplam worker sayısı")
    args = parser.parse_args()

    init_db()

    if args.mode == "once":
        asyncio.run(run_once())
    elif args.mode == "kesif":
        asyncio.run(kesif_tarama())
    elif args.mode == "fiyat":
        asyncio.run(fiyat_tarama(worker_id=args.worker_id, total_workers=args.total_workers))
    elif args.mode == "detay":
        asyncio.run(detay_tarama(worker_id=args.worker_id, total_workers=args.total_workers))
    elif args.mode == "firsat":
        asyncio.run(firsat_tarama())
    else:
        asyncio.run(run_scheduler())


if __name__ == "__main__":
    main()
