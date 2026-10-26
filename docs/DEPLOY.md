# Deployment

Deployments have not been created or verified. Use accounts and secrets you control. Deployments and external connectivity were not verified in this run.

## Frontend on Vercel

1. Push this repository to GitHub and import it as a new Vercel project.
2. Set the project root directory to web. Vercel should detect Vite; build with npm run build and publish dist.
3. Add VITE_API_URL as the public HTTPS base URL for the API, with no trailing slash.
4. Add the exact Vercel deployment origin to the backend CORS_ORIGINS setting.
5. Deploy, then check the browser console, API health URL, map tiles, and the real Sentinel-1 analysis and SAR preview.

Vercel's Vite guidance: https://vercel.com/docs/frameworks/frontend/vite

## Backend on Hugging Face Spaces

1. Create a Docker Space in an account or organization you control.
2. Push the repository contents to the Space. The root Dockerfile builds the API; the Spaces metadata is already at the top of README.md with sdk: docker and app_port: 8000.
3. In Space settings, add CORS_ORIGINS as the exact Vercel origin, APP_DATA_DIR=/app/var, and optionally AISSTREAM_API_KEY as a server-side secret.
4. Wait for the Docker build, then verify /health and /docs on the Space URL.
5. Set VITE_API_URL on Vercel to that API URL and redeploy the frontend.
6. The server-side AIS relay is implemented. Store `AISSTREAM_API_KEY` as a Hugging Face secret, then open `/api/v1/live/vessels` and confirm the SSE status changes to `connected` and emits positions. If no key is configured, the endpoint emits an explicit unavailable status and closes. The key is never exposed to Vercel or the browser.

Hugging Face Docker Space documentation: https://huggingface.co/docs/hub/spaces-sdks-docker

The free Space filesystem may be ephemeral. SQLite is only cache/job state; durable history comes from data/archive in the repository. A Vercel frontend and Hugging Face backend on separate origins need correct CORS and public connectivity.

## GitHub Actions archive

1. Push the repository to GitHub.
2. In repository settings, allow the workflow token to write repository contents.
3. Enable Actions and run Daily archive ingestion manually once.
4. Inspect logs and the proposed data/archive diff. Successful runs commit only after the pipeline exits cleanly.
5. Keep total committed archive data below 50 MB.

## Accounts and keys still needed

- GitHub repository and Actions contents write permission for scheduled archive updates.
- Vercel account/project for the static frontend.
- Hugging Face account and Docker Space for the API.
- Optional aisstream.io key, stored in backend secrets only. AIS availability still depends on the server secret and outbound websocket access to aisstream.io.
- No Planetary Computer user key is configured by this repository. Real STAC metadata search worked anonymously in this verification run; asset signing and data access succeeded for the archived RTC scene.
