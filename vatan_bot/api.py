"""Dashboard için REST API — aiohttp tabanlı."""
import json
import os
from datetime import datetime, timedelta
from aiohttp import web
from vatan_bot.db.models import get_connection

API_PORT = int(os.getenv("API_PORT", "8080"))


def _rows_to_dicts(cursor):
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


# ── Endpoints ──────────────────────────────────────────────

async def handle_stats(request):
    """Genel istatistikler."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM products")
    total_products = cur.fetchone()[0]

    cur.execute("SELECT COUNT(DISTINCT product_sku) FROM price_history")
    tracked = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM price_history
        WHERE scraped_at > datetime('now', '-24 hours')
    """)
    scans_today = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM price_history ph1
        WHERE ph1.scraped_at > datetime('now', '-24 hours')
        AND ph1.price < (
            SELECT ph2.price FROM price_history ph2
            WHERE ph2.product_sku = ph1.product_sku
            AND ph2.scraped_at < ph1.scraped_at
            ORDER BY ph2.scraped_at DESC LIMIT 1
        )
    """)
    drops_today = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM alerts WHERE alert_sent = 0")
    active_alerts = cur.fetchone()[0]

    conn.close()
    return web.json_response({
        "total_products": total_products,
        "tracked_products": tracked,
        "scans_today": scans_today,
        "drops_today": drops_today,
        "active_alerts": active_alerts,
    })


async def handle_products(request):
    """Tüm ürünler + son fiyat."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT p.sku, p.name, p.url, p.brand, p.category, p.created_at,
               ph.price, ph.old_price, ph.in_stock, ph.scraped_at
        FROM products p
        LEFT JOIN price_history ph ON ph.product_sku = p.sku
            AND ph.scraped_at = (
                SELECT MAX(ph2.scraped_at) FROM price_history ph2
                WHERE ph2.product_sku = p.sku
            )
        ORDER BY ph.scraped_at DESC
    """)
    products = _rows_to_dicts(cur)
    conn.close()
    return web.json_response(products)


async def handle_drops(request):
    """Son 7 günde fiyatı düşen ürünler."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT p.sku, p.name, p.url, p.brand,
               ph1.price AS new_price, ph1.old_price,
               ph1.scraped_at,
               ROUND((ph1.old_price - ph1.price) / ph1.old_price * 100, 1) AS drop_pct
        FROM price_history ph1
        JOIN products p ON p.sku = ph1.product_sku
        WHERE ph1.scraped_at > datetime('now', '-7 days')
          AND ph1.old_price IS NOT NULL
          AND ph1.price < ph1.old_price
        ORDER BY drop_pct DESC
        LIMIT 50
    """)
    drops = _rows_to_dicts(cur)
    conn.close()
    return web.json_response(drops)


async def handle_product_history(request):
    """Tek ürünün fiyat geçmişi."""
    sku = request.match_info["sku"]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT price, old_price, in_stock, scraped_at
        FROM price_history
        WHERE product_sku = ?
        ORDER BY scraped_at ASC
    """, (sku,))
    history = _rows_to_dicts(cur)
    conn.close()
    return web.json_response(history)


async def handle_brands(request):
    """Tüm markalar ve ürün sayıları."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT brand, COUNT(*) as count
        FROM products
        WHERE brand != '' AND brand IS NOT NULL
        GROUP BY brand
        ORDER BY count DESC
    """)
    brands = _rows_to_dicts(cur)
    conn.close()
    return web.json_response(brands)


async def handle_categories(request):
    """Tüm kategoriler ve ürün sayıları."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT category, COUNT(*) as count
        FROM products
        WHERE category != '' AND category IS NOT NULL
        GROUP BY category
        ORDER BY count DESC
    """)
    categories = _rows_to_dicts(cur)
    conn.close()
    return web.json_response(categories)


async def handle_products_by_filter(request):
    """Marka veya kategoriye göre ürünler."""
    brand = request.query.get("brand", "")
    category = request.query.get("category", "")

    conn = get_connection()
    cur = conn.cursor()

    conditions = []
    params = []
    if brand:
        conditions.append("p.brand = ?")
        params.append(brand)
    if category:
        conditions.append("p.category = ?")
        params.append(category)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    cur.execute(f"""
        SELECT p.sku, p.name, p.url, p.brand, p.category, p.created_at,
               ph.price, ph.old_price, ph.in_stock, ph.scraped_at
        FROM products p
        LEFT JOIN price_history ph ON ph.product_sku = p.sku
            AND ph.scraped_at = (
                SELECT MAX(ph2.scraped_at) FROM price_history ph2
                WHERE ph2.product_sku = p.sku
            )
        {where}
        ORDER BY p.brand, p.name
    """, params)
    products = _rows_to_dicts(cur)
    conn.close()
    return web.json_response(products)


async def handle_alerts(request):
    """Aktif fiyat alarmları."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.id, a.product_sku, p.name, a.target_price, a.alert_sent, a.created_at,
               ph.price AS current_price
        FROM alerts a
        JOIN products p ON p.sku = a.product_sku
        LEFT JOIN price_history ph ON ph.product_sku = a.product_sku
            AND ph.scraped_at = (
                SELECT MAX(ph2.scraped_at) FROM price_history ph2
                WHERE ph2.product_sku = a.product_sku
            )
        ORDER BY a.created_at DESC
    """)
    alerts = _rows_to_dicts(cur)
    conn.close()
    return web.json_response(alerts)


# ── App ────────────────────────────────────────────────────

def create_app():
    app = web.Application()
    app.router.add_get("/api/stats", handle_stats)
    app.router.add_get("/api/products", handle_products)
    app.router.add_get("/api/drops", handle_drops)
    app.router.add_get("/api/products/{sku}/history", handle_product_history)
    app.router.add_get("/api/alerts", handle_alerts)
    app.router.add_get("/api/brands", handle_brands)
    app.router.add_get("/api/categories", handle_categories)
    app.router.add_get("/api/filter", handle_products_by_filter)

    # CORS
    import aiohttp.web_middlewares
    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            resp = web.Response()
        else:
            resp = await handler(request)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    app.middlewares.append(cors_middleware)
    return app


def run_api():
    app = create_app()
    web.run_app(app, host="127.0.0.1", port=API_PORT)


if __name__ == "__main__":
    run_api()
