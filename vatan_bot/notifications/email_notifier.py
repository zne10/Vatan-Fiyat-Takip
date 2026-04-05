"""E-posta bildirim modülü"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from vatan_bot.config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_TO

logger = logging.getLogger(__name__)


def send_email(subject: str, body: str) -> bool:
    """E-posta gönderir."""
    if not all([SMTP_USER, SMTP_PASS, EMAIL_TO]):
        logger.debug("E-posta ayarları eksik, gönderilmedi")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = EMAIL_TO

        html_part = MIMEText(body, "html", "utf-8")
        msg.attach(html_part)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, EMAIL_TO, msg.as_string())

        logger.info(f"E-posta gönderildi: {subject}")
        return True

    except Exception as e:
        logger.error(f"E-posta hatası: {e}")
        return False


def send_price_drop_email(
    name: str,
    sku: str,
    new_price: float,
    old_price: float,
    drop_pct: float,
    url: str,
) -> bool:
    subject = f"🔔 Fiyat Düşüşü: {name}"
    body = f"""
    <html><body>
    <h2>Fiyat Düşüşü Tespit Edildi!</h2>
    <table>
        <tr><td><b>Ürün:</b></td><td>{name}</td></tr>
        <tr><td><b>SKU:</b></td><td>{sku}</td></tr>
        <tr><td><b>Yeni Fiyat:</b></td><td><b>{new_price:,.0f} TL</b></td></tr>
        <tr><td><b>Eski Fiyat:</b></td><td><s>{old_price:,.0f} TL</s></td></tr>
        <tr><td><b>İndirim:</b></td><td>%{drop_pct * 100:.1f}</td></tr>
    </table>
    <p><a href="{url}">Ürüne Git →</a></p>
    </body></html>
    """
    return send_email(subject, body)
