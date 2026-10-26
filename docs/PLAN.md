# Build plan

1. Core: validated configuration, bounded AOI reads, masks, detector, scoring, drift; numerical tests.
2. API: typed contracts, bounded jobs/cache, preview, archive/history, live conditions/AIS.
3. Validation: measured synthetic experiments and transparent real-data access/coverage report.
4. Pipeline: transactional idempotent ingestion and small durable archives.
5. Frontend: map, offline demo, analysis, history/live, exports and methodology.
6. CI and deployment: pinned dependencies, lint/types/unit/browser gates, Docker Compose.
7. Documentation: verified results, screenshots, decisions, deployment and remaining manual checks.

Real scenes and external services will only be described as verified after actual successful requests. Performance targets are targets until benchmarked.
