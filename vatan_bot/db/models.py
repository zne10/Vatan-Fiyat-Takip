"""Veritabanı şeması oluşturma — Fırsat Avcısı mimarisi"""

import sqlite3
from vatan_bot.config import DB_PATH


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()

    # ── 1. ÜRÜNLER ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT NOT NULL UNIQUE,
            mpn TEXT,
            name TEXT,
            url TEXT UNIQUE,
            brand TEXT DEFAULT '',
            category TEXT DEFAULT '',
            image_url TEXT,
            description TEXT,
            data_completeness INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── 2. FİYAT GEÇMİŞİ (Append-only) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_sku TEXT NOT NULL,
            price REAL NOT NULL,
            old_price REAL,
            in_stock BOOLEAN DEFAULT 1,
            scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_sku) REFERENCES products(sku)
        )
    """)

    # ── 3. FIRSATLAR (Tespit edilen fiyat düşüşleri) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_sku TEXT NOT NULL,
            product_name TEXT,
            brand TEXT,
            category TEXT,
            url TEXT,
            old_price REAL NOT NULL,
            new_price REAL NOT NULL,
            drop_pct REAL NOT NULL,
            detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            dismissed BOOLEAN DEFAULT 0,
            notified BOOLEAN DEFAULT 0,
            FOREIGN KEY (product_sku) REFERENCES products(sku)
        )
    """)

    # ── 4. ALARMLAR (Kullanıcı hedef fiyat) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_sku TEXT NOT NULL,
            target_price REAL NOT NULL,
            alert_sent BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_sku) REFERENCES products(sku)
        )
    """)

    # ── 5. FIRSAT KURALLARI (Fiyat aralığına göre eşik) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS alert_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            min_price REAL DEFAULT 0,
            max_price REAL DEFAULT 999999,
            min_drop_pct REAL DEFAULT 5,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── 6. SERVİSLER (Worker durum yönetimi) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS services (
            name TEXT PRIMARY KEY,
            display_name TEXT,
            description TEXT,
            status TEXT DEFAULT 'stopped',
            started_at DATETIME,
            last_heartbeat DATETIME,
            stats_json TEXT DEFAULT '{}',
            config_json TEXT DEFAULT '{}'
        )
    """)

    # ── 7. CRAWL LOG (Audit trail) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS crawl_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            fetch_mode TEXT,
            status TEXT,
            response_time_ms INTEGER,
            error_message TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── 8. AYARLAR (Key-Value) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── İndeksler ──
    c.execute("CREATE INDEX IF NOT EXISTS idx_ph_sku ON price_history(product_sku)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ph_scraped ON price_history(scraped_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_alerts_sku ON alerts(product_sku)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_opp_detected ON opportunities(detected_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_opp_dismissed ON opportunities(dismissed)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(category)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_crawl_created ON crawl_logs(created_at)")

    # ── Varsayılan fırsat kuralları ──
    c.execute("SELECT COUNT(*) FROM alert_rules")
    if c.fetchone()[0] == 0:
        c.executemany("INSERT INTO alert_rules (min_price, max_price, min_drop_pct) VALUES (?, ?, ?)", [
            (0, 500, 10),
            (500, 5000, 5),
            (5000, 999999, 3),
        ])

    # ── Varsayılan servisler ──
    c.execute("SELECT COUNT(*) FROM services")
    if c.fetchone()[0] == 0:
        c.executemany("""
            INSERT OR IGNORE INTO services (name, display_name, description, status) VALUES (?, ?, ?, ?)
        """, [
            ("firsat_worker", "Fırsat Tarama", "Fırsat ürünleri sayfasını tarar", "stopped"),
            ("kategori_worker", "Kategori Tarama", "Kategori sayfalarını tarar", "stopped"),
            ("urun_worker", "Ürün Takip", "Kayıtlı ürünlerin fiyatlarını kontrol eder", "stopped"),
            ("api_server", "API Sunucu", "Dashboard REST API servisi", "running"),
        ])

    conn.commit()
    conn.close()
