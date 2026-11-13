#!/usr/bin/env python3
"""
test_downloader.py - offline tests for download_mods.py (no network needed).

Covers the parts that actually decide "which jar do I install":
  * version comparison
  * Maven resolution (JEI 19.x scheme, Mekanism 1.21.1-10.7.x scheme)
  * GitHub release-asset matching (Mekanism vs MekanismTools)
  * Modrinth version picking (newest release, never a sources jar)

Usage: python3 tools/test_downloader.py
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("dm", ROOT / "download_mods.py")
dm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dm)

FAILS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILS.append(name)


# ---------------------------------------------------------------------------------------
print("- version_key")
check("19.70 > 19.21", dm.version_key("19.70.0.469") > dm.version_key("19.21.1.300"))
check("21.1.10 > 21.1.9", dm.version_key("21.1.10") > dm.version_key("21.1.9"))
check("1.21.1-10.7.19 > 1.21.1-10.7.9", dm.version_key("1.21.1-10.7.19.85") > dm.version_key("1.21.1-10.7.9.80"))

# ---------------------------------------------------------------------------------------
print("- mc version matching")
check('"1.21.1" in text', dm.mc_in("exdeorum-3.12+1.21.1", "1.21.1"))
check('"1.21.11" is not 1.21.1', not dm.mc_in("ImmediatelyFast-NeoForge-1.14.3+1.21.11", "1.21.1"))
check('"1.21.10" is not 1.21.1', not dm.mc_in("mod-1.21.10.jar", "1.21.1"))

# ---------------------------------------------------------------------------------------
print("- maven: JEI uses 19.x for MC 1.21.x")
JEI_META = ("<metadata><versions><version>19.8.4.110</version>"
            "<version>19.21.1.300</version><version>19.70.0.469</version>"
            "<version>26.1.0.1</version></versions></metadata>")
dm.http_text = lambda url: JEI_META
dm.url_exists = lambda url: "19.70.0.469" in url
jei = {"name": "JEI", "id": "jei", "maven": {
    "repo": "https://maven.blamejared.com", "group": "mezz/jei",
    "artifact": "jei-1.21.1-neoforge", "version_regex": r"^19\."}}
rec = dm.maven_lookup(jei, "1.21.1", "neoforge")
check("JEI resolved", rec is not None)
if rec:
    check("JEI newest 19.x", rec["version"] == "19.70.0.469", rec["version"])
    check("JEI url",
          rec["url"] == "https://maven.blamejared.com/mezz/jei/jei-1.21.1-neoforge/19.70.0.469/jei-1.21.1-neoforge-19.70.0.469.jar",
          rec["url"])

print("- maven: Mekanism uses 1.21.1-10.7.x")
MEK_META = ("<metadata><versions><version>10.7.19.85</version>"
            "<version>1.21.1-10.7.19.85</version>"
            "<version>1.20.1-10.4.16.80</version></versions></metadata>")
dm.http_text = lambda url: MEK_META
dm.url_exists = lambda url: "1.21.1-10.7.19.85" in url
mek = {"name": "Mekanism", "id": "mekanism", "maven": {
    "repo": "https://modmaven.dev", "group": "mekanism", "artifact": "Mekanism"}}
rec = dm.maven_lookup(mek, "1.21.1", "neoforge")
check("Mekanism resolved", rec is not None)
if rec:
    check("Mekanism 1.21.1 build", rec["version"] == "1.21.1-10.7.19.85", rec["version"])

# ---------------------------------------------------------------------------------------
print("- github asset matching")
mek_mod = {"github_asset_prefixes": ["Mekanism"]}
check("Mekanism-*.jar accepted",
      dm.asset_pattern(mek_mod, "mekanism/Mekanism", "Mekanism-1.21.1-10.7.19.85.jar"))
check("MekanismTools-*.jar rejected",
      not dm.asset_pattern(mek_mod, "mekanism/Mekanism", "MekanismTools-1.21.1-10.7.19.85.jar"))
check("Mekanism-all.jar rejected",
      not dm.asset_pattern(mek_mod, "mekanism/Mekanism", "Mekanism-1.21.1-10.7.19.85-all.jar"))
check("sources.jar rejected",
      not dm.asset_pattern(mek_mod, "mekanism/Mekanism", "Mekanism-1.21.1-10.7.19.85-sources.jar"))
jei_mod = {"github_asset": r"^jei-1\.21\.1-neoforge-.*\.jar$"}
check("JEI neoforge jar accepted",
      dm.asset_pattern(jei_mod, "mezz/JustEnoughItems", "jei-1.21.1-neoforge-19.70.0.469.jar"))
check("JEI common jar rejected",
      not dm.asset_pattern(jei_mod, "mezz/JustEnoughItems", "jei-1.21.1-common-19.70.0.469.jar"))

# ---------------------------------------------------------------------------------------
print("- modrinth version picking")
versions = [
    {"version_number": "3.9", "version_type": "release", "game_versions": ["1.21.1"], "loaders": ["neoforge"],
     "files": [{"primary": True, "filename": "exdeorum-3.9.jar", "url": "https://cdn/3.9.jar", "hashes": {"sha512": "aa"}}]},
    {"version_number": "3.12", "version_type": "release", "game_versions": ["1.21.1"], "loaders": ["neoforge"],
     "files": [{"primary": True, "filename": "exdeorum-3.12.jar", "url": "https://cdn/3.12.jar", "hashes": {}},
               {"primary": False, "filename": "exdeorum-3.12-sources.jar", "url": "https://cdn/src.jar", "hashes": {}}]},
    {"version_number": "9.0", "version_type": "release", "game_versions": ["1.20.1"], "loaders": ["neoforge"],
     "files": [{"primary": True, "filename": "exdeorum-9.jar", "url": "https://cdn/9.jar", "hashes": {}}]},
]
picked = dm.pick_modrinth_version(versions, "1.21.1", "neoforge")
check("newest 1.21.1 release picked", picked is not None and picked["version"] == "3.12",
      picked and picked["version"])
check("sources jar never picked", picked is not None and "sources" not in picked["filename"],
      picked and picked["filename"])

print()
if FAILS:
    print(f"FAILED: {len(FAILS)} test(s): {', '.join(FAILS)}")
    sys.exit(1)
print("all downloader tests passed")
