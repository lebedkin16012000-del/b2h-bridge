# B2H Model Import 0.5.0

Houdini 21 importer for models, materials, and textures exported from Blender
with **B2H Bridge 4.8.1 Beta** or newer.

## Features

- Editable USD geometry import into Solaris.
- Karma MaterialX networks for Base Color, AO, Roughness, Metallic, Normal,
  Opacity, Emission, Transmission, IOR, and Displacement.
- Exact material bindings resolved from USD primitive paths.
- Idempotent updates by stable asset identity.
- Transactional replacement that preserves the previous working import when
  an update fails.
- Schema validation, explicit diagnostics, background scans, and progress UI.

## Windows installation

1. Extract the entire release archive.
2. Close Houdini.
3. Run `install_windows.bat`.
4. Restart Houdini.
5. Open **Windows → New Pane Tab Type → B2H Model Import v0.5.0**.

The installer detects **all Houdini versions** from Documents, OneDrive, and
Program Files. It configures the package and Python Panel for every detected
version while installing the shared application files only once under:

`%LOCALAPPDATA%\B2H\ModelImport\0.5.0`

To select one or more Houdini user folders explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_windows.ps1 `
  -HoudiniUserDir "C:\Users\USERNAME\Documents\houdini20.5", `
                  "C:\Users\USERNAME\Documents\houdini21.0"
```

For manual installation, copy `B2H_Model_Import` to a permanent directory,
copy its `.pypanel` file into the Houdini `python_panels` directory, and edit
`B2H_Model_Import.package.example.json` with the permanent path before placing
it in the Houdini `packages` directory.

## Using the importer

1. Export a prepared model from Blender with B2H Bridge.
2. Keep **Split Meshes By Material** enabled for meshes with multiple materials.
3. Click **Select Export Folder** and choose the folder containing the exported bridge JSON.
4. Click **Refresh**, select the asset, then click **Import / Update Selected**.

Reimporting the same `asset_id` updates only its B2H-owned nodes. User-created nodes in `/stage` are not removed. Check geometry, materials and a test render after importing.

## Installation backups

The installer backs up replaced package and panel files in `b2h_backup` inside each Houdini user directory.

## Developer validation

Run the included regression script with Houdini's Python interpreter:

```powershell
& "C:\Program Files\Side Effects Software\Houdini 21.0.559\bin\hython.exe" `
  .\tests\test_houdini_import.py
```

## Requirements and compatibility

- Tested with Houdini 21.0.559.
- Blender regression suite passed with Blender 5.1.
- B2H Bridge manifest schema v1.
- Windows 10/11 installer.

Keep **Split Meshes By Material** enabled in Blender for meshes with multiple
materials. This gives the importer an exact USD primitive for every binding.

## License

MIT. See `LICENSE`.
