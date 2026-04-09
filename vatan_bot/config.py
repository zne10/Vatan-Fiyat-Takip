"""Vatan Fiyat Takip Botu — Konfigürasyon"""

import os
from pathlib import Path
from dotenv import load_dotenv

# .env dosyasını yükle
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent / ".env")

# ── Telegram ──
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Scraper Servisleri ──
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
CF_WORKER_URL = os.getenv("CF_WORKER_URL", "")

# ── Proxy ──
PROXY_LIST = [
    p.strip()
    for p in os.getenv("PROXY_LIST", "").split(",")
    if p.strip()
]

# ── E-posta ──
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")

# ── Veritabanı ──
DB_PATH = BASE_DIR / "data" / "vatan.db"

# ── Fiyat Takip Ayarları ──
PRICE_DROP_THRESHOLD = float(os.getenv("PRICE_DROP_THRESHOLD", "0.05"))

# ── Scraping Ayarları ──
REQUEST_DELAY_MIN = 2.0  # saniye
REQUEST_DELAY_MAX = 5.0
MAX_RETRIES = 3
BACKOFF_FACTOR = 2  # exponential backoff çarpanı

# ── Zamanlama ──
FIRSAT_INTERVAL_MINUTES = 30
KATEGORI_INTERVAL_HOURS = 2
URUN_INTERVAL_HOURS = 1
GECE_BASLANGIC = 5   # 05:00
GECE_BITIS = 5        # 05:00 (gece modu kapalı — 7/24 tarama)

# ── Takip Edilecek Sayfalar ──
FIRSAT_URL = "https://www.vatanbilgisayar.com/firsat-urunler"
KATEGORI_URLS = [
    # Telefon & Tablet
    "https://www.vatanbilgisayar.com/cep-telefonu-modelleri/",
    "https://www.vatanbilgisayar.com/tablet/",
    # Bilgisayar
    "https://www.vatanbilgisayar.com/bilgisayar/",
    "https://www.vatanbilgisayar.com/oyun-bilgisayari-notebook/",
    "https://www.vatanbilgisayar.com/monitor/",
    # TV & Ses
    "https://www.vatanbilgisayar.com/televizyon/",
    "https://www.vatanbilgisayar.com/kulaklik/",
    "https://www.vatanbilgisayar.com/bluetooth-hoparlor/",
    "https://www.vatanbilgisayar.com/soundbar/",
    # Aksesuar & Çevre Birimleri
    "https://www.vatanbilgisayar.com/mouse/",
    "https://www.vatanbilgisayar.com/klavye/",
    "https://www.vatanbilgisayar.com/gaming-mouse/",
    "https://www.vatanbilgisayar.com/gaming-klavye/",
    "https://www.vatanbilgisayar.com/mousepad/",
    "https://www.vatanbilgisayar.com/gaming-kulaklik/",
    # Giyilebilir
    "https://www.vatanbilgisayar.com/akilli-saat/",
    "https://www.vatanbilgisayar.com/akilli-bileklik/",
    # Depolama
    "https://www.vatanbilgisayar.com/tasinabilir-disk/",
    "https://www.vatanbilgisayar.com/usb-bellek/",
    "https://www.vatanbilgisayar.com/ssd/",
    # Yazıcı & Kamera
    "https://www.vatanbilgisayar.com/yazici/",
    "https://www.vatanbilgisayar.com/fotograf-makinesi/",
    # Ağ & Akıllı Ev
    "https://www.vatanbilgisayar.com/router-modem/",
    "https://www.vatanbilgisayar.com/akilli-ev/",
    # Elektrikli Ev Aletleri
    "https://www.vatanbilgisayar.com/elektrikli-supurge/",
    "https://www.vatanbilgisayar.com/camasir-makinesi/",
    "https://www.vatanbilgisayar.com/bulasik-makinesi/",
    # Oyun
    "https://www.vatanbilgisayar.com/playstation/",
    "https://www.vatanbilgisayar.com/oyun-konsolu/",
]
# Eski limit — artık main.py'de sınırsız tarama yapılıyor (güvenlik limiti: 50 sayfa)
KATEGORI_MAX_SAYFA = 50

# ── HTTP Headers ──
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Referer": "https://www.vatanbilgisayar.com/",
}

# ── Aktif Scraper Seçimi ──
# "chain" (varsayılan, IP gizli), "worker", "proxy", "crawl4ai", "firecrawl", "requests"
# DİKKAT: "requests" sunucu IP'sini açığa çıkarır — sadece test için!
PRIMARY_SCRAPER = os.getenv("PRIMARY_SCRAPER", "chain")
