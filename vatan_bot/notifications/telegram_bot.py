"""Telegram bildirim sistemi"""

import logging
from datetime import datetime
from typing import Optional

import requests

from vatan_bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from vatan_bot.parsers.price_parser import format_price

logger = logging.getLogger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_message(text: str, chat_id: str = None) -> bool:
    """Telegram mesajı gönderir."""
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN tanımlanmamış, mesaj gönderilemedi")
        return False

    target = chat_id or TELEGRAM_CHAT_ID
    if not target:
        logger.warning("TELEGRAM_CHAT_ID tanımlanmamış")
        return False

    try:
        resp = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": target,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        logger.error(f"Telegram API hatası: {resp.status_code} — {resp.text}")
        return False
    except Exception as e:
        logger.error(f"Telegram gönderim hatası: {e}")
        return False


def send_price_drop_alert(
    name: str,
    sku: str,
    new_price: float,
    old_price: float,
    drop_pct: float,
    url: str,
    is_all_time_low: bool = False,
) -> bool:
    """Fiyat düşüşü bildirimi gönderir."""
    atl_badge = "\n⭐ TARİHSEL EN DÜŞÜK FİYAT!" if is_all_time_low else ""
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    text = (
        f"🔔 <b>FİYAT DÜŞÜŞÜ ALARMI!</b>\n"
        f"────────────────────────\n"
        f"📦 {name}\n"
        f"🏷️ SKU: {sku}\n"
        f"💰 Yeni Fiyat: <b>{format_price(new_price)}</b>\n"
        f"📉 Eski Fiyat: {format_price(old_price)}\n"
        f"💡 İndirim: %{drop_pct * 100:.1f}\n"
        f"🔗 <a href=\"{url}\">Ürüne Git</a>\n"
        f"⏰ Tespit: {now}"
        f"{atl_badge}"
    )
    return send_message(text)


def send_target_price_alert(
    name: str,
    sku: str,
    current_price: float,
    target_price: float,
    url: str,
) -> bool:
    """Hedef fiyata ulaşma bildirimi gönderir."""
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    text = (
        f"🎯 <b>HEDEF FİYATA ULAŞILDI!</b>\n"
        f"────────────────────────\n"
        f"📦 {name}\n"
        f"🏷️ SKU: {sku}\n"
        f"💰 Güncel Fiyat: <b>{format_price(current_price)}</b>\n"
        f"🎯 Hedef Fiyat: {format_price(target_price)}\n"
        f"🔗 <a href=\"{url}\">Ürüne Git</a>\n"
        f"⏰ Tespit: {now}"
    )
    return send_message(text)


def send_new_firsat_alert(
    name: str,
    sku: str,
    price: float,
    old_price: Optional[float],
    url: str,
) -> bool:
    """Fırsat sayfasında yeni ürün bildirimi gönderir."""
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    price_line = f"💰 Fiyat: <b>{format_price(price)}</b>"
    if old_price and old_price > price:
        pct = (old_price - price) / old_price * 100
        price_line += f"\n📉 Eski Fiyat: {format_price(old_price)} (-%{pct:.0f})"

    text = (
        f"🆕 <b>YENİ FIRSAT ÜRÜNü!</b>\n"
        f"────────────────────────\n"
        f"📦 {name}\n"
        f"🏷️ SKU: {sku}\n"
        f"{price_line}\n"
        f"🔗 <a href=\"{url}\">Ürüne Git</a>\n"
        f"⏰ Tespit: {now}"
    )
    return send_message(text)


def send_status_report(
    total_products: int,
    total_scanned: int,
    drops_found: int,
    errors: int,
) -> bool:
    """Günlük durum raporu gönderir."""
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    text = (
        f"📊 <b>GÜNLÜK RAPOR</b>\n"
        f"────────────────────────\n"
        f"📦 Takip edilen: {total_products}\n"
        f"🔍 Taranan: {total_scanned}\n"
        f"📉 Düşüş tespit: {drops_found}\n"
        f"❌ Hata: {errors}\n"
        f"⏰ {now}"
    )
    return send_message(text)
