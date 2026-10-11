import json
import pathlib
import sys
import tempfile

import hou
from pxr import Usd, UsdGeom


ROOT = pathlib.Path(__file__).resolve().parents[1] / "B2H_Model_Import"
sys.path.insert(0, str(ROOT / "python"))

import b2h_library


temp = pathlib.Path(tempfile.mkdtemp(prefix="b2h_houdini_test_"))
usd_path = temp / "TestAsset.usda"
stage = Usd.Stage.CreateNew(str(usd_path))
UsdGeom.Xform.Define(stage, "/Asset")
UsdGeom.Cube.Define(stage, "/Asset/Cube_A")
UsdGeom.Cube.Define(stage, "/Asset/Cube_B")
stage.SetDefaultPrim(stage.GetPrimAtPath("/Asset"))
stage.GetRootLayer().Save()

texture_roles = ("basecolor", "ao", "roughness", "metallic", "normal", "opacity", "emission", "transmission", "ior", "displacement")
for role in texture_roles:
    (temp / (role + ".png")).write_bytes(b"\x89PNG\r\n\x1a\nB2H-test")

manifest = {
    "schema_version": 1,
    "asset_id": "automated-test-asset",
    "asset_revision": 1,
    "asset_name": "TestAsset",
    "base_dir": ".",
    "usd_path": usd_path.name,
    "axis_fix_enabled": False,
    "materials": {
        "Red": {"name": "Red", "textures": {role: role + ".png" for role in texture_roles}, "defaults": {"base_color": [1, 0, 0, 1], "roughness": 0.4, "metallic": 0, "displacement_scale": 0.02}},
        "Metal": {"name": "Metal", "textures": {}, "defaults": {"base_color": [0.2, 0.2, 0.2, 1], "roughness": 0.2, "metallic": 1}},
    },
    "assignments": [
        {"object_name": "Cube_A", "safe_object_name": "Cube_A", "materials": ["Red"]},
        {"object_name": "Cube_B", "safe_object_name": "Cube_B", "materials": ["Metal"]},
    ],
}
manifest_path = temp / "TestAsset_bridge.json"
manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

root = hou.node("/")
old_stage = hou.node("/stage")
if old_stage:
    for node in list(old_stage.children()):
        if node.userData("b2h_asset_id") == "automated-test-asset":
            node.destroy()

first = b2h_library.import_b2h_asset(str(manifest_path))
assert first["diagnostics"]["status"] == "SUCCESS", first["diagnostics"]
stage_node = hou.node("/stage")
owned_first = [node for node in stage_node.children() if node.userData("b2h_asset_id") == "automated-test-asset"]
assert len(owned_first) == 3, [node.path() for node in owned_first]
assign = first["assign"]
patterns = [assign.parm("primpattern%d" % index).eval() for index in range(1, assign.parm("nummaterials").eval() + 1)]
assert set(patterns) == {"/Asset/Cube_A", "/Asset/Cube_B"}, patterns
assert all("*" not in pattern for pattern in patterns), patterns

second = b2h_library.import_b2h_asset(str(manifest_path))
owned_second = [node for node in stage_node.children() if node.userData("b2h_asset_id") == "automated-test-asset"]
assert len(owned_second) == 3, [node.path() for node in owned_second]
assert second["diagnostics"]["replaced_nodes"] == 3, second["diagnostics"]

# A bad replacement must not delete the last working import.
broken = dict(manifest)
broken["asset_revision"] = 2
broken["assignments"] = [{"object_name": "Missing_Object", "materials": ["Red"]}]
broken_path = temp / "TestAsset_broken_bridge.json"
broken_path.write_text(json.dumps(broken), encoding="utf-8")
try:
    b2h_library.import_b2h_asset(str(broken_path))
    raise AssertionError("Broken exact assignment unexpectedly succeeded")
except RuntimeError:
    pass
owned_after_failure = [node for node in stage_node.children() if node.userData("b2h_asset_id") == "automated-test-asset"]
assert len(owned_after_failure) == 3, [node.path() for node in owned_after_failure]
print("B2H_HOUDINI_IMPORT_TEST_OK")
