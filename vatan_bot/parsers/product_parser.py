"""Vatan Bilgisayar HTML sayfalarından ürün verisi parse etme"""

import json
import re
import logging
from typing import Optional
from bs4 import BeautifulSoup

from vatan_bot.parsers.price_parser import clean_price

logger = logging.getLogger(__name__)

# Bilinen marka isimleri — CDN yolundan gelen küçük harfli isimleri düzelt
BRAND_MAP = {
    "apple": "Apple", "samsung": "Samsung", "xiaomi": "Xiaomi", "huawei": "Huawei",
    "oppo": "Oppo", "realme": "Realme", "honor": "Honor", "oneplus": "OnePlus",
    "google": "Google", "sony": "Sony", "lg": "LG", "motorola": "Motorola",
    "nokia": "Nokia", "asus": "Asus", "acer": "Acer", "lenovo": "Lenovo",
    "hp": "HP", "dell": "Dell", "msi": "MSI", "monster": "Monster",
    "casper": "Casper", "toshiba": "Toshiba", "jbl": "JBL", "philips": "Philips",
    "logitech": "Logitech", "razer": "Razer", "steelseries": "SteelSeries",
    "hyperx": "HyperX", "corsair": "Corsair", "anker": "Anker", "baseus": "Baseus",
    "ugreen": "Ugreen", "tp-link": "TP-Link", "zyxel": "Zyxel",
    "sandisk": "SanDisk", "kingston": "Kingston", "lexar": "Lexar",
    "seagate": "Seagate", "wd": "WD", "verbatim": "Verbatim",
    "epson": "Epson", "canon": "Canon", "brother": "Brother",
    "bosch": "Bosch", "dyson": "Dyson", "karcher": "Karcher",
    "vestel": "Vestel", "arcelik": "Arçelik", "beko": "Beko",
    "tcl": "TCL", "hisense": "Hisense", "panasonic": "Panasonic",
}


def _extract_brand_from_img(card) -> str:
    """Ürün kartındaki CDN görsel yolundan marka adını çıkarır."""
    img = card.select_one("img[data-src]")
    if img:
        m = re.search(r"/PRODUCT/([^/]+)/", img.get("data-src", ""))
        if m:
            raw = m.group(1).lower()
            return BRAND_MAP.get(raw, raw.title())
    return ""


def _extract_category_from_breadcrumb(soup) -> str:
    """Breadcrumb'dan kategori adını çıkarır."""
    crumbs = soup.select(".breadcrumb a, [class*=breadcrumb] a")
    if crumbs:
        # Son breadcrumb linki kategori adıdır
        return crumbs[-1].get_text(strip=True)
    h1 = soup.select_one("h1")
    if h1:
        return h1.get_text(strip=True)
    return ""


def parse_jsonld_product(html: str) -> Optional[dict]:
    """
    Ürün detay sayfasından JSON-LD Product schema parse eder.
    En temiz ve en stabil yöntem.
    """
    soup = BeautifulSoup(html, "lxml")
    scripts = soup.find_all("script", type="application/ld+json")

    for script in scripts:
        try:
            data = json.loads(script.string)
            if data.get("@type") == "Product":
                offers = data.get("offers", {})
                return {
                    "name": data.get("name", ""),
                    "sku": data.get("sku", ""),
                    "mpn": data.get("mpn", ""),
                    "brand": data.get("brand", {}).get("name", "")
                    if isinstance(data.get("brand"), dict)
                    else data.get("brand", ""),
                    "category": data.get("category", ""),
                    "price": float(offers.get("price", 0)),
                    "currency": offers.get("priceCurrency", "TRY"),
                    "in_stock": "InStock" in offers.get("availability", ""),
                }
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.debug(f"JSON-LD parse hatası: {e}")
            continue

    return None


def parse_category_page(html: str) -> list[dict]:
    """
    Kategori/fırsat listesi sayfasından ürün kartlarını parse eder.
    CSS selector tabanlı. Marka ve kategori bilgisini de çıkarır.
    """
    soup = BeautifulSoup(html, "lxml")
    products = []

    # Sayfa genelinden kategori bilgisi
    page_category = _extract_category_from_breadcrumb(soup)

    cards = soup.select(".product-list--list-page")
    for card in cards:
        try:
            name_el = card.select_one(".product-list__product-name")
            sku_el = card.select_one(".product-list__product-code")
            link_el = card.select_one("a.product-list-link")

            if not name_el:
                continue

            name = name_el.get_text(strip=True)
            sku = sku_el.get_text(strip=True) if sku_el else ""

            # FİYAT MANTIĞI (Doğru):
            # .product-list__price          = gerçek/indirimli fiyat (her zaman)
            # .product-list__current-price  = eski/üstü çizili fiyat (sadece indirimli ürünlerde)
            old_price_el = card.select_one(
                ".price-basket-camp--new-price .product-list__current-price"
            )
            list_price_el = card.select_one(
                ".price-basket-camp--new-price .product-list__price"
            )
            if not list_price_el:
                list_price_el = card.select_one(".product-list__price")

            price = None
            old_price = None

            if list_price_el and list_price_el.get_text(strip=True):
                price = clean_price(list_price_el.get_text(strip=True))

            if old_price_el and old_price_el.get_text(strip=True):
                old_price = clean_price(old_price_el.get_text(strip=True))
            url = ""
            if link_el and link_el.get("href"):
                href = link_el["href"]
                if href.startswith("/"):
                    url = f"https://www.vatanbilgisayar.com{href}"
                else:
                    url = href

            if price is None:
                continue

            # Marka: CDN görsel yolundan çıkar
            brand = _extract_brand_from_img(card)

            products.append(
                {
                    "name": name,
                    "sku": sku,
                    "price": price,
                    "old_price": old_price,
                    "url": url,
                    "brand": brand,
                    "category": page_category,
                }
            )
        except Exception as e:
            logger.debug(f"Kart parse hatası: {e}")
            continue

    return products


def parse_product_detail(html: str, url: str = "") -> Optional[dict]:
    """
    Ürün detay sayfasını parse eder.
    Önce JSON-LD dener, eksik alanları CSS selector ile tamamlar.
    """
    soup = BeautifulSoup(html, "lxml")

    # JSON-LD'den veri çek
    jsonld = parse_jsonld_product(html)

    # CSS selector'lardan veri çek
    css_data = _parse_css_detail(soup)

    # İkisini birleştir — JSON-LD birincil, CSS yedek
    result = {}

    if jsonld and jsonld.get("price", 0) > 0:
        result = jsonld
        # JSON-LD'de eksik alanları CSS'den doldur
        if not result.get("sku") and css_data.get("sku"):
            result["sku"] = css_data["sku"]
        if not result.get("name") and css_data.get("name"):
            result["name"] = css_data["name"]
        if not result.get("mpn") and css_data.get("mpn"):
            result["mpn"] = css_data["mpn"]
    elif css_data and css_data.get("price", 0) > 0:
        result = css_data
    else:
        return None

    # Hala SKU yoksa URL'den türet
    if not result.get("sku") and url:
        result["sku"] = _sku_from_url(url)

    # Hala SKU yoksa sayfadaki data attribute'lardan dene
    if not result.get("sku"):
        sku_from_page = _find_sku_in_page(soup)
        if sku_from_page:
            result["sku"] = sku_from_page

    # HTML entity temizliği
    from html import unescape
    for key in ("name", "category", "brand", "mpn"):
        if result.get(key):
            result[key] = unescape(result[key])

    # Breadcrumb kategori → sadece alt kategori (2. segment)
    cat = result.get("category", "")
    if ">" in cat:
        parts = [p.strip() for p in cat.split(">")]
        # 2. segment en anlamlı alt kategori (1. çok genel, 3+ çok spesifik)
        result["category"] = parts[1] if len(parts) >= 2 else parts[0]

    return result if result.get("price", 0) > 0 else None


def _parse_css_detail(soup) -> dict:
    """CSS selector'larla ürün detay sayfasını parse eder."""
    try:
        name = ""
        h1 = soup.select_one("h1")
        if h1:
            name = h1.get_text(strip=True)

        # Fiyat
        price_el = soup.select_one(".product-detail-price-big")
        if not price_el:
            price_el = soup.select_one(".product-list__price")
        price = clean_price(price_el.get_text(strip=True)) if price_el else None

        # SKU — birkaç farklı selector dene
        sku = ""
        mpn = ""
        for sel in [
            ".product-list__product-code",
            "[data-product-id]",
            ".product-id",
            ".product-code",
        ]:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(strip=True) if sel != "[data-product-id]" else el.get("data-product-id", "")
                if text:
                    sku = text
                    break

        # SKU formatı: "MPN / İÇ_ID" — iç ID'yi al
        if "/" in sku:
            parts = sku.split("/")
            mpn = parts[0].strip()
            sku = parts[-1].strip()

        # Marka
        brand = ""
        brand_el = soup.select_one(".product-detail-brand, [itemprop=brand]")
        if brand_el:
            brand = brand_el.get_text(strip=True)

        # Kategori — breadcrumb'dan
        category = _extract_category_from_breadcrumb(soup)

        if not price:
            return {}

        return {
            "name": name,
            "sku": sku,
            "mpn": mpn,
            "brand": brand,
            "category": category,
            "price": price,
            "in_stock": True,
        }
    except Exception as e:
        logger.debug(f"CSS selector parse hatası: {e}")
        return {}


def _sku_from_url(url: str) -> str:
    """URL'den benzersiz bir SKU türetir. Örn: /urun-adi.html → 'url-urun-adi'"""
    import hashlib
    path = url.rstrip("/").split("/")[-1]
    # .html uzantısını kaldır
    path = re.sub(r'\.html?$', '', path)
    # URL çok uzunsa hash'le
    if len(path) > 50:
        short = path[:30] + "-" + hashlib.md5(path.encode()).hexdigest()[:8]
        return f"url-{short}"
    return f"url-{path}"


def _find_sku_in_page(soup) -> str:
    """Sayfadaki gizli input, data attribute veya JS'den SKU bulur."""
    # data-product-id attribute
    el = soup.select_one("[data-product-id]")
    if el:
        pid = el.get("data-product-id", "").strip()
        if pid:
            return pid

    # Gizli input
    for inp in soup.select("input[type=hidden]"):
        name = inp.get("name", "").lower()
        if "product" in name and "id" in name:
            val = inp.get("value", "").strip()
            if val:
                return val

    # Add to cart butonundaki data attribute
    btn = soup.select_one("[data-productid], [data-product-sku], .add-to-cart[data-id]")
    if btn:
        for attr in ["data-productid", "data-product-sku", "data-id"]:
            val = btn.get(attr, "").strip()
            if val:
                return val

    return ""
