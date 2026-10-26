# Validation report

## Executed checks

- `.venv/Scripts/python.exe -m pytest -q`: **16 passed**, 4 third-party deprecation warnings, 3.83 seconds.
- `.venv/Scripts/python.exe -m pytest tests/test_core.py::test_synthetic_recall_area -s -q`: **1 passed**; synthetic recall **0.877171**, relative pixel-area error **0.122829**.
- `.venv/Scripts/ruff.exe check core api pipeline tests`: **passed**.
- `.venv/Scripts/mypy.exe --follow-imports=skip --no-incremental core api pipeline`: **passed**, 19 Python source files.
- `npm run lint`: **passed**.
- `npm run build`: **passed** (TypeScript and Vite); initial bundle warning: 1.20 MB minified / 336 kB gzip. History and drift are code-split.
- `npm test`: **passed**, 2 Zod schema tests.
- `npm ci` hit Windows EPERM while replacing native package binaries; `npm install` restored the exact lockfile dependencies. The workflow uses `npm ci`, which still needs a clean Linux runner verification.
- `PLAYWRIGHT_BROWSERS_PATH=work/pw-browsers npx playwright install chromium; npm run e2e -- --reporter=line`: **passed**, 1 browser smoke test. It loads the app, forces API failure, and verifies the local SYNTHETIC fallback. Captured screenshot: docs/screenshots/offline-demo.png.
- FastAPI TestClient: GET health/zones and offline POST analyze → GET job → GET result passed; response contained three SYNTHETIC candidates and 6/12/24-hour drift envelopes.
- `docker compose config`: **passed**.
- `docker compose --progress plain build`: **not completed**; Docker Desktop Linux engine pipe was absent after the buildx lock access was resolved. `docker compose up` therefore remains unverified.

## Real scene coverage and analysis

For 2026-09-26 through 2026-10-26 UTC, the Planetary Computer STAC search returned 8 RTC items with VV for each zone. The best usable footprints covered 100% of each configured AOI; after the app's 80% threshold, usable RTC counts were North **4**, Central **2**, South **5**. Coverage means STAC footprint intersection, not valid ocean pixel coverage.

The archived real-scene command was:

```powershell
.venv/Scripts/python.exe -m pipeline.analyze_scene --zone central --scene-id S1D_IW_GRDH_1SDV_20261014T113320_20261014T113345_005011_009780_rtc --force
```

The scene acquired at 2026-10-14 11:33:32 UTC (about 279 hours old at processing) loaded Sentinel-1 RTC VV at 30 m. Measured QA: valid pixels **100.0%**, AOI coverage **100.0%**, sea pixels after Natural Earth mask **95.116%**, wind available, processing **60.56 seconds**. It yielded **500 candidates** (the configured output cap) with total candidate polygon area **50.590 km²**. The result and simplified candidate GeoJSON are archived under data/archive/central/2026-10-14; GeoJSON size is about 1.34 MB.

These are algorithm outputs for an observation, **not verified oil slicks**. Reaching the 500-candidate cap and the high mapped area indicate likely substantial false positives and require visual/ground-truth review. No claim of a spill is made.

The exact coverage and land-mask probes were temporary scripts under work/coverage_probe.py and pipeline.fetch_land. The latter downloaded the Natural Earth 1:10m public-domain polygon source and generated data/land/natural-earth.geojson plus its source checksum metadata.

## Synthetic fixture

The deterministic 512 × 640, 30 m raster contains two injected dark shapes, gamma speckle noise, and a bright ship-like cluster. With threshold multiplier 1.0, measured recall is **0.877171** and relative pixel-area error is **0.122829**. The synthetic fixture bypasses land masking. These values are not real-world accuracy.

## Remaining validation gaps

- No documented real spill incident cases are in validation/cases.yaml; it remains a clearly marked placeholder because date, location, and extent have not been verified from reliable public sources.
- False-alarm rate per known no-spill scene or per 1000 km²: not measured.
- Open-Meteo live conditions: GET /api/v1/live/conditions returned HTTP 200 with wind and ocean-current model vectors at all three grid points on 2026-10-26 UTC; all were labelled MODEL.
- AIS: the relay consumer is not connected. A key does not enable vessel data; API/UI state this.
- Full Docker image build and deployment to Vercel or Hugging Face: not verified.
- Performance targets beyond the single 60.56-second central zone processing run: not benchmarked.
- Drift is a first-order estimate, not a full Lagrangian model.



