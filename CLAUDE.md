# Vatan Fiyat Takip — Claude Talimatları

## Proje
- Domain: vatan.zeynepnurefe.com.tr
- Sunucu: 154.53.167.116 (root) — `ssh vatan`
- GitHub: https://github.com/zne10/Vatan-Fiyat-Takip
- Deploy: `git push` → GitHub webhook → sunucu otomatik pull

## Kurallar
- Her şeyi kendin yap, kullanıcıya adım yapıştırma
- Tüm yanıtlar Türkçe (kod ve teknik terim hariç)
- Onay sormadan devam et
- Değişiklik sonrası commit + push yap

## Sunucu Yapısı
- `/var/www/projects/vatan-repo/` — uygulama kodu
- `/etc/nginx/sites-available/` — nginx config
- PM2 process yönetimi, port 9000 webhook

## Deploy
```bash
git add . && git commit -m "mesaj" && git push
```
