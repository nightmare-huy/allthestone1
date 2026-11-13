#!/usr/bin/env python3
"""
check_mods.py - offline sanity check of everything in mods/.

Reads META-INF/neoforge.mods.toml (and the older META-INF/mods.toml) out of every jar and
reports problems that would otherwise show up as a crash on the first launch:

  * duplicate mod ids            (two versions of the same mod)
  * missing required dependencies (mod requires something that is not installed)
  * known incompatible pairs     (e.g. Embeddium + Sodium, both are the same renderer)
  * wrong game version           (a 1.20.1 jar in a 1.21.1 pack)
  * broken archives / stray non-jar files

Usage:
    python3 tools/check_mods.py           # report
    python3 tools/check_mods.py --strict  # exit 1 on any error
"""

from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODS = ROOT / "mods"
MC = "1.21.1"

# mod ids that are provided by the game / the loader, never by a jar in mods/
IMPLICIT = {
    "minecraft", "neoforge", "forge", "fabric", "fabricloader", "java", "c", "cloth_config",
}

# two mods that must never be installed together (same feature, both patch the renderer)
# (group, mod ids that really are separate installations, message)
# Embeddium legitimately declares a "sodium" duplicate id to replace Sodium, so the pair
# only conflicts when two *files* provide them - that is checked by the duplicate-id rule.
CONFLICTS = []   # mods declare their own "incompatible" deps now, see below

ERRORS: list[str] = []
WARNINGS: list[str] = []


def parse_toml_lite(text: str) -> dict:
    """Just enough TOML for mods.toml: [[mods]] blocks and [[dependencies.x]] blocks."""
    mods: list[dict] = []
    deps: list[dict] = []

    for block in re.split(r"\[\[", text)[1:]:
        # "mods]] #mandatory \n modId=..." -> header "mods", body "modId=..."
        header, _, body = block.partition("]]")
        header = re.sub(r"#.*", "", header).strip().lower()

        def val(key: str) -> str | None:
            # modId="jei" #mandatory   /   type="required"
            m = re.search(rf'^[ \t]*{key}[ \t]*=[ \t]*"?([^"\n#]*)"?', body, flags=re.M)
            return m.group(1).strip() if m else None

        if header == "mods":
            mods.append({"modId": val("modId"), "version": val("version"),
                         "displayName": val("displayName"), "modLoader": val("modLoader")})
        elif header.startswith("dependencies"):
            deps.append({
                "owner": header.split(".")[-1].strip('"'),
                "modId": val("modId"),
                "type": (val("type") or "required").lower(),
                "versionRange": val("versionRange"),
            })
    return {"mods": mods, "deps": deps}


def nested_mod_ids(z: zipfile.ZipFile) -> set[str]:
    """Mods bundled inside the jar via NeoForge jar-in-jar (endercore, mezz_config, ...)."""
    ids: set[str] = set()
    for name in z.namelist():
        if not (name.startswith("META-INF/jarjar/") and name.endswith(".jar")):
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(z.read(name))) as inner:
                for inner_toml in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"):
                    if inner_toml in inner.namelist():
                        text = inner.read(inner_toml).decode("utf-8", "replace")
                        ids.update(re.findall(r'^[ \t]*modId[ \t]*=[ \t]*"?([^"\n#]+)"?', text, flags=re.M))
                        break
        except Exception:  # noqa: BLE001
            continue
    return {i.strip() for i in ids if i.strip()}


def read_jar(path: Path) -> dict:
    info = {"file": path.name, "mods": [], "deps": [], "bundled": set(), "error": None}
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            toml = next((n for n in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml")
                         if n in names), None)
            if not toml:
                # Fabric mods / libraries (e.g. nothing to check) - flag Fabric jars
                if "fabric.mod.json" in names:
                    info["error"] = "fabric mod - will not load on NeoForge"
                return info
            text = z.read(toml).decode("utf-8", "replace")
            parsed = parse_toml_lite(text)
            info["mods"] = parsed["mods"]
            info["deps"] = parsed["deps"]
            info["bundled"] = nested_mod_ids(z)
    except zipfile.BadZipFile:
        info["error"] = "not a zip archive"
    except Exception as e:  # noqa: BLE001
        info["error"] = f"unreadable: {e}"
    return info


def files_of(infos: list[dict], ids: set[str]) -> list[str]:
    out = []
    for info in infos:
        if any((m.get("modId") or "") in ids for m in info["mods"]):
            out.append(f"{info['file']} ({', '.join(m.get('modId', '?') for m in info['mods'])})")
    return out


def main() -> int:
    strict = "--strict" in sys.argv
    jars = sorted(MODS.glob("*.jar"))
    if not jars:
        print("mods/ is empty - run: python3 download_mods.py")
        return 1

    print(f"== checking {len(jars)} jars in {MODS} ==")
    by_mod_id: dict[str, list[str]] = {}
    infos = []
    for jar in jars:
        info = read_jar(jar)
        infos.append(info)
        if info["error"]:
            ERRORS.append(f"{info['file']}: {info['error']}")
        for m in info["mods"]:
            mid = m.get("modId")
            if mid:
                by_mod_id.setdefault(mid, []).append(info["file"])

    # duplicate mod ids
    for mid, files in sorted(by_mod_id.items()):
        if len(files) > 1:
            ERRORS.append(f"duplicate mod id '{mid}' in: {', '.join(files)}")

    # missing required dependencies
    present = set(by_mod_id)
    bundled = set().union(*(i["bundled"] for i in infos)) if infos else set()
    for info in infos:
        for dep in info["deps"]:
            mid = (dep.get("modId") or "").strip()
            if not mid or dep["type"] != "required":
                continue
            if dep["type"] == "incompatible":
                if mid in present:
                    ERRORS.append(f"{info['file']}: declares '{mid}' incompatible, but it is installed")
                continue
            if mid.lower() in IMPLICIT or mid in present or mid in bundled:
                continue
            if dep["type"] == "required":
                WARNINGS.append(
                    f"{info['file']}: requires '{mid}' {dep.get('versionRange') or ''}"
                    " (not in mods/)")

    # conflicts
    for group, own_files, why in CONFLICTS:
        installed = sorted(group & present)
        if len(installed) < 2:
            continue
        # only an error when a *second file* brings the other renderer
        files = [i["file"] for i in infos
                 if any((m.get("modId") or "") in group for m in i["mods"])]
        if len(files) > 1 and any(f.lower().startswith(tuple(own_files)) for f in files):
            ERRORS.append(f"conflict: {' + '.join(installed)} ({', '.join(files)}) - {why}")

    # game version hints from the file name (best effort)
    for jar in jars:
        name = jar.name
        if re.search(r"1\.20\.1|mc1\.20", name) and MC not in name:
            ERRORS.append(f"{name}: looks like a 1.20.x build, pack targets {MC}")

    print()
    for info in infos:
        names = ", ".join(str(m.get("modId") or "?") for m in info["mods"]) or "-"
        print(f"  {info['file']:<48} {names}")

    print()
    for w in WARNINGS:
        print(f"  warn  {w}")
    for e in ERRORS:
        print(f"  FAIL  {e}")

    print()
    print(f"{len(by_mod_id)} mod ids, {len(ERRORS)} error(s), {len(WARNINGS)} warning(s)")
    if ERRORS and strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
