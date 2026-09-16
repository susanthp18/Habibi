# CloudUnity — beeonixpayint.bigtapp.net

Shared VM (`20.205.178.161`). Other products already occupy 80/443, 5432–5439, 6379, 8001/8006/8008, 8080–8084, 9000–9001. This overlay uses **unused loopback ports only**. It does not replace existing nginx sites.

| Process | Bind | Why this port |
|---|---|---|
| Habibi UI | `127.0.0.1:3108` | 8080 is SearxNG |
| FastAPI | `127.0.0.1:8100` | keep a PayInt block; 8000 is unused but 8001+ are taken |
| Voice | `127.0.0.1:7860` | free |
| Postgres | `127.0.0.1:5440` | 5432–5439 taken |
| MinIO | `127.0.0.1:9102` / `9103` | 9000–9001 are EIP MinIO |

Do not publish these on `0.0.0.0`. Do not `certbot` a name that is not `beeonixpayint.bigtapp.net`. Do not `nginx -s reload` until `nginx -t` is clean.

## Bring the API up (does not start other compose projects)

```bash
cp deploy/cloudunity/compose.env.example deploy/cloudunity/compose.env
# Fill secrets in backend/.env on the server. Never commit that file.
cd backend
docker compose --env-file ../deploy/cloudunity/compose.env -f docker-compose.yml up -d
```

Compose project name stays `backend` (directory name) unless you set `-p payint`. Container names are `collections_*`, which were not in use on this VM.

## UI

```bash
cd Habibi
cp ../deploy/cloudunity/habibi.env.example .env.production
npm run build
npx vite preview --host 127.0.0.1 --port 3108
```

## nginx (after DNS already points here)

```bash
sudo cp deploy/cloudunity/nginx/beeonixpayint.bigtapp.net.conf \
  /etc/nginx/sites-available/beeonixpayint_config
sudo ln -s /etc/nginx/sites-available/beeonixpayint_config /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d beeonixpayint.bigtapp.net
```
