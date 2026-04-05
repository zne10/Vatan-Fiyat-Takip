"""Vatan Fiyat Takip — FastAPI REST API"""

import json
import os
import time
import psutil
from datetime import datetime
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from vatan_bot.db.models import get_connection, init_db

API_PORT = int(os.getenv("API_PORT", "8080"))

app = FastAPI(title="Vatan Fiyat Takip API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _rows(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _row(cur):
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


# ════════════════════════════════════════════════════════════
# DASHBOARD & STATS
# ════════════════════════════════════════════════════════════

@app.get("/api/stats")
def get_stats():
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM products")
    total = c.fetchone()[0]

    c.execute("SELECT COUNT(DISTINCT product_sku) FROM price_history")
    tracked = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM price_history WHERE scraped_at > datetime('now','localtime','-24 hours')")
    scans_today = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM opportunities WHERE detected_at > datetime('now','localtime','-24 hours') AND dismissed=0")
    drops_today = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM opportunities WHERE dismissed=0")
    active_opps = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM alerts WHERE alert_sent=0")
    active_alerts = c.fetchone()[0]

    c.execute("SELECT COUNT(DISTINCT brand) FROM products WHERE brand != ''")
    brand_count = c.fetchone()[0]

    c.execute("SELECT COUNT(DISTINCT category) FROM products WHERE category != ''")
    cat_count = c.fetchone()[0]

    conn.close()
    return {
        "total_products": total,
        "tracked_products": tracked,
        "scans_today": scans_today,
        "drops_today": drops_today,
        "active_opportunities": active_opps,
        "active_alerts": active_alerts,
        "brand_count": brand_count,
        "category_count": cat_count,
    }


@app.get("/api/tracking-stats")
def tracking_stats():
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM price_history")
    total_records = c.fetchone()[0]

    c.execute("SELECT MIN(scraped_at), MAX(scraped_at) FROM price_history")
    row = c.fetchone()
    first_scan, last_scan = row[0], row[1]

    c.execute("""
        SELECT COUNT(*) FROM price_history ph1
        WHERE EXISTS (
            SELECT 1 FROM price_history ph2
            WHERE ph2.product_sku = ph1.product_sku
            AND ph2.scraped_at < ph1.scraped_at
            AND ph2.price != ph1.price
        )
    """)
    price_changes = c.fetchone()[0]

    conn.close()
    return {
        "total_records": total_records,
        "price_changes": price_changes,
        "first_scan": first_scan,
        "last_scan": last_scan,
    }


# ════════════════════════════════════════════════════════════
# PRODUCTS
# ════════════════════════════════════════════════════════════

@app.get("/api/products")
def list_products(
    brand: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "scraped_at",
    order: str = "desc",
    page: int = 0,
    limit: int = 30,
):
    conn = get_connection()
    c = conn.cursor()

    conditions = []
    params = []
    if brand:
        conditions.append("p.brand = ?")
        params.append(brand)
    if category:
        conditions.append("p.category = ?")
        params.append(category)
    if search:
        conditions.append("(p.name LIKE ? OR p.brand LIKE ? OR p.sku LIKE ?)")
        q = f"%{search}%"
        params.extend([q, q, q])

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    allowed_sorts = {"name": "p.name", "brand": "p.brand", "category": "p.category",
                     "price": "ph.price", "scraped_at": "ph.scraped_at"}
    sort_col = allowed_sorts.get(sort, "ph.scraped_at")
    sort_dir = "ASC" if order == "asc" else "DESC"

    c.execute(f"""
        SELECT COUNT(*) FROM products p
        LEFT JOIN price_history ph ON ph.product_sku = p.sku
            AND ph.scraped_at = (SELECT MAX(scraped_at) FROM price_history WHERE product_sku = p.sku)
        {where}
    """, params)
    total = c.fetchone()[0]

    c.execute(f"""
        SELECT p.sku, p.name, p.url, p.brand, p.category, p.image_url,
               p.created_at, p.updated_at,
               ph.price, ph.in_stock, ph.scraped_at,
               prev.price AS prev_price, prev.scraped_at AS prev_date
        FROM products p
        LEFT JOIN price_history ph ON ph.product_sku = p.sku
            AND ph.scraped_at = (SELECT MAX(scraped_at) FROM price_history WHERE product_sku = p.sku)
        LEFT JOIN price_history prev ON prev.product_sku = p.sku
            AND prev.scraped_at = (
                SELECT MAX(scraped_at) FROM price_history
                WHERE product_sku = p.sku
                AND scraped_at < ph.scraped_at
                AND price != ph.price
            )
        {where}
        ORDER BY {sort_col} {sort_dir}
        LIMIT ? OFFSET ?
    """, params + [limit, page * limit])
    products = _rows(c)

    conn.close()
    return {"items": products, "total": total, "page": page, "limit": limit}


@app.get("/api/products/{sku}")
def get_product(sku: str):
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT * FROM products WHERE sku = ?", (sku,))
    product = _row(c)
    if not product:
        conn.close()
        raise HTTPException(404, "Ürün bulunamadı")

    c.execute("""
        SELECT price, old_price, in_stock, scraped_at
        FROM price_history WHERE product_sku = ? ORDER BY scraped_at ASC
    """, (sku,))
    history = _rows(c)

    conn.close()
    return {"product": product, "price_history": history}


# ════════════════════════════════════════════════════════════
# OPPORTUNITIES (Fırsatlar)
# ════════════════════════════════════════════════════════════

@app.get("/api/opportunities")
def list_opportunities(
    brand: Optional[str] = None,
    category: Optional[str] = None,
    dismissed: bool = False,
    sort: str = "drop_pct",
    order: str = "desc",
    limit: int = 100,
):
    conn = get_connection()
    c = conn.cursor()

    conditions = ["dismissed = ?"]
    params: list = [1 if dismissed else 0]
    if brand:
        conditions.append("brand = ?")
        params.append(brand)
    if category:
        conditions.append("category = ?")
        params.append(category)

    where = f"WHERE {' AND '.join(conditions)}"
    allowed = {"drop_pct": "drop_pct", "new_price": "new_price", "detected_at": "detected_at", "old_price": "old_price"}
    sort_col = allowed.get(sort, "drop_pct")
    sort_dir = "ASC" if order == "asc" else "DESC"

    c.execute(f"""
        SELECT * FROM opportunities {where}
        ORDER BY {sort_col} {sort_dir} LIMIT ?
    """, params + [limit])
    opps = _rows(c)
    conn.close()
    return opps


@app.delete("/api/opportunities/{opp_id}")
def dismiss_opportunity(opp_id: int):
    conn = get_connection()
    conn.execute("UPDATE opportunities SET dismissed = 1 WHERE id = ?", (opp_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


class BatchDismiss(BaseModel):
    ids: list[int]

@app.post("/api/opportunities/batch-dismiss")
def batch_dismiss(body: BatchDismiss):
    conn = get_connection()
    for oid in body.ids:
        conn.execute("UPDATE opportunities SET dismissed = 1 WHERE id = ?", (oid,))
    conn.commit()
    conn.close()
    return {"ok": True, "count": len(body.ids)}


# ════════════════════════════════════════════════════════════
# ALERT CONFIG (Fırsat Kuralları)
# ════════════════════════════════════════════════════════════

@app.get("/api/alert-config")
def get_alert_config():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM alert_rules ORDER BY min_price")
    rules = _rows(c)
    conn.close()
    return rules


class AlertRule(BaseModel):
    min_price: float = 0
    max_price: float = 999999
    min_drop_pct: float = 5

@app.post("/api/alert-config")
def save_alert_config(rules: list[AlertRule]):
    conn = get_connection()
    conn.execute("DELETE FROM alert_rules")
    for r in rules:
        conn.execute(
            "INSERT INTO alert_rules (min_price, max_price, min_drop_pct) VALUES (?, ?, ?)",
            (r.min_price, r.max_price, r.min_drop_pct),
        )
    conn.commit()
    conn.close()
    return {"ok": True}


# ════════════════════════════════════════════════════════════
# BRANDS & CATEGORIES
# ════════════════════════════════════════════════════════════

@app.get("/api/brands")
def list_brands():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT brand, COUNT(*) as count,
               ROUND(AVG(ph.price), 0) as avg_price
        FROM products p
        LEFT JOIN price_history ph ON ph.product_sku = p.sku
            AND ph.scraped_at = (SELECT MAX(scraped_at) FROM price_history WHERE product_sku = p.sku)
        WHERE p.brand != '' AND p.brand IS NOT NULL
        GROUP BY p.brand ORDER BY count DESC
    """)
    brands = _rows(c)
    conn.close()
    return brands


@app.get("/api/categories")
def list_categories():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT category, COUNT(*) as count,
               ROUND(AVG(ph.price), 0) as avg_price
        FROM products p
        LEFT JOIN price_history ph ON ph.product_sku = p.sku
            AND ph.scraped_at = (SELECT MAX(scraped_at) FROM price_history WHERE product_sku = p.sku)
        WHERE p.category != '' AND p.category IS NOT NULL
        GROUP BY p.category ORDER BY count DESC
    """)
    cats = _rows(c)
    conn.close()
    return cats


# ════════════════════════════════════════════════════════════
# SERVICES
# ════════════════════════════════════════════════════════════

@app.get("/api/services")
def list_services():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM services")
    services = _rows(c)
    conn.close()
    for s in services:
        s["stats"] = json.loads(s.get("stats_json") or "{}")
        s["config"] = json.loads(s.get("config_json") or "{}")
    return services


@app.post("/api/services/{name}/start")
def start_service(name: str):
    conn = get_connection()
    conn.execute(
        "UPDATE services SET status='running', started_at=datetime('now','localtime') WHERE name=?",
        (name,),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "status": "running"}


@app.post("/api/services/{name}/stop")
def stop_service(name: str):
    conn = get_connection()
    conn.execute("UPDATE services SET status='stopped', started_at=NULL WHERE name=?", (name,))
    conn.commit()
    conn.close()
    return {"ok": True, "status": "stopped"}


# ════════════════════════════════════════════════════════════
# SYSTEM
# ════════════════════════════════════════════════════════════

@app.get("/api/health")
def health():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM products")
    products = c.fetchone()[0]
    conn.close()
    return {"status": "healthy", "products": products, "timestamp": datetime.now().isoformat()}


@app.get("/api/system-resources")
def system_resources():
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "cpu_percent": cpu,
        "memory_total_gb": round(mem.total / (1024**3), 1),
        "memory_used_gb": round(mem.used / (1024**3), 1),
        "memory_percent": mem.percent,
        "disk_total_gb": round(disk.total / (1024**3), 1),
        "disk_used_gb": round(disk.used / (1024**3), 1),
        "disk_percent": round(disk.percent, 1),
    }


@app.get("/api/crawler-stats")
def crawler_stats():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT status, COUNT(*) as count,
               ROUND(AVG(response_time_ms)) as avg_time
        FROM crawl_logs
        WHERE created_at > datetime('now','localtime', '-24 hours')
        GROUP BY status
    """)
    stats = _rows(c)

    c.execute("SELECT COUNT(*) FROM crawl_logs WHERE created_at > datetime('now','localtime', '-24 hours')")
    total = c.fetchone()[0]

    c.execute("""
        SELECT COUNT(*) FROM crawl_logs
        WHERE status='success' AND created_at > datetime('now','localtime', '-24 hours')
    """)
    success = c.fetchone()[0]

    conn.close()
    return {
        "total_requests": total,
        "success_count": success,
        "success_rate": round(success / total * 100, 1) if total > 0 else 0,
        "by_status": stats,
    }


# ════════════════════════════════════════════════════════════
# SETTINGS
# ════════════════════════════════════════════════════════════

@app.get("/api/settings")
def get_settings():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM settings")
    rows = _rows(c)
    conn.close()
    return {r["key"]: r["value"] for r in rows}


class SettingUpdate(BaseModel):
    key: str
    value: str

@app.post("/api/settings")
def save_setting(body: SettingUpdate):
    conn = get_connection()
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now','localtime')) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (body.key, body.value),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ════════════════════════════════════════════════════════════
# STARTUP
# ════════════════════════════════════════════════════════════

@app.on_event("startup")
def startup():
    init_db()


def run_api():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=API_PORT)


if __name__ == "__main__":
    run_api()
