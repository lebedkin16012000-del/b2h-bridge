# B2H Bridge v4.0.0 Beta

> **Beta / Work In Progress** — please test the add-on on a copy of production assets before relying on it in a production pipeline.

B2H Bridge is a Blender add-on for preparing Blender assets for Houdini look-development workflows. It exports USD geometry, creates portable PBR textures when needed, writes MaterialX data, and generates a Houdini Python import script.

## Supported versions

- Blender **5.1**
- Houdini **21.0.559**

## What it does

- Analyses Blender material graphs and preserves straightforward PBR texture connections.
- Bakes complex, procedural, alpha, and normal-map channels when required.
- Deduplicates and cleans up exported texture sets.
- Exports USD geometry with material assignments.
- Generates MaterialX files and a Houdini Python importer for Karma-oriented workflows.
- Creates debug files for assignments, bake activity, and the complete exported material/texture summary.

## Quick start

1. Download the release ZIP and extract it.
2. Copy the extracted `B2H_Bridge` folder to Blender's add-ons folder:
   `%APPDATA%\Blender Foundation\Blender\5.1\scripts\addons\`.
3. In Blender open **Edit → Preferences → Add-ons** and enable **B2H Bridge v4.0.0 Beta**.
4. Open the scene containing the mesh asset and its materials.
5. In the 3D Viewport press `N`, open the **Houdini** tab, and configure the export folder and asset name.
6. Select the desired bake, material, and Houdini options, then click **Export Stable PBR Bridge**.
7. After a successful export, open `COPY_THIS_TO_HOUDINI.txt` from the export folder.
8. Copy its generated Python command into Houdini's **Python Shell** and execute it.
9. Inspect the imported geometry, material assignments, MaterialX networks, and texture paths in Houdini.

## Export output

An export folder normally contains:

- `<asset>.usd` or `<asset>.usdc` — geometry export
- `textures/` — copied or baked PBR textures
- `materialx/` — MaterialX files and manifest
- `import_to_houdini.py` — generated Houdini importer
- `COPY_THIS_TO_HOUDINI.txt` — the command to paste into Houdini's Python Shell
- `<asset>_export_report.txt` — readable material, texture, bake, and script-path report
- `<asset>_assignment_debug.json` — material assignment diagnostics
- `<asset>_bridge.json` — bridge metadata consumed by the importer

## Installation notes

This is a folder-based Blender add-on. Keep the `B2H_Bridge` folder intact; do not install an individual Python file. The add-on requires Blender's bundled `bpy` module and is therefore not intended to run as a standalone Python program.

## Development and reporting issues

Please attach the generated `<asset>_export_report.txt`, `<asset>_bake_report.txt`, and `<asset>_assignment_debug.json` when reporting an export issue.

## Contacts

- Telegram: [@Neo_Lesha](https://t.me/Neo_Lesha)
- Email: [lebedkin16012000@gmail.com](mailto:lebedkin16012000@gmail.com)
- Telegram channel: [houdini_closet](https://t.me/houdini_closet)
## License

B2H Bridge v4.0.0 Beta is released under the [MIT License](LICENSE).
