module.exports = {
  apps: [
    {
      name: "vatan-api",
      cwd: "/var/www/projects/vatan-repo",
      script: "python3",
      args: "-m uvicorn vatan_bot.api:app --host 127.0.0.1 --port 8080",
      autorestart: true,
      max_restarts: 10,
    },
    {
      name: "vatan-kesif",
      cwd: "/var/www/projects/vatan-repo",
      script: "python3",
      args: "-m vatan_bot.main --mode kesif",
      autorestart: true,
      restart_delay: 43200000, // bitince 12 saat bekle, tekrar çalıştır
      max_restarts: 100,
    },
    {
      name: "vatan-kategori",
      cwd: "/var/www/projects/vatan-repo",
      script: "python3",
      args: "-m vatan_bot.main --mode kategori",
      autorestart: true,
      restart_delay: 7200000, // bitince 2 saat bekle, tekrar çalıştır
      max_restarts: 100,
    },
    {
      name: "vatan-fiyat",
      cwd: "/var/www/projects/vatan-repo",
      script: "python3",
      args: "-m vatan_bot.main --mode fiyat",
      autorestart: true,
      restart_delay: 1000, // bitince 1 sn bekle, hemen tekrar başlat (aralıksız)
      max_restarts: 10000,
    },
    {
      name: "vatan-firsat",
      cwd: "/var/www/projects/vatan-repo",
      script: "python3",
      args: "-m vatan_bot.main --mode firsat",
      autorestart: true,
      restart_delay: 1800000, // bitince 30 dk bekle, tekrar çalıştır
      max_restarts: 100,
    },
  ],
};
