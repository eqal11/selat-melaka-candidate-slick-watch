# Methodology and limitations

## Scope and honest interpretation

The application screens real Copernicus Sentinel-1 SAR observations for dark-water regions that could merit review. Every detection is a **candidate slick**, never a confirmed spill. Dark radar backscatter is not specific to petroleum. This is educational and research software only; it must not be used for operational, legal, safety, or emergency decisions.

Sentinel-1 is near-real-time at best: catalog and processing latency can be hours, and a location's nominal revisit is roughly 6–12 days. Each displayed/archive result identifies its STAC item, acquisition time UTC, satellite, orbit direction, polarization, age, and QA.

## SAR backscatter and preview

Sentinel-1 is a C-band synthetic aperture radar. VV backscatter is converted to decibels as `10 log10(power)`; non-positive or nodata pixels are invalid. Oil films can damp capillary waves and create low-return patches, but low wind, rain, biogenic films/algae, wakes, island wind shadow, and acquisition geometry can look similar. Bright ships and fixed infrastructure create other artifacts.

The detector's raw and Lee-equivalent filtered arrays both come from the exact AOI read used in analysis. Pixels outside the AOI and nodata are excluded. The server encodes decimated georeferenced WebP previews; map bounds are the AOI bounds and QA records overlap with the item footprint and raster/AOI corner residual. The documented fixed grayscale stretch is **−25 to 0 dB**. Auto stretch clips per-scene percentiles **2–98**. Fixed and auto are display transforms only; they do not change the detector.

## Processing sequence and defaults

1. Search Microsoft Planetary Computer STAC, prefer `sentinel-1-rtc` VV, and verify footprint overlap. Use `sentinel-1-grd` only when no usable RTC item exists; mark the calibration caveat. Read only the AOI window with bounded/dask-backed COG reads. Decimate large AOIs to a working resolution no coarser than the configured memory budget permits; fail explicitly on budget exhaustion.
2. Convert to dB, ignore nodata, and apply a documented Lee-equivalent local speckle smoother for filtered products and detection.
3. Rasterize the configured Natural Earth land polygon and expand it by **2.5 km**. Apply known port buffers (default **3 km**) and bright-target detection plus a **300 m** halo. Offshore platform data is not comprehensive; the result QA flags when that mask is unavailable.
4. Form a local CFAR-like threshold from a **3.5 standard-deviation** depression relative to a local background. Apply global backscatter sanity bounds. This is a transparent heuristic, not a calibrated CFAR probability model.
5. Morphologically close small fragments and merge nearby components. Retain components between **0.03 and 10 km²**, with at least **3 dB** contrast. Reject implausibly elongated or low-compactness shapes and large smooth regions typical of rain cells or island wind shadows. These limits are tunable screening rules; the real scene evaluation is too small to claim accuracy.
6. Wind gate uses scene-time wind from Open-Meteo with a nominal valid interval of **2–10 m/s**. Outside the interval, candidate regions are retained with `wind_out_of_range` and a score penalty rather than silently discarded. Missing wind is null, flagged `wind_unavailable`, and receives no wind-support score. Scene results include a funnel: raw dark pixels, after land, after ship/platform/port, wind-pass/removal/unknown, area components, shape candidates, final candidates.
7. Calculate area in a metric CRS and output polygons in EPSG:4326. Keep output simplified and validate GeoJSON.
8. Add scene-time context, QA (valid pixel %, AOI coverage, wind availability, age, processing duration, working resolution, footprint overlap and corner residual). A zero-candidate result is valid and includes the scene and funnel.

### Heuristic score

Scores are integers **0–100**, not probabilities. The present transparent rule assigns up to 35 points for contrast (`35 × clamp(contrast_dB / 8, 0, 1)`), 15 for elongation (`15 × clamp((elongation − 1) / 4, 0, 1)`), 15 for area (`15 × clamp(area_km² / 0.5, 0, 1)`), 25 for in-window scene-time wind, and 10 for offshore distance (`10 × clamp(coast_km / 5, 0, 1)`). Missing wind gives zero wind points. The final score is capped at 39 for out-of-range wind and 49 for unavailable wind. Bands are Low (0–39), Medium (40–69), and High (70–100). The UI's default threshold of 40 hides Low scores but the threshold can be changed. Inspect `core/scoring.py` for the executable implementation and tests.

## Drift estimate

For each candidate centroid, use the nearest available ocean-current vector plus **3% of the 10 m wind vector**. Integrate in **15-minute** steps to **6, 12, and 24 hours**. The envelope varies windage from **2–4%** and direction by **±20°**. If current is unavailable, use wind only, mark `current_unavailable`, and widen the envelope. This first-order advection sketch is not a full Lagrangian model and omits waves, tides, Stokes drift, weathering, and shoreline interaction.

## Live context and sources

Wind is from Open-Meteo forecast/archive endpoints; current is from Open-Meteo Marine. Values are model output, with source API and timestamp displayed. They are not in-situ measurements. Conditions refresh every 10 minutes. AIS is hidden/unavailable unless a server-side aisstream.io streaming relay is actually configured and connected; a key alone does not mean positions are available.

## Known limitations

- No source-verified offshore slick footprint exists for the incident cases currently listed. Do not compute IoU or distance from place names or released volume.
- Incident matched-scene outcomes and 60-day zone ingestion are reported in `validation/report.md`; they do not establish detector accuracy.
- Candidate counts on a small, mostly unlabelled sample are not a false-alarm rate. A false-alarm rate requires verified negatives and suitable surveyed area.
- Port and offshore-platform masks are incomplete. The QA flag communicates missing platform-mask data.
- RTC footprint overlap does not equal valid ocean pixels. Review per-result AOI coverage and sea-pixel QA.
- Drift and weather context are first-order/model estimates, not operational forecasts.
- Network, STAC, Open-Meteo, or absent-AIS errors are shown directly. No sample/demo content is substituted.