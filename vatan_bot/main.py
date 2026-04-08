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
PARALEL_WORKER = 10  # eşzamanlı tarayıcı sayısı

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
# MODÜL 2: KATEGORİ — kategori sayfalarını dolaş → ürün bilgileri
# ═══════════════════════════════════════════════════════════════════

async def _tara_tek_kategori_bilgi(s, base_url: str) -> dict:
    """Tek kategoriyi tüm sayfalarıyla tarar — ürün bilgisi + ilk fiyat. ASLA çökmez."""
    sonuc = {"urun": 0, "guncellenen": 0, "hatalar": 0}
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

            try:
                updated = bulk_update_products(products)
                sonuc["guncellenen"] += updated
            except Exception as e:
                logger.error(f"[KATEGORİ] DB hatası ({base_url} p{page}): {e}")
                sonuc["hatalar"] += 1

            sonuc["urun"] += len(products)

            if len(products) < 24:
                break
            page += 1
            if page > 50:
                break

        except Exception as e:
            logger.error(f"[KATEGORİ] Sayfa hatası ({base_url} p{page}): {e}")
            sonuc["hatalar"] += 1
            break

    return sonuc


async def kategori_tarama():
    """Kategori sayfalarını 5 paralel worker ile dolaş. Ürün bilgisi + ilk fiyat kaydı."""
    if is_night_time():
        return

    logger.info("📂 [KATEGORİ] Kategori tarama başlıyor (5 paralel)...")
    s = get_scraper()

    # Dinamik kategori keşfi
    kategori_urls = KATEGORI_URLS
    try:
        discovered = await discover_categories_from_homepage(s)
        if discovered and len(discovered) > len(KATEGORI_URLS):
            kategori_urls = [c["url"] for c in discovered]
            logger.info(f"[KATEGORİ] Dinamik keşif: {len(kategori_urls)} kategori")
    except Exception as e:
        logger.warning(f"[KATEGORİ] Dinamik keşif başarısız, sabit liste: {e}")

    toplam = {"urun": 0, "guncellenen": 0, "hatalar": 0, "tamamlanan": 0}
    sem = asyncio.Semaphore(PARALEL_WORKER)

    async def worker(base_url):
        async with sem:
            sonuc = await _tara_tek_kategori_bilgi(s, base_url)
            toplam["urun"] += sonuc["urun"]
            toplam["guncellenen"] += sonuc["guncellenen"]
            toplam["hatalar"] += sonuc["hatalar"]
            toplam["tamamlanan"] += 1
            if toplam["tamamlanan"] % 50 == 0:
                logger.info(
                    f"[KATEGORİ] İlerleme: {toplam['tamamlanan']}/{len(kategori_urls)} kategori, "
                    f"{toplam['urun']} ürün"
                )

    tasks = [asyncio.create_task(worker(url)) for url in kategori_urls]
    await asyncio.gather(*tasks, return_exceptions=True)

    stats["scanned"] += toplam["urun"]
    logger.info(
        f"✅ [KATEGORİ] {toplam['tamamlanan']} kategori, "
        f"{toplam['urun']} ürün, {toplam['guncellenen']} güncellendi, "
        f"{toplam['hatalar']} hata"
    )


# ═══════════════════════════════════════════════════════════════════
# MODÜL 3: FİYAT TAKİP — 5 paralel worker, fark varsa sinyal
# ═══════════════════════════════════════════════════════════════════

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


async def fiyat_tarama():
    """
    Tüm kategori sayfalarını 5 paralel worker ile dolaşır.
    Her ürünün fiyatını DB'deki son fiyatla karşılaştırır.
    Fark varsa → sinyal (Telegram + DB opportunity).
    """
    if is_night_time():
        return

    logger.info("💰 [FİYAT] Fiyat takip taraması başlıyor (5 paralel)...")
    s = get_scraper()

    # Kategori listesi
    kategori_urls = KATEGORI_URLS
    try:
        discovered = await discover_categories_from_homepage(s)
        if discovered and len(discovered) > len(KATEGORI_URLS):
            kategori_urls = [c["url"] for c in discovered]
            logger.info(f"[FİYAT] {len(kategori_urls)} kategori taranacak")
    except Exception as e:
        logger.warning(f"[FİYAT] Kategori keşfi başarısız: {e}")

    toplam = {"kontrol": 0, "dusus": 0, "hatalar": 0, "tamamlanan": 0}
    sem = asyncio.Semaphore(PARALEL_WORKER)

    async def worker(base_url):
        async with sem:
            sonuc = await _fiyat_kontrol_tek_kategori(s, base_url)
            toplam["kontrol"] += sonuc["kontrol"]
            toplam["dusus"] += sonuc["dusus"]
            toplam["hatalar"] += sonuc["hatalar"]
            toplam["tamamlanan"] += 1
            if toplam["tamamlanan"] % 50 == 0:
                logger.info(
                    f"[FİYAT] İlerleme: {toplam['tamamlanan']}/{len(kategori_urls)} kategori, "
                    f"{toplam['kontrol']} kontrol, {toplam['dusus']} düşüş"
                )

    tasks = [asyncio.create_task(worker(url)) for url in kategori_urls]
    await asyncio.gather(*tasks, return_exceptions=True)

    stats["scanned"] += toplam["kontrol"]
    logger.info(
        f"✅ [FİYAT] {toplam['tamamlanan']} kategori, "
        f"{toplam['kontrol']} fiyat kontrolü, "
        f"{toplam['dusus']} düşüş tespit, "
        f"{toplam['hatalar']} hata"
    )


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
    await kategori_tarama()
    await fiyat_tarama()
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
        kategori_job=kategori_tarama,
        urun_job=fiyat_tarama,
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
    await kategori_tarama()
    await fiyat_tarama()
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
        choices=["once", "scheduler", "kesif", "kategori", "fiyat", "firsat"],
        default="scheduler",
        help="Çalışma modu: once | scheduler | kesif | kategori | fiyat | firsat",
    )
    args = parser.parse_args()

    init_db()

    if args.mode == "once":
        asyncio.run(run_once())
    elif args.mode == "kesif":
        asyncio.run(kesif_tarama())
    elif args.mode == "kategori":
        asyncio.run(kategori_tarama())
    elif args.mode == "fiyat":
        asyncio.run(fiyat_tarama())
    elif args.mode == "firsat":
        asyncio.run(firsat_tarama())
    else:
        asyncio.run(run_scheduler())


if __name__ == "__main__":
    main()
