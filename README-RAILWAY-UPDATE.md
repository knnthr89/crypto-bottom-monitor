# Railway deployment and Android configuration

## Railway
1. Deploy this repository from GitHub in Railway.
2. The root `railway.toml` selects `backend/Dockerfile` and configures `/health`.
3. Generate a public domain in Railway Networking.
4. Set `DB_PATH=/data/monitor.db` in Railway Variables.
5. Add a Railway Volume mounted at `/data` if validation imports must persist across redeploys.
6. Optional variables: `COINGLASS_API_KEY`, `GOOGLE_TRENDS_GEO`, `ETF_FLOWS_CSV`.
7. Check `https://YOUR-DOMAIN/health`, then `/docs`.

Railway's injected `PORT` is now used by the Docker start command. Keep API keys in Railway Variables, never in Android or Git.

## CoinGlass Hobbyist fallback
If CoinGlass spot CVD is unavailable, the backend uses Binance spot kline taker-buy quote volume to estimate taker-sell volume and builds a cumulative directional flow proxy. The app labels this as **Spot taker flow (proxy)**. It is not true aggregated CVD.

## Android build
The app defaults to `http://10.0.2.2:8000/` for the Android emulator. To build against Railway:

```bash
./gradlew assembleDebug -PBACKEND_BASE_URL=https://YOUR-RAILWAY-DOMAIN/
```

Or set `BACKEND_BASE_URL` in the environment. The app version becomes `0.2.0`.
