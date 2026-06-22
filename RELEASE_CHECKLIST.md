# Release checklist — B2H Bridge v4.0.0 Beta

Use this checklist before publishing a release or sharing a build.

- [ ] Install the `B2H_Bridge` folder in Blender 5.1 and enable the add-on.
- [ ] Export a simple PBR asset with base color, roughness, metallic, and normal textures.
- [ ] Export an asset with alpha/foliage material and verify opacity handling.
- [ ] Export an asset with a procedural material and confirm the required channels are baked.
- [ ] Open `COPY_THIS_TO_HOUDINI.txt` and confirm it points to the generated `import_to_houdini.py`.
- [ ] Paste the generated command into Houdini 21.0.559 Python Shell and run it.
- [ ] Verify generated MaterialX files and their networks in Houdini/Karma.
- [ ] Verify all texture paths resolve and no required texture path is empty.
- [ ] Verify material assignments on imported geometry.
- [ ] Review `<asset>_export_report.txt`, `<asset>_bake_report.txt`, and `<asset>_assignment_debug.json` for warnings.
- [ ] Confirm the release archive contains no `__pycache__`, `.pyc`, temporary Blender files, local exports, or logs.