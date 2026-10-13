# Changelog

## 4.8.4 Beta — October 13, 2026

- Added direct transfer of supported ready-made PBR images with complex-material baking disabled.
- Added RGB/Alpha channel extraction for scalar PBR maps.
- Expanded direct UV-image and tangent-space normal-map recognition.
- UV preparation now runs only when baking is required.
- Normal detection ignores disconnected nodes in simple material graphs.
- Baking-disabled errors now identify channels that require baking.
- Updated repository documentation to English, including preparation and step-by-step instructions.

## 4.8.3 Beta + Houdini Model Import 0.5.0 — October 12, 2026

Update from the previously published 4.0.0 Beta; intermediate versions are not listed separately.

### Blender

- Background export with progress, estimated time and cancellation.
- Handling of nested groups, Mix/Add Shader, IOR and transmission.
- Material reuse, identical-texture deduplication and local caching.
- Readable texture names and optional projection across the full UV tile.
- Asset identity and revision stored in manifest schema 1.

### Houdini

- Separate asset-library panel and Windows installer.
- Export validation and missing-texture diagnostics.
- Exact material assignments using USD paths.
- Asset updates without duplicate networks.
- Preservation of the previous nodes if an update fails.
- MaterialX construction with PBR maps, AO, normal, opacity, emission, transmission, IOR and displacement.

Installation ZIPs were published without code changes. See the README for limitations and validation status.

## B2H Bridge v4.0.0 Beta

### Changes since v3.0.1

- Reworked the add-on into a clearer modular structure.
- Updated the Blender interface and organized export settings into focused sections.
- Improved texture handling and portable texture export.
- Added texture deduplication and cleanup of unreferenced exported textures.
- Improved bake stability, including controlled partial baking and GPU bake options.
- Improved reconstruction of materials for Houdini, including MaterialX-oriented output.
- Improved overall pipeline stability, diagnostics, and export feedback.

### Beta notes

- This is a work-in-progress beta release.
- Validate generated USD, texture paths, MaterialX files, and material assignments on your target Houdini setup before production use.
