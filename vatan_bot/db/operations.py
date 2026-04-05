"""Veritabanı CRUD operasyonları"""

from typing import Optional
from vatan_bot.db.models import get_connection


# ── Ürün İşlemleri ──

def upsert_product(
    sku: str,
    name: str,
    url: str,
    mpn: str = "",
    brand: str = "",
    category: str = "",
) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO products (sku, mpn, name, url, brand, category)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(sku) DO UPDATE SET
            name = excluded.name,
            url = excluded.url,
            mpn = COALESCE(NULLIF(excluded.mpn, ''), products.mpn),
            brand = COALESCE(NULLIF(excluded.brand, ''), products.brand),
            category = COALESCE(NULLIF(excluded.category, ''), products.category)
        """,
        (sku, mpn, name, url, brand, category),
    )
    conn.commit()
    conn.close()


def get_product(sku: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_products() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM products ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_tracked_urls() -> list[str]:
    conn = get_connection()
    rows = conn.execute("SELECT url FROM products WHERE url IS NOT NULL").fetchall()
    conn.close()
    return [r["url"] for r in rows]


# ── Fiyat Geçmişi ──

def add_price_record(
    product_sku: str,
    price: float,
    old_price: Optional[float] = None,
    in_stock: bool = True,
) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO price_history (product_sku, price, old_price, in_stock)
        VALUES (?, ?, ?, ?)
        """,
        (product_sku, price, old_price, in_stock),
    )
    conn.commit()
    conn.close()


def get_last_price(product_sku: str) -> Optional[float]:
    conn = get_connection()
    row = conn.execute(
        """
        SELECT price FROM price_history
        WHERE product_sku = ?
        ORDER BY scraped_at DESC LIMIT 1
        """,
        (product_sku,),
    ).fetchone()
    conn.close()
    return row["price"] if row else None


def get_min_price(product_sku: str) -> Optional[float]:
    conn = get_connection()
    row = conn.execute(
        "SELECT MIN(price) as min_price FROM price_history WHERE product_sku = ?",
        (product_sku,),
    ).fetchone()
    conn.close()
    return row["min_price"] if row else None


def get_price_history(product_sku: str, limit: int = 50) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM price_history
        WHERE product_sku = ?
        ORDER BY scraped_at DESC LIMIT ?
        """,
        (product_sku, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Alert İşlemleri ──

def add_alert(product_sku: str, target_price: float) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO alerts (product_sku, target_price) VALUES (?, ?)",
        (product_sku, target_price),
    )
    conn.commit()
    conn.close()


def get_active_alerts() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM alerts WHERE alert_sent = 0"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_alert_sent(alert_id: int) -> None:
    conn = get_connection()
    conn.execute("UPDATE alerts SET alert_sent = 1 WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()


# ── Fırsat Tespiti ──

def check_price_drop(product_sku: str, current_price: float, threshold: float) -> Optional[dict]:
    """Fiyat düşüşü kontrolü. Düşüş varsa detay döner, yoksa None."""
    last_price = get_last_price(product_sku)
    if last_price is None:
        return None

    if current_price >= last_price:
        return None

    drop_pct = (last_price - current_price) / last_price
    if drop_pct < threshold:
        return None

    min_price = get_min_price(product_sku)
    is_all_time_low = current_price <= (min_price or current_price)

    return {
        "sku": product_sku,
        "old_price": last_price,
        "new_price": current_price,
        "drop_pct": drop_pct,
        "is_all_time_low": is_all_time_low,
    }


def check_target_alerts(product_sku: str, current_price: float) -> list[dict]:
    """Hedef fiyata ulaşan alert'leri döner."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM alerts
        WHERE product_sku = ? AND alert_sent = 0 AND target_price >= ?
        """,
        (product_sku, current_price),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
