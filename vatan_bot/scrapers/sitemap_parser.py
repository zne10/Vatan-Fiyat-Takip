"""
Vatan Bilgisayar Sitemap & Ürün Keşfi

Üç katmanlı keşif stratejisi:
  1. robots.txt → sitemap index → ürün URL'leri
  2. sitemap.xml doğrudan parse
  3. Kategori sayfalarından pagination ile tüm ürünler

Sunucu IP'si gizli kalır — tüm istekler mevcut scraper chain üzerinden.
"""

import re
import logging
from typing import Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

# Sitemap XML namespace
NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

BASE_URL = "https://www.vatanbilgisayar.com"


async def fetch_robots_txt(scraper) -> list[str]:
    """robots.txt'den sitemap URL'lerini çeker."""
    url = f"{BASE_URL}/robots.txt"
    logger.info(f"robots.txt okunuyor: {url}")

    html = await scraper.fetch_html(url)
    if not html:
        logger.warning("robots.txt alınamadı")
        return []

    sitemaps = []
    for line in html.splitlines():
        line = line.strip()
        if line.lower().startswith("sitemap:"):
            sitemap_url = line.split(":", 1)[1].strip()
            sitemaps.append(sitemap_url)
            logger.info(f"robots.txt'den sitemap bulundu: {sitemap_url}")

    return sitemaps


async def parse_sitemap_index(scraper, sitemap_url: str) -> list[str]:
    """
    Sitemap index dosyasını parse eder.
    Sitemap index ise child sitemap URL'lerini döner.
    Normal sitemap ise doğrudan URL'leri döner.
    """
    logger.info(f"Sitemap okunuyor: {sitemap_url}")
    xml_text = await scraper.fetch_html(sitemap_url)
    if not xml_text:
        logger.warning(f"Sitemap alınamadı: {sitemap_url}")
        return []

    # XML'den önce gelen HTML varsa temizle
    xml_text = _clean_xml(xml_text)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error(f"Sitemap XML parse hatası: {e}")
        return []

    tag = root.tag.lower()

    # Sitemap index ise
    if "sitemapindex" in tag:
        child_urls = []
        for sitemap in root.findall("sm:sitemap", NS):
            loc = sitemap.find("sm:loc", NS)
            if loc is not None and loc.text:
                child_urls.append(loc.text.strip())
        logger.info(f"Sitemap index: {len(child_urls)} alt sitemap bulundu")
        return child_urls

    # Normal urlset ise
    if "urlset" in tag:
        urls = []
        for url_el in root.findall("sm:url", NS):
            loc = url_el.find("sm:loc", NS)
            if loc is not None and loc.text:
                urls.append(loc.text.strip())
        logger.info(f"Sitemap: {len(urls)} URL bulundu")
        return urls

    logger.warning(f"Bilinmeyen sitemap formatı: {tag}")
    return []


async def discover_product_urls_from_sitemap(scraper) -> list[str]:
    """
    Tam sitemap keşfi:
      1. robots.txt → sitemap URL'leri
      2. Her sitemap'i parse et (index ise recursive)
      3. Ürün URL'lerini filtrele

    Returns: Benzersiz ürün URL'leri listesi
    """
    all_urls = []

    # 1. robots.txt'den sitemap'leri bul
    sitemap_urls = await fetch_robots_txt(scraper)

    # robots.txt boşsa varsayılan sitemap'leri dene
    if not sitemap_urls:
        sitemap_urls = [
            f"{BASE_URL}/sitemap.xml",
            f"{BASE_URL}/sitemap_index.xml",
            f"{BASE_URL}/product-sitemap.xml",
        ]
        logger.info("robots.txt'de sitemap yok, varsayılan URL'ler deneniyor")

    # 2. Her sitemap'i parse et
    for sitemap_url in sitemap_urls:
        urls = await parse_sitemap_index(scraper, sitemap_url)

        # Alt sitemap'ler varsa (index dosyasıysa)
        sub_sitemaps = [u for u in urls if u.endswith(".xml") or "sitemap" in u.lower()]
        direct_urls = [u for u in urls if u not in sub_sitemaps]

        all_urls.extend(direct_urls)

        # Alt sitemap'leri de parse et
        for sub_url in sub_sitemaps:
            sub_urls = await parse_sitemap_index(scraper, sub_url)
            # İkinci seviye sitemap varsa onu da parse et
            for u in sub_urls:
                if u.endswith(".xml") or "sitemap" in u.lower():
                    deep_urls = await parse_sitemap_index(scraper, u)
                    all_urls.extend(deep_urls)
                else:
                    all_urls.append(u)

    # 3. Sadece ürün URL'lerini filtrele
    product_urls = filter_product_urls(all_urls)
    logger.info(f"Sitemap keşfi tamamlandı: {len(all_urls)} toplam URL, {len(product_urls)} ürün URL'si")

    return product_urls


def filter_product_urls(urls: list[str]) -> list[str]:
    """
    URL listesinden sadece ürün detay sayfalarını filtreler.
    Vatan URL formatı: /urun-adi-p-123456/ veya /urun-adi-456789/
    """
    product_urls = set()

    for url in urls:
        url = url.strip()
        if not url.startswith(BASE_URL):
            continue

        path = url.replace(BASE_URL, "")

        # Kategori, bilgi ve statik sayfaları atla
        skip_patterns = [
            "/firsat-urunler",
            "/kampanyalar",
            "/hakkimizda",
            "/iletisim",
            "/magaza",
            "/siparis",
            "/uyelik",
            "/sepet",
            "/blog",
            "/destek",
            "/garanti",
            "/odeme",
            "/kargo",
            "/iade",
            "/kvkk",
            "/gizlilik",
            "/cerez",
            "/sss",
        ]
        if any(path.startswith(p) for p in skip_patterns):
            continue

        # Boş path veya sadece / ise atla
        if not path or path == "/":
            continue

        # Ürün URL pattern: /urun-adi-p-123456/ veya sayıyla biten slug
        # Vatan'da ürün URL'leri genellikle -p- veya sonunda sayısal ID içerir
        if re.search(r'-p-\d+', path) or re.search(r'-\d{4,}/?$', path):
            product_urls.add(url)
            continue

        # Alt kategoriler genelde kısa path'ler: /cep-telefonu-modelleri/
        # Ürünler daha uzun: /samsung-galaxy-s24-ultra-256gb-p-123456/
        # En az 3 tire varsa muhtemelen üründür
        segments = path.strip("/").split("-")
        if len(segments) >= 4 and any(s.isdigit() for s in segments):
            product_urls.add(url)

    return sorted(product_urls)


async def discover_categories_from_homepage(scraper) -> list[dict]:
    """
    Ana sayfadan ve navigasyon menüsünden tüm kategori URL'lerini keşfeder.

    Returns: [{"name": "Cep Telefonu", "url": "https://.../"}, ...]
    """
    logger.info("Ana sayfadan kategori keşfi başlıyor...")
    html = await scraper.fetch_html(BASE_URL)
    if not html:
        logger.error("Ana sayfa alınamadı")
        return []

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")

    categories = {}

    # 1. Ana navigasyon menüsü
    nav_links = soup.select(
        ".header-nav-list a, "
        ".main-menu a, "
        "nav a, "
        ".category-menu a, "
        "[class*=menu] a, "
        "[class*=nav] a"
    )

    for link in nav_links:
        href = link.get("href", "")
        name = link.get_text(strip=True)
        if not href or not name:
            continue

        # Tam URL oluştur
        if href.startswith("/"):
            full_url = f"{BASE_URL}{href}"
        elif href.startswith(BASE_URL):
            full_url = href
        else:
            continue

        # Kategori sayfası mı kontrol et
        if _is_category_url(full_url):
            categories[full_url] = name

    # 2. Sitemap'ten keşfedilen kategori URL'leri
    # Ana sayfadaki tüm linkleri tara
    all_links = soup.select("a[href]")
    for link in all_links:
        href = link.get("href", "")
        name = link.get_text(strip=True)
        if not href or not name:
            continue

        if href.startswith("/"):
            full_url = f"{BASE_URL}{href}"
        elif href.startswith(BASE_URL):
            full_url = href
        else:
            continue

        if _is_category_url(full_url) and full_url not in categories:
            categories[full_url] = name

    result = [{"name": name, "url": url} for url, name in categories.items()]
    logger.info(f"Kategori keşfi: {len(result)} kategori bulundu")

    return result


def _is_category_url(url: str) -> bool:
    """URL'nin kategori sayfası olup olmadığını kontrol eder."""
    path = url.replace(BASE_URL, "").strip("/")

    if not path:
        return False

    # Ürün URL'lerini atla (sayı içerenler genelde ürün)
    if re.search(r'-p-\d+', path):
        return False
    if re.search(r'-\d{5,}/?$', path):
        return False

    # Statik sayfaları atla
    skip = [
        "hakkimizda", "iletisim", "magaza", "siparis", "uyelik",
        "sepet", "blog", "destek", "garanti", "odeme", "kargo",
        "iade", "kvkk", "gizlilik", "cerez", "sss", "kampanya",
        "firsat-urunler", "javascript", "#", "tel:", "mailto:",
    ]
    path_lower = path.lower()
    if any(s in path_lower for s in skip):
        return False

    # Query parametresi varsa atla (filtreleme sayfaları)
    if "?" in path:
        return False

    # Çok kısa veya çok uzun path'ler kategori değildir
    if len(path) < 3 or len(path) > 80:
        return False

    # Segment sayısı: kategoriler genelde 1-2 segment
    segments = path.split("/")
    if len(segments) > 3:
        return False

    return True


def _clean_xml(text: str) -> str:
    """XML'den önce gelen HTML/boşluk temizleme."""
    # XML declaration'ı bul
    idx = text.find("<?xml")
    if idx > 0:
        text = text[idx:]
    # Eğer XML declaration yoksa root element'i bul
    elif not text.strip().startswith("<"):
        idx = text.find("<urlset")
        if idx == -1:
            idx = text.find("<sitemapindex")
        if idx >= 0:
            text = text[idx:]
    return text.strip()
