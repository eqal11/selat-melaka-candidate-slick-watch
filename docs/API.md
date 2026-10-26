# API

OpenAPI: `/docs`. All endpoints use the `/api/v1` prefix. No endpoint accepts a sample or synthetic mode.

- `GET /health` — API status plus cached Planetary Computer STAC and Open-Meteo reachability statuses (refreshed every 60 seconds).
- `GET /zones`
- `GET /scenes?bbox=west,south,east,north&start=<UTC>&end=<UTC>` — RTC first, GRD fallback flagged; real STAC links and metadata included.
- `POST /analyze` — `{"aoi":[west,south,east,north],"start":"...Z","end":"...Z"}` or `scene_id` with AOI. Returns a real analysis job ID.
- `GET /jobs/{id}`
- `GET /results/{id}` — scene trace, candidates, drift, forcing metadata, QA funnel and preview asset URLs.
- `GET /results/{id}/preview-{raw|filtered}-{fixed|auto}.webp`
- `GET /results/{id}/mask-{land|ship|wind-removed}.webp`
- `GET /results/{id}/pixel?lon=&lat=&variant=raw|filtered`
- `GET /results/{id}/profile/{candidate_id}`
- `GET /history?zone=&start=&end=` — committed real archive only.
- `GET /validation/cases` — source-linked global incident/seep register; cases remain `not_verified` until scene search and detector analysis are actually completed.
- `GET /history/{result_id}/candidates.geojson`
- `GET /history/{result_id}/{raw|filtered}.webp`
- `GET /live/conditions?bbox=` — Open-Meteo source/API and value timestamp included.
- `GET /live/vessels` — throttled SSE from the server-side AIS relay; emits an explicit unavailable status if no server key is configured, otherwise relays positions from a 30-minute bounded ring buffer.

Errors contain the actual reason (for example no matching scene, STAC unavailable, wind unavailable, memory budget exceeded). They never return placeholders. AOIs must stay within 95–104.5°E, 0.8–7°N, each dimension <=60 km. Scene ranges are limited to 31 days. User request JSON is capped at 256 KiB. API is rate limited and CORS origins are allowlisted.
