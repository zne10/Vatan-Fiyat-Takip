"""Vatan Bilgisayar HTML sayfalarından ürün verisi parse etme"""

import json
import logging
from typing import Optional
from bs4 import BeautifulSoup

from vatan_bot.parsers.price_parser import clean_price

logger = logging.getLogger(__name__)


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
    CSS selector tabanlı.
    """
    soup = BeautifulSoup(html, "lxml")
    products = []

    cards = soup.select(".product-list--list-page")
    for card in cards:
        try:
            name_el = card.select_one(".product-list__product-name")
            sku_el = card.select_one(".product-list__product-code")
            price_el = card.select_one(
                ".price-basket-camp--new-price .product-list__price"
            )
            old_price_el = card.select_one(
                ".price-basket-camp--new-price .product-list__current-price"
            )
            link_el = card.select_one("a.product-list-link")

            if not name_el or not price_el:
                continue

            name = name_el.get_text(strip=True)
            sku = sku_el.get_text(strip=True) if sku_el else ""
            price = clean_price(price_el.get_text(strip=True))
            old_price = (
                clean_price(old_price_el.get_text(strip=True))
                if old_price_el
                else None
            )
            url = ""
            if link_el and link_el.get("href"):
                href = link_el["href"]
                if href.startswith("/"):
                    url = f"https://www.vatanbilgisayar.com{href}"
                else:
                    url = href

            if price is None:
                continue

            products.append(
                {
                    "name": name,
                    "sku": sku,
                    "price": price,
                    "old_price": old_price,
                    "url": url,
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

        old_price_el = soup.select_one(".old-price")
        old_price = (
            clean_price(old_price_el.get_text(strip=True)) if old_price_el else None
        )

        if not price:
            return None

        return {
            "name": name,
            "sku": sku,
            "mpn": mpn,
            "brand": "",
            "category": "",
            "price": price,
            "old_price": old_price,
            "in_stock": True,
        }
    except Exception as e:
        logger.debug(f"CSS selector parse hatası: {e}")
        return None
