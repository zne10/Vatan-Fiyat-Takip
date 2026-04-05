"""Veritabanı şeması oluşturma"""

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
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT NOT NULL UNIQUE,
            mpn TEXT,
            name TEXT,
            url TEXT UNIQUE,
            brand TEXT,
            category TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_sku TEXT NOT NULL,
            target_price REAL NOT NULL,
            alert_sent BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_sku) REFERENCES products(sku)
        )
    """)

    # İndeksler
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_price_history_sku
        ON price_history(product_sku)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_price_history_scraped
        ON price_history(scraped_at)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_alerts_sku
        ON alerts(product_sku)
    """)

    conn.commit()
    conn.close()
