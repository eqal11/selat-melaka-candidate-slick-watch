# Running real-data validation locally

The validation runner checks the live catalog endpoints, searches real Sentinel-1 RTC/GRD items, then loads and processes selected scenes for cases with source-published coordinates. Processing uses a separate 0.12° case window whose geodesic width and height must remain at or below 60 km. These case windows do not change the app's Strait-only AOI limits.

Python 3.11 is required. This checkout already has a project virtual environment; if it exists, `uv` is not required. From the repository root in PowerShell, run the detector validation with:

```powershell
.\.venv\Scripts\python.exe -m pipeline.run_validation --resume
```

The command prints a line for each case and each processed scene. It writes case summaries to `validation/results/cases/{case-id}.json`; processed scene JSON and raw/filtered WebP previews are written below `validation/results/cases/{case-id}/`. The API exposes those real results to the Validation cases tab after its page is refreshed. A candidate count of zero is a valid result. Scene-search success alone is not a detector result.

`--resume` skips cases already marked processed and retries incomplete searches/processing. Omit `--resume` to repeat every search and processing run. Add `--case-id gc600-gulf-of-mexico-natural-seep` to run just one named case while debugging. `--search-only` performs catalog searches without raster loading. `--dry-run` checks connectivity only and does not search for scenes or run the detector.

To change the seep sampling period, pass explicit UTC calendar dates, for example:

```powershell
.\.venv\Scripts\python.exe -m pipeline.run_validation --resume --seep-start 2017-01-01 --seep-end 2026-10-26
```

The runner uses only numeric coordinates already recorded in `validation/cases.yaml`; it does not geocode descriptive place names or invent coordinates. Cases without source coordinates remain marked unsearchable. Scene processing requires a matching Planetary Computer item with usable assets. Copernicus or ASF metadata matches without those assets are reported as not processed. A catalog error such as HTTP 429 is preserved in the case output and means the cross-catalog search is incomplete.

The detector reports candidate slicks only, never confirmed spills. The reported slick dimensions in case sources are descriptive; the runner does not compute IoU without a georeferenced reference boundary. Current wind and ocean-current data may be unavailable for historical acquisition times; those cases retain the documented flags and are not silently discarded.

The normal daily archive ingestion is separate from case validation and writes only the Strait study zones:

```powershell
.\.venv\Scripts\python.exe -m pipeline.run_ingest --days 60
```
