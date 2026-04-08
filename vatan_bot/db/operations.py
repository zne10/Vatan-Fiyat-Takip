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


def bulk_register_urls(products: list[dict]) -> int:
    """
    URL listesini toplu olarak DB'ye kaydeder. Tek seferde binlerce ürün.
    Her dict: {"url": "...", "category": "..."} — SKU, fiyat vs sonra gelecek.
    URL'den otomatik SKU türetir. Mevcut URL'ler güncellenmez (sadece yeniler).
    Returns: eklenen yeni ürün sayısı
    """
    import hashlib
    import re

    conn = get_connection()
    added = 0

    # Mevcut URL'leri çek (hızlı lookup için set)
    existing = set(
        r[0] for r in conn.execute("SELECT url FROM products WHERE url IS NOT NULL").fetchall()
    )

    rows = []
    for p in products:
        url = p.get("url", "").strip()
        if not url or url in existing:
            continue

        # URL'den SKU türet
        path = url.rstrip("/").split("/")[-1]
        path = re.sub(r'\.html?$', '', path)
        if len(path) > 50:
            sku = f"url-{path[:30]}-{hashlib.md5(path.encode()).hexdigest()[:8]}"
        else:
            sku = f"url-{path}"

        # URL'den basit isim türet
        name = path.replace("-", " ").title()

        category = p.get("category", "")

        rows.append((sku, name, url, category))
        existing.add(url)  # duplikasyon engeli

    if rows:
        conn.executemany(
            """INSERT OR IGNORE INTO products (sku, name, url, category, data_completeness)
               VALUES (?, ?, ?, ?, 0)""",
            rows,
        )
        added = conn.total_changes
        conn.commit()

    conn.close()
    return len(rows)


def bulk_update_products(updates: list[dict]) -> int:
    """
    Kategori sayfasından gelen toplu veriyle mevcut ürünleri günceller.
    Her dict: {"url": ..., "sku": ..., "name": ..., "price": ..., "brand": ..., "category": ...}
    Fiyat değişimi varsa price_history'ye ekler.
    Returns: güncellenen ürün sayısı
    """
    import logging
    _log = logging.getLogger(__name__)

    conn = get_connection()
    updated = 0

    for p in updates:
        try:
            url = p.get("url", "")
            sku = p.get("sku", "")
            price = p.get("price")
            if not price or price <= 0:
                continue

            # Eşleşme: URL + SKU birlikte kontrol et, tutarsızsa SKU'yu tercih et
            row = None
            if sku and not sku.startswith("url-"):
                row = conn.execute("SELECT sku FROM products WHERE sku = ?", (sku,)).fetchone()
            if not row and url:
                row = conn.execute("SELECT sku FROM products WHERE url = ?", (url,)).fetchone()

            if row:
                db_sku = row[0]
                new_sku = db_sku

                # SKU güncelleme: url-xxx → gerçek SKU
                if db_sku.startswith("url-") and sku and not sku.startswith("url-"):
                    existing = conn.execute("SELECT sku FROM products WHERE sku = ?", (sku,)).fetchone()
                    if existing:
                        conn.execute("DELETE FROM price_history WHERE product_sku = ?", (db_sku,))
                        conn.execute("DELETE FROM products WHERE sku = ?", (db_sku,))
                        new_sku = sku
                    else:
                        conn.execute("UPDATE price_history SET product_sku = ? WHERE product_sku = ?", (sku, db_sku))
                        new_sku = sku

                # URL de güncelle (yanlış URL düzeltme)
                new_url = url if url else None
                conn.execute(
                    """UPDATE products SET
                        sku = ?,
                        name = COALESCE(NULLIF(?, ''), name),
                        url = COALESCE(NULLIF(?, ''), url),
                        brand = COALESCE(NULLIF(?, ''), brand),
                        category = COALESCE(NULLIF(?, ''), category),
                        data_completeness = 1,
                        updated_at = datetime('now','localtime')
                       WHERE sku = ?""",
                    (new_sku, p.get("name", ""), new_url or "", p.get("brand", ""), p.get("category", ""), new_sku),
                )

                last = conn.execute(
                    "SELECT price FROM price_history WHERE product_sku = ? ORDER BY scraped_at DESC LIMIT 1",
                    (new_sku,),
                ).fetchone()

                # Her zaman updated_at güncelle (dashboard son tarama zamanı için)
                conn.execute(
                    "UPDATE products SET updated_at = datetime('now','localtime') WHERE sku = ?",
                    (new_sku,),
                )

                if not last or last[0] != price:
                    # Anormal fiyat değişimi kontrolü (%80'den fazla değişim → atla)
                    if last and last[0] > 0:
                        change_ratio = abs(price - last[0]) / last[0]
                        if change_ratio > 0.80:
                            _log.warning(
                                f"Anormal fiyat: {new_sku} {last[0]:.0f} → {price:.0f} (%{change_ratio*100:.0f})"
                            )
                            updated += 1
                            continue

                    conn.execute(
                        "INSERT INTO price_history (product_sku, price, in_stock, scraped_at) VALUES (?, ?, ?, datetime('now','localtime'))",
                        (new_sku, price, p.get("in_stock", True)),
                    )

                updated += 1
            elif sku:
                conn.execute(
                    """INSERT OR IGNORE INTO products (sku, name, url, brand, category, data_completeness)
                       VALUES (?, ?, ?, ?, ?, 1)""",
                    (sku, p.get("name", ""), url, p.get("brand", ""), p.get("category", "")),
                )
                if conn.execute("SELECT 1 FROM products WHERE sku = ?", (sku,)).fetchone():
                    conn.execute(
                        "INSERT INTO price_history (product_sku, price, in_stock, scraped_at) VALUES (?, ?, ?, datetime('now','localtime'))",
                        (sku, price, p.get("in_stock", True)),
                    )
                updated += 1
        except Exception as e:
            _log.warning(f"bulk_update tekil hata (sku={p.get('sku','')}): {e}")
            continue

    conn.commit()
    conn.close()
    return updated


def get_unpriced_urls(limit: int = 500) -> list[str]:
    """Fiyat kaydı olmayan ürünlerin URL'lerini döner."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT url FROM products
           WHERE url IS NOT NULL AND url != ''
           AND sku NOT IN (SELECT DISTINCT product_sku FROM price_history)
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


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
    in_stock: bool = True,
) -> None:
    """Sadece fiyat değiştiyse yeni kayıt oluşturur. Aynı fiyat tekrar kaydedilmez."""
    conn = get_connection()
    # Son kayıtlı fiyatı kontrol et
    row = conn.execute(
        "SELECT price FROM price_history WHERE product_sku = ? ORDER BY scraped_at DESC LIMIT 1",
        (product_sku,),
    ).fetchone()

    if row and row[0] == price:
        # Fiyat aynı — sadece updated_at güncelle, yeni kayıt oluşturma
        conn.execute(
            "UPDATE products SET updated_at = datetime('now','localtime') WHERE sku = ?",
            (product_sku,),
        )
        conn.commit()
        conn.close()
        return

    # Fiyat değişti veya ilk kayıt — yeni price_history ekle
    conn.execute(
        """
        INSERT INTO price_history (product_sku, price, in_stock, scraped_at)
        VALUES (?, ?, ?, datetime('now', 'localtime'))
        """,
        (product_sku, price, in_stock),
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


# ── Fırsat Tespiti (Kural Tabanlı) ──

def _get_alert_rules() -> list[dict]:
    """Fırsat kurallarını getirir."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM alert_rules ORDER BY min_price").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_threshold_for_price(price: float) -> float:
    """Fiyat aralığına göre minimum düşüş eşiğini döner."""
    rules = _get_alert_rules()
    for rule in rules:
        if rule["min_price"] <= price <= rule["max_price"]:
            return rule["min_drop_pct"] / 100.0
    return 0.05  # varsayılan %5


def get_last_price_with_date(product_sku: str) -> Optional[dict]:
    """Son fiyat kaydını tarihiyle birlikte döner."""
    conn = get_connection()
    row = conn.execute(
        """SELECT price, scraped_at FROM price_history
           WHERE product_sku = ? ORDER BY scraped_at DESC LIMIT 1""",
        (product_sku,),
    ).fetchone()
    conn.close()
    if row:
        return {"price": row["price"], "date": row["scraped_at"]}
    return None


def check_price_drop(product_sku: str, current_price: float, threshold: float = None) -> Optional[dict]:
    """
    Fiyat düşüşü kontrolü — SADECE DB'deki gerçek fiyat geçmişiyle karşılaştırır.
    Sayfadaki kampanya fiyatı (üstü çizili) kullanılmaz.
    Düşüş varsa eski fiyatın tarihi de döner.
    """
    last = get_last_price_with_date(product_sku)
    if last is None:
        return None

    last_price = last["price"]
    last_date = last["date"]

    if current_price >= last_price:
        return None

    drop_pct = (last_price - current_price) / last_price

    # Kural tabanlı eşik
    if threshold is None:
        threshold = _get_threshold_for_price(current_price)

    if drop_pct < threshold:
        return None

    min_price = get_min_price(product_sku)
    is_all_time_low = current_price <= (min_price or current_price)

    # Ürün bilgisi
    product = get_product(product_sku)

    # Opportunity oluştur — eski fiyat tarihi ile
    create_opportunity(
        product_sku=product_sku,
        product_name=product["name"] if product else "",
        brand=product.get("brand", "") if product else "",
        category=product.get("category", "") if product else "",
        url=product.get("url", "") if product else "",
        old_price=last_price,
        new_price=current_price,
        drop_pct=round(drop_pct * 100, 1),
        old_price_date=last_date,
    )

    return {
        "sku": product_sku,
        "old_price": last_price,
        "old_price_date": last_date,
        "new_price": current_price,
        "drop_pct": drop_pct,
        "is_all_time_low": is_all_time_low,
    }


def create_opportunity(
    product_sku: str,
    product_name: str,
    brand: str,
    category: str,
    url: str,
    old_price: float,
    new_price: float,
    drop_pct: float,
    old_price_date: str = "",
) -> None:
    """
    Yeni fırsat kaydı oluşturur.
    old_price SADECE DB'deki gerçek fiyat geçmişinden gelmeli — kampanya fiyatı değil.
    old_price_date: bu fiyatın DB'de kaydedildiği tarih.
    """
    conn = get_connection()
    # Aynı ürün için son 1 saatte zaten fırsat oluşturulmuşsa atla
    existing = conn.execute(
        """SELECT id FROM opportunities
           WHERE product_sku = ? AND detected_at > datetime("now", "-1 hour") AND dismissed = 0""",
        (product_sku,),
    ).fetchone()
    if existing:
        conn.close()
        return

    conn.execute(
        """INSERT INTO opportunities
           (product_sku, product_name, brand, category, url, old_price, new_price, drop_pct, old_price_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (product_sku, product_name, brand, category, url, old_price, new_price, drop_pct, old_price_date),
    )
    conn.commit()
    conn.close()


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
