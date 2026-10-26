# Decisions

- Every detection is a candidate; no result confirms an oil spill.
- The deterministic offline fixture is SYNTHETIC, represents no incident, and stays visibly labelled in API and UI.
- Zones live in editable data/zones.json. AOIs stay inside 95–104.5°E, 0.8–7°N and at most 60 × 60 km.
- Stored timestamps are UTC. The UI has a UTC+8 display toggle.
- RTC search is preferred. GRD fallback is flagged as radiometrically uncalibrated.
- Real scene processing requires the bundled Natural Earth mask. The app does not invent coastline geometry when the download is missing.
- SQLite is disposable job/cache state; data/archive is the intended durable history.
- The AIS UI stays unavailable until a real server-side relay is connected. Configuring a key alone does not imply vessel data.
- Live wind and currents are Open-Meteo model fields; missing values stay unavailable.
- RTC footprint coverage was verified for one recent 31-day window across all three zones; this is not a guarantee of future coverage. Real-scene accuracy, broad performance benchmarks, hosting, and deployment remain unverified.

- The synthetic raster bypasses sea masking; coast distance is unknown (null) unless an actual bundled coastline is available. Its geometry and measurements remain labelled SYNTHETIC.
- The adaptive threshold default is 1.0 × local spread after the initial 1.8 default failed the synthetic recall gate. This is fixture tuning, not real-scene calibration.
- SQLite job and result-cache queries use SQLAlchemy Core with parameterized statements.
- The first archived real RTC result hit the 500-candidate cap; preserve that QA flag and avoid treating the output as spill evidence.

