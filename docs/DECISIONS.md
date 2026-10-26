# Decisions

- Every detection is a candidate slick, never a confirmed spill. UI and README carry an educational/research disclaimer.
- The application and API have no demo mode, synthetic fallback, or placeholder result. Synthetic pixels are test-only in `/tests` and are never imported by `/core`, `/api`, `/pipeline`, or `/web`.
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
- AIS stays unavailable until a functioning server-side streaming relay exists. A key by itself is insufficient; keys never enter browser code.
- API source metadata and error reasons are shown directly. Network/data failures never produce a substitute result.
