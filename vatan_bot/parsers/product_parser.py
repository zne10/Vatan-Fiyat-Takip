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


def parse_product_detail(html: str) -> Optional[dict]:
    """
    Ürün detay sayfasını parse eder.
    Önce JSON-LD dener, başarısız olursa CSS selector'lara düşer.
    """
    # Önce JSON-LD
    result = parse_jsonld_product(html)
    if result and result["price"] > 0:
        return result

    # Fallback: CSS selector
    soup = BeautifulSoup(html, "lxml")
    try:
        name = ""
        h1 = soup.select_one("h1")
        if h1:
            name = h1.get_text(strip=True)

        price_el = soup.select_one(".product-detail-price-big")
        if not price_el:
            price_el = soup.select_one(".product-list__price")
        price = clean_price(price_el.get_text(strip=True)) if price_el else None

        sku_el = soup.select_one(".product-list__product-code")
        sku = sku_el.get_text(strip=True) if sku_el else ""

        # SKU formatı: "MPN / İÇ_ID" — iç ID'yi al
        if "/" in sku:
            parts = sku.split("/")
            mpn = parts[0].strip()
            sku = parts[-1].strip()
        else:
            mpn = ""

        if not price:
            return None

        return {
            "name": name,
            "sku": sku,
            "mpn": mpn,
            "brand": "",
            "category": "",
            "price": price,
            "in_stock": True,
        }
    except Exception as e:
        logger.debug(f"CSS selector parse hatası: {e}")
        return None
