# API

Base path: /api/v1. Interactive OpenAPI documentation is at /docs when the API is running.

- GET /health and GET /api/v1/health
- GET /api/v1/zones
- GET /api/v1/scenes?bbox=west,south,east,north&start=ISO-UTC&end=ISO-UTC
- POST /api/v1/analyze with AOI plus date range or scene ID; demo=true runs the deterministic SYNTHETIC fixture
- GET /api/v1/jobs/{id}
- GET /api/v1/results/{id} and /api/v1/results/{id}/preview.png
- GET /api/v1/history?zone=&start=&end=
- GET /api/v1/live/conditions?bbox=west,south,east,north
- GET /api/v1/live/vessels (SSE)

API models validate every analysis result. Bounds and time ranges are constrained. Jobs and result cache are local disposable SQLite/filesystem state; committed archive history is read from data/archive. AIS key setup currently returns an explicit unavailable state because no relay consumer is implemented.
