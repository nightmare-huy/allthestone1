#!/usr/bin/env python3
"""
validate_pack.py - static checks for the All The Stone 1 pack files.

It does NOT need Minecraft. It catches the mistakes that actually break a pack:
  * broken JSON (worldgen, dimension, quest-adjacent files)
  * broken SNBT (FTB Quests chapters + data.snbt)
  * duplicate quest / task / reward ids
  * dependencies pointing at quests that do not exist
  * quests with no task
  * item ids that are obviously malformed
  * KubeJS scripts that reference dimensions/ids the pack does not ship

Usage:  python3 tools/validate_pack.py [--verbose]
Exit code 0 = all good, 1 = at least one error.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ERRORS: list[str] = []
WARNINGS: list[str] = []


def err(msg: str) -> None:
    ERRORS.append(msg)


def warn(msg: str) -> None:
    WARNINGS.append(msg)


# ---------------------------------------------------------------------------------------
#  minimal but strict SNBT parser (compound / list / string / number / bool)
# ---------------------------------------------------------------------------------------
class SnbtParser:
    NUMBER_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?[bBsSlLfFdD]?|[-+]?(?:NaN|Infinity)")

    def __init__(self, text: str, name: str):
        self.s = text
        self.i = 0
        self.name = name

    def fail(self, msg: str):
        line = self.s.count("\n", 0, self.i) + 1
        col = self.i - self.s.rfind("\n", 0, self.i)
        raise ValueError(f"{self.name}:{line}:{col}: {msg}")

    def ws(self):
        while self.i < len(self.s):
            c = self.s[i] if False else self.s[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif c == "#":                      # comment to end of line
                while self.i < len(self.s) and self.s[self.i] != "\n":
                    self.i += 1
            else:
                break

    def peek(self) -> str:
        self.ws()
        return self.s[self.i] if self.i < len(self.s) else ""

    def expect(self, ch: str):
        if self.peek() != ch:
            self.fail(f"expected {ch!r}, found {self.peek()!r}")
        self.i += 1

    def parse(self):
        value = self.value()
        self.ws()
        if self.i != len(self.s):
            self.fail(f"trailing data: {self.s[self.i:self.i + 30]!r}")
        return value

    def value(self):
        c = self.peek()
        if c == "{":
            return self.compound()
        if c == "[":
            return self.list()
        if c in "\"'":
            return self.string()
        return self.bare()

    def compound(self) -> dict:
        self.expect("{")
        out = {}
        while True:
            if self.peek() == "}":
                self.i += 1
                return out
            key = self.key()
            self.expect(":")
            out[key] = self.value()
            c = self.peek()
            if c == ",":
                self.i += 1
            elif c != "}":
                self.fail(f"expected ',' or '}}' after value, found {c!r}")

    def list(self) -> list:
        self.expect("[")
        out = []
        while True:
            if self.peek() == "]":
                self.i += 1
                return out
            out.append(self.value())
            c = self.peek()
            if c == ",":
                self.i += 1
            elif c != "]":
                self.fail(f"expected ',' or ']' after value, found {c!r}")

    def key(self) -> str:
        c = self.peek()
        if c in "\"'":
            return self.string()
        start = self.i
        while self.i < len(self.s) and (self.s[self.i].isalnum() or self.s[self.i] in "._-+"):
            self.i += 1
        if start == self.i:
            self.fail(f"expected a key, found {c!r}")
        return self.s[start:self.i]

    def string(self) -> str:
        quote = self.s[self.i]
        self.i += 1
        buf = []
        while self.i < len(self.s):
            c = self.s[self.i]
            if c == "\\":
                nxt = self.s[self.i + 1] if self.i + 1 < len(self.s) else ""
                buf.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                self.i += 2
            elif c == quote:
                self.i += 1
                return "".join(buf)
            else:
                buf.append(c)
                self.i += 1
        self.fail("unterminated string")

    def bare(self):
        m = self.NUMBER_RE.match(self.s, self.i)
        if m:
            raw = m.group(0)
            self.i = m.end()
            suffix = raw[-1]
            if suffix in "bBsSlLfFdD":
                raw = raw[:-1]
            try:
                return float(raw) if ("." in raw or "e" in raw.lower()) else int(raw)
            except ValueError:
                self.fail(f"bad number {raw!r}")
        start = self.i
        while self.i < len(self.s) and self.s[self.i] not in " \t\r\n,]}" :
            self.i += 1
        token = self.s[start:self.i]
        if not token:
            self.fail("expected a value")
        if token in ("true", "false"):
            return token == "true"
        return token            # unquoted string, e.g. "rounded_square"


def parse_snbt(path: Path):
    try:
        return SnbtParser(path.read_text(encoding="utf-8"), str(path.relative_to(ROOT))).parse()
    except ValueError as e:
        err(str(e))
        return None


# ---------------------------------------------------------------------------------------
#  checks
# ---------------------------------------------------------------------------------------
ITEM_ID = re.compile(r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")
QUEST_ID = re.compile(r"^[0-9A-Fa-f]{16}$")


def check_json() -> None:
    for path in sorted(ROOT.glob("**/*.json")):
        if any(part in (".git", "node_modules") for part in path.parts):
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            err(f"{path.relative_to(ROOT)}: invalid JSON ({e})")


def check_noise_settings() -> None:
    path = ROOT / "kubejs/data/minecraft/worldgen/noise_settings/overworld.json"
    if not path.exists():
        err("noise_settings/overworld.json is missing")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    router = data.get("noise_router", {})
    if router.get("final_density") != 1.0:
        err("noise_router.final_density must be the constant 1.0 (solid stone everywhere)")
    for key, value in router.items():
        if isinstance(value, str):
            warn(f"noise_router.{key} references {value}; the stone world should use constants only")
    if data.get("default_block", {}).get("Name") != "minecraft:stone":
        err("default_block must be minecraft:stone")
    if data.get("default_fluid", {}).get("Name") != "minecraft:air":
        err("default_fluid must be minecraft:air (no oceans inside the stone)")
    if data.get("noise", {}).get("min_y") != -64 or data.get("noise", {}).get("height") != 384:
        err("noise.min_y/-height must be -64 / 384")
    if data.get("aquifers_enabled") is not False:
        err("aquifers_enabled must be false")
    if data.get("ore_veins_enabled") is not False:
        err("ore_veins_enabled must be false")

    # bedrock at the very bottom and the very top
    seq = data.get("surface_rule", {}).get("sequence", [])
    bedrock_rules = [r for r in seq if r.get("then_run", {}).get("result_state", {}).get("Name") == "minecraft:bedrock"]
    if len(bedrock_rules) < 2:
        err("surface_rule must place bedrock at both y=-64 and y=319")
    else:
        tops = [r["if_true"]["false_at_and_above"]["absolute"] for r in bedrock_rules]
        if -63 not in tops:
            err("the floor bedrock rule must switch off at y=-63")
        if not any(t > 319 for t in tops):
            err("the ceiling bedrock rule must cover y=319 (false_at_and_above must be 320)")


def check_quests(verbose: bool = False) -> None:
    qdir = ROOT / "config/ftbquests/quests"
    data_path = qdir / "data.snbt"
    if not data_path.exists():
        err("config/ftbquests/quests/data.snbt is missing")
        return
    root = parse_snbt(data_path)
    if root is not None and root.get("version") != 13:
        err(f"data.snbt version must be 13 for FTB Quests 1.21.1 (found {root.get('version')})")

    chapters_dir = qdir / "chapters"
    files = sorted(chapters_dir.glob("*.snbt")) if chapters_dir.exists() else []
    if not files:
        err("config/ftbquests/quests/chapters/ has no chapters")
        return

    all_quest_ids: dict[str, str] = {}
    seen_obj_ids: dict[str, str] = {}
    chapter_ids = set()

    for path in files:
        chapter = parse_snbt(path)
        if chapter is None:
            continue
        rel = path.relative_to(ROOT)
        cid = chapter.get("id", "")
        if not QUEST_ID.match(str(cid)):
            err(f"{rel}: chapter id {cid!r} is not a 16 digit hex id")
        if cid in chapter_ids:
            err(f"{rel}: duplicate chapter id {cid}")
        chapter_ids.add(cid)
        if chapter.get("filename") != path.stem:
            warn(f"{rel}: filename field {chapter.get('filename')!r} != file name {path.stem!r}")
        if not chapter.get("title"):
            warn(f"{rel}: chapter has no title (it will render as its id)")

        quests = chapter.get("quests", [])
        if not isinstance(quests, list):
            err(f"{rel}: 'quests' must be a list")
            continue

        for q in quests:
            if not isinstance(q, dict):
                err(f"{rel}: a quest is not a compound")
                continue
            qid = str(q.get("id", ""))
            if not QUEST_ID.match(qid):
                err(f"{rel}: quest id {qid!r} is not a 16 digit hex id")
            if qid in seen_obj_ids:
                err(f"{rel}: duplicate object id {qid} (also in {seen_obj_ids[qid]})")
            seen_obj_ids[qid] = str(rel)
            all_quest_ids[qid] = str(rel)

            tasks = q.get("tasks", [])
            if not tasks:
                err(f"{rel}: quest {qid} has no task (it can never be completed)")
            for t in tasks:
                tid = str(t.get("id", ""))
                if tid in seen_obj_ids:
                    err(f"{rel}: duplicate task id {tid}")
                seen_obj_ids[tid] = str(rel)
                if not t.get("type"):
                    err(f"{rel}: task {tid} has no type")
                item = t.get("item")
                if isinstance(item, dict) and "id" in item and not ITEM_ID.match(str(item["id"])):
                    err(f"{rel}: task {tid} has a malformed item id {item['id']!r}")
            for r in q.get("rewards", []):
                rid = str(r.get("id", ""))
                if rid in seen_obj_ids:
                    err(f"{rel}: duplicate reward id {rid}")
                seen_obj_ids[rid] = str(rel)
                item = r.get("item")
                if isinstance(item, dict) and "id" in item and not ITEM_ID.match(str(item["id"])):
                    err(f"{rel}: reward {rid} has a malformed item id {item['id']!r}")
            if verbose:
                print(f"   quest {qid} {q.get('title')!r} tasks={len(tasks)}")

    # second pass: dependencies must exist
    for path in files:
        chapter = parse_snbt(path)
        if not chapter:
            continue
        for q in chapter.get("quests", []):
            for dep in q.get("dependencies", []) or []:
                if str(dep) not in all_quest_ids:
                    err(f"{path.relative_to(ROOT)}: quest {q.get('id')} depends on unknown quest {dep}")

    print(f"   chapters: {len(files)}, quests: {len(all_quest_ids)}")


def check_kubejs() -> None:
    dim = ROOT / "kubejs/data/allthestone1/dimension/stone_world.json"
    if not dim.exists():
        err("kubejs/data/allthestone1/dimension/stone_world.json is missing")
        return
    d = json.loads(dim.read_text(encoding="utf-8"))
    dtype = d.get("type", "")
    type_path = ROOT / "kubejs/data" / dtype.replace(":", "/worldgen/dimension_type/", 1).replace(":", "/") 
    # dtype is allthestone1:stone_world -> kubejs/data/allthestone1/worldgen/dimension_type/stone_world.json
    ns, _, name = dtype.partition(":")
    type_path = ROOT / "kubejs/data" / ns / "worldgen/dimension_type" / f"{name}.json"
    if not type_path.exists():
        err(f"dimension {dim.name} points at missing dimension_type {dtype}")
    sel = d.get("generator", {}).get("settings")
    if sel != "minecraft:overworld":
        err(f"stone_world must generate with minecraft:overworld noise settings (found {sel})")

    spawn_js = ROOT / "kubejs/server_scripts/stone_block_spawn.js"
    if spawn_js.exists():
        text = spawn_js.read_text(encoding="utf-8")
        for needle in ("PlayerEvents.loggedIn", "first_join", "setworldspawn", "fill -2 64 -2 2 68 2"):
            if needle not in text:
                err(f"stone_block_spawn.js is missing {needle!r}")
        if "allthestone1:stone_world" not in text:
            err("stone_block_spawn.js does not reference the stone world dimension id")

    prog = ROOT / "kubejs/server_scripts/progression.js"
    if prog.exists():
        text = prog.read_text(encoding="utf-8")
        for needle in ("BlockEvents.rightClicked", "PEBBLE_CHANCE", "ServerEvents.recipes", "minecraft:dirt"):
            if needle not in text:
                err(f"progression.js is missing {needle!r}")


def check_mod_list() -> None:
    """Every jar name in the catalog must at least look like a mod we know about."""
    path = ROOT / "modlist.json"
    if not path.exists():
        err("modlist.json is missing")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("minecraft") != "1.21.1":
        err("modlist.json must target minecraft 1.21.1")
    if data.get("loader") != "neoforge":
        err("modlist.json must target the neoforge loader")
    ids = set()
    for mod in data["mods"]:
        if mod["id"] in ids:
            err(f"modlist.json: duplicate mod id {mod['id']}")
        ids.add(mod["id"])
        if not mod.get("name"):
            err(f"modlist.json: mod {mod['id']} has no name")


def main() -> int:
    verbose = "--verbose" in sys.argv
    print("== validating All The Stone 1 ==")

    print("- version / structure")
    for required in (
        "mods",
        "config/ftbquests/quests/chapters",
        "kubejs/server_scripts",
        "kubejs/startup_scripts",
        "kubejs/data/minecraft/worldgen/noise_settings",
    ):
        if not (ROOT / required).is_dir():
            err(f"missing directory: {required}")

    print("- json")
    check_json()
    print("- worldgen (solid stone, bedrock floor + ceiling)")
    check_noise_settings()
    print("- ftb quests")
    check_quests(verbose)
    print("- kubejs")
    check_kubejs()
    print("- mod catalog")
    check_mod_list()

    print()
    for w in WARNINGS:
        print(f"  warning: {w}")
    for e in ERRORS:
        print(f"  ERROR:   {e}")
    print()
    if ERRORS:
        print(f"FAILED with {len(ERRORS)} error(s), {len(WARNINGS)} warning(s)")
        return 1
    print(f"OK - 0 errors, {len(WARNINGS)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
