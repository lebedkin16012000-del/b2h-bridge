# B2H Bridge — Blender → Houdini

**Blender add-on: 4.8.4 Beta · Houdini Model Import: 0.5.0**

Automatically bake materials into portable PBR textures and export prepared models to Houdini Solaris / Karma through USD.

## Downloads

- [B2H Bridge 4.8.4 Beta for Blender](downloads/B2H_Bridge-4.8.4-Beta.zip?raw=true)
- [B2H Model Import 0.5.0 for Houdini](downloads/B2H_Model_Import_Houdini_0.5.0.zip?raw=true)

Download these installation packages. The full repository ZIP is a source archive, not the Blender installation package.

## What's new in 4.8.4

- Transfer supported ready-made PBR image maps with **Bake Complex Materials** disabled.
- Export individual RGB or Alpha channels as scalar texture maps, useful for packed PBR textures.
- Recognize direct UV connections and supported tangent-space normal maps using the active render UV map.
- Skip automatic UV preparation when no channels need baking.
- Ignore disconnected normal-related nodes when checking simple material graphs.
- When baking is required but disabled, the error lists the affected channels.

Mapping operations, procedural shaders and other unsupported connections may still require baking. Direct transfer does not guarantee an exact match for every Blender shader.

## Features introduced since the published 4.0.0 Beta

- Baking and export run in a separate Blender process, with progress, estimated time and cancellation.
- Expanded handling of nested groups, Mix Shader, Add Shader, IOR and transmission maps.
- Material reuse, identical-texture deduplication, readable file names and a local bake cache.
- Optional full-tile projection for 3D procedural materials.
- A separate Houdini panel validates exports, builds MaterialX and assigns materials to exact USD paths.
- Reimport updates the asset's network; a failed replacement preserves the previous nodes.

## Important: prepare your model before export

**B2H Bridge is primarily an automatic material-baking and export-preparation tool. You must check UVs yourself. A well-prepared model is essential for a reliable result.**

- In **UV Editing**, check the UV map used for baking. For ordinary single-tile baking, keep islands within 0–1, leave padding and avoid overlaps where different surface details must be written to the same texture.
- A mesh can have multiple materials, but areas baked into a shared texture must not conflict. For a simpler workflow, split the model by material first: **Edit Mode → A → P → By Material**. Check the UVs of every resulting part.
- Separate objects with separate texture sets may use the same 0–1 UV area. The problem is conflicting areas written into the same texture.
- **Split Meshes By Material** helps Houdini assign materials correctly; it does not replace UV checks or model preparation.
- Check material assignments on faces, source texture availability, normals and the model's appearance in Blender. Save a prepared copy of the scene.
- **Rig transfer is currently not recommended. The author was unable to transfer a rig successfully; working rig transfer with this version has not been confirmed.** Start with a static mesh without a rig. Handle rigging and animation separately. Splitting by material clears object animation data on the export copies.

## Step-by-step workflow

### 1. Install the Blender add-on

1. Download **B2H_Bridge-4.8.4-Beta.zip** above.
2. Open **Edit → Preferences → Add-ons → Install from Disk**, select the ZIP and enable **B2H Bridge v4.8.4 Beta**.
3. Open your prepared model and switch to **Object Mode**.
4. Select the mesh objects to export.
5. In the 3D Viewport, press **N**, open the **Houdini** tab and find the **Houdini Bridge** panel.

### 2. Configure the export

The names below use the English interface.

| Section | Setting | What to choose |
| --- | --- | --- |
| Export | **Export Folder** | Destination for the model and textures, for example `D:/B2H_Exports/TestModel`. |
| Export | **Asset Name** | A readable asset name, for example `TestModel`. |
| Export | **Selected Only** | Keep enabled to export selected meshes. |
| Bake | **Bake Complex Materials** | Keep enabled for automatic baking of complex and procedural materials. Disable only when using supported ready-made maps. |
| Bake | **Fast Bake** | Keep enabled to bake only where needed. |
| Bake | **Bake Resolution** | Start with 1024; increase to 2048 or 4096 if needed. |
| Materials | **Split Meshes By Material** | Keep enabled, especially for meshes with multiple materials. |

Leave other settings at their defaults for the first test. Automatic UV options do not guarantee a suitable layout: inspect your UVs yourself.

For ready-made texture maps, you can disable **Bake Complex Materials**. If the exporter reports that a channel requires baking, enable it again or simplify the material connection. RGB/Alpha extraction writes texture files without rendering the material.

### 3. Export

1. Click **Export Stable PBR Bridge** at the bottom of the panel.
2. Wait for completion. The panel shows the current stage, progress and time.
3. Check the export folder for **.usd / .usdc**, **textures/** and **<asset>_bridge.json**. Keep the USD, texture folders and JSON together.
4. If export fails, inspect **<asset>_bake_report.txt** and **<asset>_export_report.txt**, if available.

### 4. Install the Houdini importer on Windows

1. Download **B2H_Model_Import_Houdini_0.5.0.zip** and extract it completely.
2. Close Houdini and run **install_windows.bat**.
3. After successful installation, start Houdini.
4. Open **B2H Model Import v0.5.0** through **Windows → New Pane Tab Type**. If it is listed under a Python Panel submenu, select it there.

### 5. Import the model

1. Click **Select Export Folder**.
2. Choose the Blender **Export Folder** containing **<asset>_bridge.json**.
3. Click **Refresh** and wait for the asset to appear in the table.
4. Select its row and click **Import / Update Selected**.
5. Inspect geometry and materials in **Solaris /stage**, then make a test render in Karma.
6. Read any import warnings, including missing-texture messages.

To update a model, export it again using the same asset name and folder, then click **Refresh → Import / Update Selected** in Houdini. Keep **<asset>_bridge.json** between exports: it stores the identity used for updates.

**Alternative import:** open **COPY_THIS_TO_HOUDINI.txt** in the export folder, copy its command into Houdini's **Windows → Python Shell** and run it.

See the [Houdini installation guide](houdini/README.md) for more details.

## Compatibility and limitations

- The add-on declares Blender 5.0 as its minimum version. The Houdini importer targets Houdini 21.0.559.
- This is a beta. Archive integrity and Python syntax were checked for 4.8.4; end-to-end export and rendering were not run during this publication.
- UDIM is metadata-only; full tiled-image baking is not supported.
- Splitting by material clears object animation data on export copies. Animated models require separate testing.
- Known importer behavior: with a displacement texture connected, a displacement scale of 0 is replaced with 0.01.
- The uploaded installation ZIPs are published unchanged. Repository documentation is maintained separately.

## Source code

Blender source code is in the repository root. Houdini source and its installer are in [houdini/](houdini/). Use the download ZIPs for installation.

## Reporting issues

Include **<asset>_export_report.txt**, **<asset>_bake_report.txt** and **<asset>_assignment_debug.json**, if generated, along with your Blender/Houdini versions and a description of the problem.

## Contacts

- Telegram: [@Neo_Lesha](https://t.me/Neo_Lesha)
- Email: lebedkin16012000@gmail.com
- Telegram channel: [houdini_closet](https://t.me/houdini_closet)

[MIT License](LICENSE)
