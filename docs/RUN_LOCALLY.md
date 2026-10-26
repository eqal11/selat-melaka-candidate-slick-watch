# Running real-data validation locally

The current hosted/sandbox shell cannot reach external services (`PermissionError(13)` before an HTTP response). These commands are intended for a normal terminal with outbound HTTPS. No API keys are needed for Planetary Computer STAC, Copernicus STAC/OData, ASF, or Open-Meteo.

Use Python 3.11 and install the locked environment:

```powershell
uv sync --frozen --extra dev
```

Connectivity-only check (prints HTTP codes and writes `validation/results/connectivity-latest.json`):

```powershell
uv run python -m pipeline.run_validation --dry-run
```

Search incidents ±3 days and sample ten acquisition dates per seep site; checkpoints are written after each case and retained for resume:

```powershell
uv run python -m pipeline.run_validation --resume --seep-start 2017-01-01 --seep-end 2026-10-26
```

Run the normal daily archive ingestion (the operation remains idempotent by zone and scene ID; archive is committed only after all requested scenes finish and the 50 MiB cap is checked):

```powershell
uv run python -m pipeline.run_ingest --days 60
```

Connectivity-only ingestion check:

```powershell
uv run python -m pipeline.run_ingest --dry-run
```

The current validation runner searches Planetary Computer and Copernicus STAC catalogs when coordinates exist. ASF is included in the connectivity gate but not integrated into scene query/normalization. It records unsearchable cases explicitly when source coordinates are absent. It currently does not raster-process global cases: its case AOIs lie outside the Strait-only result schema. Do not treat scene discovery as detector validation. A case-scoped global AOI processing extension and real-scene processing remain required before claiming worldwide detection outcomes.
