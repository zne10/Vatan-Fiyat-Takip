"""
Vatan Bilgisayar Ürün & Kategori Keşfi

Keşif stratejisi (öncelik sırasına göre):
  1. llmmap.txt — Vatan'ın LLM haritası (934KB, ~10.900 URL, Cloudflare izinli)
  2. robots.txt → sitemap.axd (Cloudflare engelleyebilir)
  3. Kategori sayfalarından pagination

Sunucu IP'si gizli kalır — tüm istekler mevcut scraper chain üzerinden.
"""

import re
import logging
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
BASE_URL = "https://www.vatanbilgisayar.com"


# ─── Birincil: llmmap.txt ───────────────────────────────────────────

async def fetch_llmmap(scraper) -> tuple[list[str], list[str]]:
    """
    llmmap.txt'den tüm URL'leri çeker.
    Returns: (product_urls, category_urls)
    """
    url = f"{BASE_URL}/llmmap.txt"
    logger.info(f"llmmap.txt okunuyor: {url}")

    raw = await scraper.fetch_html(url)
    if not raw:
        logger.warning("llmmap.txt alınamadı")
        return [], []

    # Crawl4AI HTML sarmalı temizleme
    text = _strip_html_wrapper(raw)

    all_urls = [line.strip() for line in text.splitlines() if line.strip().startswith("http")]
    logger.info(f"llmmap.txt: {len(all_urls)} URL okundu")

    product_urls = []
    category_urls = []

    for u in all_urls:
        # http → https normalize
        u = u.replace("http://www.", "https://www.")
        if not u.startswith(BASE_URL):
            continue

        # .html ile bitenler ürün
        if u.rstrip("/").endswith(".html"):
            product_urls.append(u)
        else:
            path = u.replace(BASE_URL, "").strip("/")
            if path and _is_category_url(u):
                category_urls.append(u)

    logger.info(f"llmmap.txt: {len(product_urls)} ürün, {len(category_urls)} kategori")
    return product_urls, category_urls


# ─── Yedek: sitemap.axd (Cloudflare engelleyebilir) ─────────────────

async def fetch_sitemap_urls(scraper) -> list[str]:
    """robots.txt → sitemap.axd → URL'ler (yedek yöntem)."""
    # robots.txt'den sitemap URL'lerini bul
    robots_raw = await scraper.fetch_html(f"{BASE_URL}/robots.txt")
    if not robots_raw:
        return []

    robots_text = _strip_html_wrapper(robots_raw)
    sitemap_urls = []
    for line in robots_text.splitlines():
        line = line.strip()
        if line.lower().startswith("sitemap:"):
            sitemap_url = line.split(":", 1)[1].strip()
            # HTML çöpünü temizle
            sitemap_url = re.sub(r'<[^>]+>.*', '', sitemap_url).strip()
            if sitemap_url.startswith("http"):
                sitemap_urls.append(sitemap_url)

    all_urls = []
    for surl in sitemap_urls:
        urls = await _parse_single_sitemap(scraper, surl)
        # Alt sitemap varsa recursive
        for u in urls:
            if "sitemap" in u.lower() or u.endswith(".xml"):
                sub = await _parse_single_sitemap(scraper, u)
                all_urls.extend(sub)
            else:
                all_urls.append(u)

    return all_urls


async def _parse_single_sitemap(scraper, sitemap_url: str) -> list[str]:
    """Tek bir sitemap dosyasını parse eder."""
    logger.info(f"Sitemap okunuyor: {sitemap_url}")
    xml_text = await scraper.fetch_html(sitemap_url)
    if not xml_text:
        return []

    xml_text = _clean_xml(xml_text)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning(f"Sitemap XML parse hatası: {e}")
        return []

    tag = root.tag.lower()
    urls = []

    if "sitemapindex" in tag:
        for sitemap in root.findall("sm:sitemap", NS):
            loc = sitemap.find("sm:loc", NS)
            if loc is not None and loc.text:
                urls.append(loc.text.strip())
    elif "urlset" in tag:
        for url_el in root.findall("sm:url", NS):
            loc = url_el.find("sm:loc", NS)
            if loc is not None and loc.text:
                urls.append(loc.text.strip())

    logger.info(f"Sitemap {sitemap_url}: {len(urls)} URL")
    return urls


# ─── Ana Keşif Fonksiyonları ─────────────────────────────────────────

async def discover_product_urls_from_sitemap(scraper) -> list[str]:
    """
    Tüm ürün URL'lerini keşfeder.
    Önce llmmap.txt (güvenilir), sonra sitemap.axd (yedek).
    """
    # 1. llmmap.txt — birincil ve en güvenilir
    product_urls, _ = await fetch_llmmap(scraper)

    if product_urls:
        logger.info(f"llmmap.txt'den {len(product_urls)} ürün URL'si keşfedildi")
        return sorted(set(product_urls))

    # 2. Yedek: sitemap.axd
    logger.info("llmmap.txt başarısız, sitemap.axd deneniyor...")
    all_urls = await fetch_sitemap_urls(scraper)
    if all_urls:
        filtered = [u for u in all_urls if u.rstrip("/").endswith(".html")]
        logger.info(f"sitemap.axd'den {len(filtered)} ürün URL'si keşfedildi")
        return sorted(set(filtered))

    logger.warning("Hiçbir kaynaktan ürün URL'si keşfedilemedi")
    return []


async def discover_categories_from_homepage(scraper) -> list[dict]:
    """
    Tüm kategori URL'lerini keşfeder.
    Önce llmmap.txt'den, sonra ana sayfadan.
    """
    categories = {}

    # 1. llmmap.txt'den kategoriler
    _, cat_urls = await fetch_llmmap(scraper)
    for url in cat_urls:
        # URL'den isim türet
        path = url.replace(BASE_URL, "").strip("/")
        name = path.replace("-", " ").replace("/", " > ").title()
        categories[url] = name

    # 2. Ana sayfadan zenginleştir (kategori isimlerini düzelt)
    logger.info("Ana sayfadan kategori isimleri alınıyor...")
    html = await scraper.fetch_html(BASE_URL)
    if html:
        soup = BeautifulSoup(html, "lxml")
        for link in soup.select("a[href]"):
            href = link.get("href", "")
            name = link.get_text(strip=True)
            if not href or not name or len(name) > 60:
                continue

            if href.startswith("/"):
                full_url = f"{BASE_URL}{href}"
            elif href.startswith(BASE_URL):
                full_url = href
            else:
                continue

            if _is_category_url(full_url):
                # Ana sayfadaki isim llmmap'teki URL-türetilmiş isimden daha doğru
                categories[full_url] = name

    result = [{"name": name, "url": url} for url, name in categories.items()]
    logger.info(f"Toplam kategori keşfi: {len(result)} kategori")
    return result


# ─── Yardımcı Fonksiyonlar ───────────────────────────────────────────

def _is_category_url(url: str) -> bool:
    """URL'nin kategori sayfası olup olmadığını kontrol eder."""
    path = url.replace(BASE_URL, "").strip("/")

    if not path:
        return False

    # .html ile bitenler ürün
    if path.endswith(".html"):
        return False

    # Statik sayfaları atla
    skip = [
        "hakkimizda", "iletisim", "magaza", "siparis", "uyelik",
        "sepet", "blog", "destek", "garanti", "odeme", "kargo",
        "iade", "kvkk", "gizlilik", "cerez", "sss", "kampanya",
        "firsat-urunler", "javascript", "login", "arama",
        "yeni-urunler", "urun_kiyaslama",
    ]
    path_lower = path.lower()
    if any(s in path_lower for s in skip):
        return False

    # Query parametresi varsa atla
    if "?" in path:
        return False

    # Çok kısa veya çok uzun path'ler kategori değildir
    if len(path) < 3 or len(path) > 100:
        return False

    # Dosya uzantıları atla
    if re.search(r'\.\w{2,4}$', path) and not path.endswith("/"):
        return False

    return True


def _strip_html_wrapper(text: str) -> str:
    """Crawl4AI'ın HTML sarmalını temizler — <pre> içindeki metni çıkarır."""
    if "<pre" in text:
        soup = BeautifulSoup(text, "lxml")
        pre = soup.find("pre")
        if pre:
            return pre.get_text()
    return text


def _clean_xml(text: str) -> str:
    """XML'den önce gelen HTML/boşluk temizleme."""
    # Önce HTML sarmalını temizle
    text = _strip_html_wrapper(text)

    idx = text.find("<?xml")
    if idx > 0:
        text = text[idx:]
    elif not text.strip().startswith("<"):
        for tag in ("<urlset", "<sitemapindex"):
            idx = text.find(tag)
            if idx >= 0:
                text = text[idx:]
                break
    return text.strip()
