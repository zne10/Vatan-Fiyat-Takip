"""Fiyat string temizleme ve dönüştürme"""

import re
from typing import Optional


def clean_price(raw: str) -> Optional[float]:
    """
    Farklı formatlardaki fiyat string'lerini float'a çevirir.
    Örnekler:
        "35.499"    → 35499.0
        "35.499 TL" → 35499.0
        "35499"     → 35499.0
        "1.299,99"  → 1299.99
        "919TL"     → 919.0
    """
    if not raw:
        return None

    text = raw.strip()
    text = text.replace("TL", "").replace("₺", "").strip()

    # Virgüllü format: "1.299,99"
    if "," in text:
        text = text.replace(".", "")
        text = text.replace(",", ".")
        try:
            return float(text)
        except ValueError:
            pass

    # Noktalı binlik ayraç: "35.499" (ondalık değil, binlik)
    # Kural: noktadan sonra tam 3 rakam varsa binlik ayraç
    cleaned = re.sub(r"[^\d.]", "", text)
    if not cleaned:
        return None

    parts = cleaned.split(".")
    if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
        # Binlik ayraç — noktaları kaldır
        cleaned = cleaned.replace(".", "")

    try:
        return float(cleaned)
    except ValueError:
        return None


def format_price(price: float) -> str:
    """Fiyatı Türk formatında göster: 35.499 TL"""
    if price == int(price):
        return f"{int(price):,} TL".replace(",", ".")
    return f"{price:,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")
