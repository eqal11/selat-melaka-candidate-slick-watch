# Build plan

1. Shared processing core: scene discovery, bounded AOI reads, preprocessing, masks, candidate detector, scoring and drift.
2. API: validated real-scene contracts, background jobs, cache, review assets, archive/history and live conditions.
3. Validation: test-only synthetic numerical fixtures, verified public incident searches and explicitly reported real-scene measurements.
4. Pipeline: idempotent ingestion of real scenes with paired small SAR previews.
5. Frontend: real-scene map, image verification, history/live, exports and methodology.
6. CI and deployment: pinned dependencies, Python/TypeScript lint and type checks, tests, Docker Compose.
7. Documentation: measured results, actual-scene screenshots, decisions, deployment steps and remaining gaps.

Only actual external requests and measured outputs are called verified. Hosting, broad accuracy and performance targets remain unverified until measured.
