# Decisions

- Every detection is a candidate slick, never a confirmed spill. UI and README carry an educational/research disclaimer.
- The application and API have no sample mode, synthetic fallback, or placeholder result. Synthetic pixels are test-only in `/tests` and are never imported by `/core`, `/api`, `/pipeline`, or `/web`.
- Every result must validate against the exact real STAC item, including sensor platform, orbit, VV polarization, acquisition time, and STAC href; missing trace metadata fails processing.
- RTC VV is preferred. If no >=80%-overlap RTC scene exists, GRD is attempted and flagged radiometry-uncalibrated. Coverage and calibration limitations are visible.
- The detector uses 3.5 local standard deviations, 0.03–10 km² component area, 3 dB contrast, 2.5 km coast buffer, 3 km known port buffer, bright-target mask/halo, and shape filters. These are transparent screening parameters, not calibrated accuracy claims.
- Wind outside 2–10 m/s does not silently remove candidate pixels: candidates remain with an out-of-range flag and reduced score. Missing scene-time wind keeps candidates visible with an unavailable flag and no wind score; the null is not replaced with a fabricated value.
- SAR images are generated from the exact raw/filtered arrays in the analysis, reprojected to AOI bounds, and stored as small WebP. Fixed stretch is -25 to 0 dB; auto stretch is p2–p98. Polygon overlays use the detector's filtered mask from the same scene.
- Map checks include raster/AOI corner residual and image-AOI overlap with the STAC footprint. Natural Earth land is buffered 2.5 km; platform masking is incomplete unless optional asset data exists, and QA states this.
- Reviewer checklist and notes are stored in browser localStorage and can be exported. They are the user's independent assessment, not system confirmation.
- Three incident reports have multiple authoritative sources. Reported spill volume or affected shoreline is not treated as a slick geometry. Scene matches and detector outcome are reported separately.
- Times are stored in UTC. UTC+8 is display-only. AOIs are bounded to 95–104.5°E, 0.8–7°N and 60×60 km maximum.
- SQLite is ephemeral job/cache state; only successful real results enter the committed archive. Each archived scene has GeoJSON and raw/filtered fixed-stretch WebP. Empty candidate arrays are valid observations.
- AIS uses a server-side websocket relay, a bounded 30-minute position buffer, and 15-second SSE updates. It is not verified without a configured server key and reachable aisstream.io; the key never enters browser code.
- API source metadata and error reasons are shown directly. Network/data failures never produce a substitute result.

- Hardening pass (2026-10-26): area, contrast, shape, large-smooth-region, wind-out-of-range and wind-unavailable rejections are represented as reason-coded `filtered` features. They are excluded from accepted-candidate totals, hidden by default, and receive a proportionally scaled heuristic breakdown capped at 19; the user can reveal them explicitly. The 23 archived scenes have not yet been reprocessed with this change, so no revised count or candidate density is claimed.
- Global incident/seep validation remains a separate evidence workflow. The Strait result schema continues to enforce the study bounds; the validation runner must not present an STAC match as a detector outcome. Catalog matches outside the bounds are not processed until case-scoped geometry validation and raster limits are implemented.
- The manual dry-run checks Planetary Computer STAC, Copernicus STAC/OData, ASF, Open-Meteo forecast and Marine. This environment returned no HTTP response due to `PermissionError(13)`; no catalog or weather result is inferred from that.
