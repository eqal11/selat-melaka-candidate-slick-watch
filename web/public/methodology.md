# Methodology and limitations

All mapped detections are **candidate slicks**, never confirmed spills. Educational and research use only; not for operational, legal, or emergency decisions.

## Sentinel-1 SAR

Sentinel-1 measures microwave backscatter. Oil films can damp short waves and appear darker in VV backscatter, but darkness is not unique to oil. Low winds, rain cells, algae, ship wakes, biogenic films, and island wind shadows can look similar. Sentinel-1 is near-real-time at best (often hours of latency) and revisits roughly every 6–12 days, depending on orbit and location.

The app searches Microsoft Planetary Computer Sentinel-1 RTC VV first. It checks footprint overlap and requires 80% of the AOI. When RTC coverage is insufficient, the code tries Sentinel-1 GRD. The current GRD fallback scales digital numbers to a nominal background and is not calibrated sigma-nought; output is explicitly flagged.

## Detection defaults

Working resolution is 30 m (20–40 m allowed). Convert power to dB using 10 log10(power). A 5-pixel local-moment Lee-equivalent filter reduces speckle. Adaptive threshold defaults to local mean minus 1.8 × max(local standard deviation, 0.5 dB) within a 51-pixel window. Dark backscatter is bounded from −35 to −17 dB. Morphological opening/closing removes speckle fragments. Minimum area is 0.025 km²; output geometry simplification is half a pixel. Real processing uses a 1.5 km Natural Earth coast buffer. AOI loading is bounded by a 384 MB estimated working-memory budget.

Wind outside 2–10 m/s keeps candidates with wind_out_of_range and caps the score at 39. Missing wind is flagged and caps score at 49.

## Heuristic score, not probability

Five components sum to a 0–100 review heuristic:
- Contrast: 35 × clamp(contrast_db / 8, 0, 1), maximum 35.
- Elongation: 15 × clamp((elongation − 1) / 4, 0, 1), maximum 15.
- Size: 15 × clamp(area_km² / 0.5, 0, 1), maximum 15.
- Wind: 25 points when available and within the configured gate, otherwise 0.
- Offshore distance: 10 × clamp(distance_to_coast_km / 5, 0, 1), maximum 10.

Bands: Low (<40), Medium (40–69.9), High (70–100). These are not calibrated confidence or probability.

## Drift

First-order velocity is ocean current + 3% of 10 m wind, integrated at 15-minute intervals for 6, 12, and 24 hours. Envelopes sample windage 2%, 3%, 4% and direction offsets −20°, 0°, +20°, then expand for unresolved uncertainty. Missing current triggers wind-only drift, a wider envelope, and current_unavailable. This is not a full Lagrangian model; waves, mixing, shore interaction, and evolving weather are omitted.

## Sources

Copernicus Sentinel data via Microsoft Planetary Computer STAC; Open-Meteo forecast/archive and marine APIs; Natural Earth public-domain land polygons; OpenStreetMap contributors; optional aisstream.io vessel feed.
