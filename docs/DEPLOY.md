# Deployment

Deployments have not been created or verified. Use accounts and secrets you control. Deployments and external connectivity were not verified in this run.

## Render Free backend trial

Hugging Face now requires a paid plan to create Docker Spaces. Do not select Gradio as a direct substitute for the existing Dockerfile. Official policy: https://huggingface.co/docs/hub/spaces-overview

Render Free is an alternative trial with 512 MB RAM and 0.1 CPU, not a verified production deployment. No claim is made that it can process a 50 x 50 km SAR AOI or meet the three-minute target. See https://render.com/docs/free and https://render.com/docs/compute-plans .

1. Push the latest commits, including `render.yaml`, to GitHub.
2. Sign into https://dashboard.render.com using GitHub. Create a **Blueprint**, select this repository and the `master` branch, and use `render.yaml` at the repository root. The plan must show **Free** before creation.
3. The blueprint builds the root Dockerfile, uses port 8000 and checks `/health`. It sets one active analysis, an estimated 128 MB working-array budget, no retained in-memory result cache, and one numerical-library thread. The 128 MB estimate excludes interpreter/library overhead and is not a total RAM guarantee. Detector thresholds and scientific parameters are unchanged.
4. Wait for **Live**, then open the service's actual public URL followed by `/health`, `/docs`, `/api/v1/zones` and `/api/v1/validation/cases`. No deployment success is claimed until these return successfully.
5. Deploy Vercel as below using this service URL for `VITE_API_URL`. Set Render's `CORS_ORIGINS` to the exact Vercel HTTPS origin and redeploy the backend.
6. Begin with a small AOI (for example 10 x 10 km). The API rejects requests exceeding its configured estimated memory budget with HTTP 422 before scene search. Check the real job outcome and same-scene SAR overlay. Larger analysis may fail or be rejected; there is no substitute result.

Render Free sleeps after 15 idle minutes and can take about one minute to wake. SQLite/cache is lost on sleep, restart or redeploy; the committed archive stays in Git. Large outbound imagery traffic may trigger free-service restrictions. No AIS key is required for deployment; add it server-side only if needed. Docker build and hosted memory/performance remain unverified because the local Docker Linux engine is not running and no Render service has been created.

### Missing native library during startup

The first Render deployment built the image but exited while importing Rasterio: `ImportError: libexpat.so.1: cannot open shared object file`. The Dockerfile now installs Debian `libexpat1`, then imports Rasterio and the API as the non-root runtime user during build. The CI container job also starts the actual Linux image and checks `/api/v1/zones` and `/api/v1/validation/cases`. These checks detect missing native libraries or packaged resources before release. The corrected Linux build has not yet been run locally because the Docker engine is stopped. After pushing the fix, verify the new deployment logs show successful startup before treating it as live. Debian package: https://packages.debian.org/trixie/libexpat1 .

## Frontend on Vercel

1. Push this repository to GitHub and import it as a new Vercel project.
2. Set the project root directory to web. Vercel should detect Vite; build with npm run build and publish dist.
3. Add VITE_API_URL as the public HTTPS base URL for the API, with no trailing slash.
4. Add the exact Vercel deployment origin to the backend CORS_ORIGINS setting.
5. Deploy, then check the browser console, API health URL, map tiles, and the real Sentinel-1 analysis and SAR preview.

Vercel's Vite guidance: https://vercel.com/docs/frameworks/frontend/vite

## Backend on Hugging Face Spaces

1. Docker Space creation currently requires a paid account plan. Proceed only if you choose that cost; this is not a free-hosting instruction. Create a Docker Space in an account or organization you control.
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
