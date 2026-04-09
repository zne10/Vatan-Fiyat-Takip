const REPO = "/var/www/projects/vatan-repo";
const FIYAT_WORKERS = 8;

const fiyatApps = Array.from({length: FIYAT_WORKERS}, (_, i) => ({
  name: `vatan-fiyat-${i}`,
  cwd: REPO,
  script: "python3",
  args: `-m vatan_bot.main --mode fiyat --worker-id ${i} --total-workers ${FIYAT_WORKERS}`,
  autorestart: true,
  restart_delay: 3000,
  max_restarts: 10000,
}));

module.exports = {
  apps: [
    {
      name: "vatan-api",
      cwd: REPO,
      script: "python3",
      args: "-m uvicorn vatan_bot.api:app --host 127.0.0.1 --port 8080",
      autorestart: true,
      max_restarts: 10,
    },
    {
      name: "vatan-kesif",
      cwd: REPO,
      script: "python3",
      args: "-m vatan_bot.main --mode kesif",
      autorestart: true,
      restart_delay: 43200000,
      max_restarts: 100,
    },
    ...fiyatApps,
    {
      name: "vatan-firsat",
      cwd: REPO,
      script: "python3",
      args: "-m vatan_bot.main --mode firsat",
      autorestart: true,
      restart_delay: 1800000,
      max_restarts: 100,
    },
  ],
};
