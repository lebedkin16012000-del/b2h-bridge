# Changelog

## 0.5.0 — Stage 10: Unified Production Importer

- Split active code into manifest, MaterialX, importer, facade and UI layers.
- Added schema v1 validation and normalized legacy texture role aliases.
- Made reimport idempotent by stable `asset_id` and B2H ownership tags.
- Made updates transactional so a failed replacement preserves old nodes.
- Replaced broad substring material patterns with exact USD primitive paths.
- Added base color, AO, roughness, metallic, normal, opacity, emission,
  transmission, IOR and displacement MaterialX handling.
- Added explicit MaterialX output wiring and failed-material cleanup.
- Added honest SUCCESS / SUCCESS WITH WARNINGS / FAILED diagnostics.
- Moved bounded disk scans to a worker thread and added import progress.
- Made the panel and generated B2H import script use the same public importer.

## Stage version history

- 0.4.1 — Stage 1: Portable Installation
- 0.4.2 — Stage 2: Clean Module Structure
- 0.4.3 — Stage 3: Manifest Schema Validation
- 0.4.4 — Stage 4: Idempotent Reimport
- 0.4.5 — Stage 5: Exact Material Assignments
- 0.4.6 — Stage 6: Complete PBR Mapping
- 0.4.7 — Stage 7: Reliable MaterialX Networks
- 0.4.8 — Stage 8: Honest Import Status
- 0.4.9 — Stage 9: Responsive Panel
- 0.5.0 — Stage 10: Unified Production Importer
