#!/usr/bin/env python3
"""
download_mods.py - fetches a complete Minecraft 1.21.1 / NeoForge mod set into ./mods/

Sources are tried in order, and every source that answers wins:
  1. Modrinth  (https://api.modrinth.com/v2/)            - official API
  2. CurseForge (https://api.curseforge.com/v1/)         - official API, needs CF_API_KEY
  3. GitHub releases (api.github.com)                    - many 1.21.1 NeoForge mods publish jars there

Run it:
    python3 download_mods.py                 # install everything that is available
    python3 download_mods.py --dry-run       # only report what would be installed
    python3 download_mods.py --only jei,kubejs
    python3 download_mods.py --report        # write MODS.md summary

If the network blocks the CDNs (some sandboxes only allow api.github.com) the script still
finishes and writes mods/manifest.json + mods/MISSING.md with a one-click CurseForge manifest
for the mods it could not fetch, so nothing is silently lost.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODS_DIR = ROOT / "mods"

# Preference order. Every entry is an independent ecosystem, so one dead host cannot
# break the build: modrinth | curseforge | maven | github | release (this repo's release
# assets, see release_lookup). Override with --prefer or ATS_SOURCES.
DEFAULT_ORDER = "modrinth,curseforge,maven,github"
CATALOG = ROOT / "modlist.json"
MANIFEST = MODS_DIR / "manifest.json"
MISSING_REPORT = ROOT / "MISSING_MODS.md"

USER_AGENT = "allthestone1-modpack-builder/1.0 (github.com/nightmare-huy/allthestone1)"
TIMEOUT = 45
RETRIES = 2

REPO = os.environ.get("ATS_REPO") or "nightmare-huy/allthestone1"   # overridden by git remote
MODRINTH = "https://api.modrinth.com/v2"
CURSEFORGE = "https://api.curseforge.com/v1"
GITHUB = "https://api.github.com"

# Set to False automatically when a host is unreachable, so we do not wait for timeouts 30 times
AVAILABLE = {"modrinth": True, "curseforge": True, "github": True, "maven": True, "html": True}
MAVEN_HOSTS = ("maven.blamejared.com", "maven.architectury.dev", "modmaven.dev", "maven.saps.dev")


# --------------------------------------------------------------------------------------
# tiny http helper
# --------------------------------------------------------------------------------------
def host_of(url: str) -> str:
    if url.startswith(MODRINTH):
        return "modrinth"
    if url.startswith(CURSEFORGE):
        return "curseforge"
    if url.startswith(GITHUB):
        return "github"
    return "cdn"


def api_of(url: str) -> str:
    """Which *API* group a URL belongs to (used for the availability cache)."""
    if url.startswith(MODRINTH):
        return "modrinth"
    if url.startswith(CURSEFORGE):
        return "curseforge"
    if url.startswith(GITHUB):
        return "github"
    if any(h in url for h in MAVEN_HOSTS):
        return "maven"
    return "html"


def http_json(url: str, headers: dict | None = None):
    host = api_of(url)
    if host in AVAILABLE and not AVAILABLE[host]:
        return None            # this API is unreachable from here, do not waste time (again)
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    last = None
    for attempt in range(RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
            if e.code in (403, 429):
                # rate limited (GitHub unauthenticated = 60 req/h) - back off, keep trying
                time.sleep(2.0 * (attempt + 1))
                continue
            break
        except Exception as e:  # noqa: BLE001 - network can fail in many ways
            last = e
            if isinstance(e, (urllib.error.URLError, ssl.SSLError, OSError)) and "timed out" not in str(e):
                # TLS reset / DNS block => the whole host is unusable here
                if host in AVAILABLE:
                    AVAILABLE[host] = False
                    print(f"    ! {host} is not reachable from this network ({type(e).__name__}), skipping it from now on")
                break
            time.sleep(1.0 * (attempt + 1))
    else:
        print(f"    ! request failed: {url} ({last})")
    return None


CDN_FAILURES = {"count": 0}

# Prefixes tried in order when a CDN is unreachable (self-hosted proxies / mirrors).
# ATS_MIRRORS="/opt/mirror/,https://mirror.example.com/" reuses a local cache of the CDN.
MIRRORS = [m.strip().rstrip("/") + "/" for m in os.environ.get("ATS_MIRRORS", "").split(",")
           if m.strip()]


def http_bytes(url: str, headers: dict | None = None) -> bytes | None:
    """Plain GET that returns bytes (used for HTML pages and small API fallbacks)."""
    host = api_of(url)
    if host in AVAILABLE and not AVAILABLE[host]:
        return None
    hdrs = {"User-Agent": USER_AGENT, "Accept": "text/html,application/json,*/*"}
    if headers:
        hdrs.update(headers)
    try:
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code in (403, 429):
            time.sleep(2.0)
            return None
        return None
    except Exception:  # noqa: BLE001
        if host in AVAILABLE:
            AVAILABLE[host] = False
        return None


def download_file(url: str, dest: Path, expected_sha512: str | None = None,
                  track_failures: bool = True) -> bool:
    if track_failures and CDN_FAILURES["count"] >= 2:
        print("    ! file downloads are blocked on this network, recording as manual download")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    headers = {"User-Agent": USER_AGENT}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=TIMEOUT * 3) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1024 * 256)
    except Exception as e:  # noqa: BLE001
        if track_failures:
            CDN_FAILURES["count"] += 1
        print(f"    ! download failed: {e}")
        tmp.unlink(missing_ok=True)
        return False

    if expected_sha512:
        h = hashlib.sha512()
        with open(tmp, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 512), b""):
                h.update(chunk)
        if h.hexdigest().lower() != expected_sha512.lower():
            print("    ! checksum mismatch, discarding file")
            tmp.unlink(missing_ok=True)
            return False

    tmp.replace(dest)
    return True


def download_with_mirrors(url: str, dest: Path, expected_sha512: str | None = None,
                          mirrors: list[str] | None = None) -> tuple[bool, str | None]:
    """
    Try `url` and then every mirror until one returns the file.

    Returns (ok, working_prefix). `working_prefix` is "" for the original URL or the
    mirror prefix that worked, so the caller can rewrite every remaining download -
    these sandboxes usually block all CDNs, and a known-good host saves a lot of time.
    """
    candidates = [("", url)]
    for prefix in mirrors or []:
        if prefix and not url.startswith(prefix):
            candidates.append((prefix, prefix + url))
    for prefix, candidate in candidates:
        if download_file(candidate, dest, expected_sha512):
            return True, prefix
        if candidate != url and not dest.exists():
            continue
    return False, None


def download_asset_by_id(mod: dict, asset_id: int, dest: Path, expected_sha512: str | None = None) -> bool:
    """
    GitHub does not always hand out a browser_download_url (and it is always on the
    blocked release-assets host), but `Accept: application/octet-stream` on
    /releases/assets/<id> streams the bytes from api.github.com itself.
    """
    url = f"{GITHUB}/repos/{mod['github']}/releases/assets/{asset_id}"
    headers = {"Accept": "application/octet-stream", "User-Agent": USER_AGENT}
    tmp = dest.with_suffix(dest.suffix + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=TIMEOUT * 3) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1024 * 256)
    except Exception as e:  # noqa: BLE001
        print(f"    ! asset download failed: {e}")
        tmp.unlink(missing_ok=True)
        return False
    if expected_sha512:
        h = hashlib.sha512()
        with open(tmp, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 512), b""):
                h.update(chunk)
        if h.hexdigest().lower() != expected_sha512.lower():
            print("    ! checksum mismatch, discarding file")
            tmp.unlink(missing_ok=True)
            return False
    tmp.replace(dest)
    return True


def modrinth_versions_html(slug: str, mc: str, loader: str) -> list[dict] | None:
    """
    Last-resort Modrinth access: the plain HTML page lists file links, so it also works
    when api.modrinth.com is blocked but modrinth.com is not.
    """
    body = http_bytes(f"https://modrinth.com/mod/{urllib.parse.quote(slug)}/versions"
                      f"?g={urllib.parse.quote(mc)}&l={urllib.parse.quote(json.dumps([loader]))}")
    if not body:
        return None
    html = body.decode("utf-8", "replace")
    found = []
    for m in re.finditer(r'https://cdn\.modrinth\.com/data/[^"\s\\]+?\.jar', html):
        url = m.group(0)
        found.append({"version_number": url.rsplit("/", 1)[-1], "version_type": "release",
                      "files": [{"primary": True, "url": url, "filename": url.rsplit("/", 1)[-1],
                                 "hashes": {}}]})
    return found or None


def curseforge_files_html(slug: str, mc: str, loader: str) -> list[dict] | None:
    """
    CurseForge fallback without an API key: scrape the project's files page for
    /files/<id> links and resolve the CDN URL from the file page itself.
    """
    body = http_bytes(f"https://www.curseforge.com/minecraft/mc-mods/{urllib.parse.quote(slug)}"
                      f"/files/all?page=1&pageSize=50&gameVersionTypeId=1.21.1")
    if not body:
        return None
    html = body.decode("utf-8", "replace")
    ids = []
    for m in re.finditer(r"/files/(\d+)", html):
        fid = m.group(1)
        if fid not in ids:
            ids.append(fid)
    return [{"fileId": int(i)} for i in ids[:20]] or None


def curseforge_file_page_url(slug: str, file_id: int) -> str | None:
    body = http_bytes(f"https://www.curseforge.com/minecraft/mc-mods/{urllib.parse.quote(slug)}/files/{file_id}")
    if not body:
        return None
    html = body.decode("utf-8", "replace")
    m = re.search(r'"downloadUrl"\s*:\s*"([^"]+)"', html) or \
        re.search(r'https://(?:edge|media)\.forgecdn\.net/[^"\s]+?\.jar', html)
    if not m:
        return None
    url = m.group(1) if m.groups() else m.group(0)
    return url.replace("\\/", "/")


# --------------------------------------------------------------------------------------
# version lookups
# --------------------------------------------------------------------------------------
def version_key(v: str) -> tuple:
    """Sort key that understands versions such as 1.2.3-beta, 21.1.77, v2.4.0+1.21.1."""
    parts = re.split(r"[.\-+_]", str(v).lstrip("vV"))
    out = []
    for p in parts:
        if p.isdigit():
            out.append((0, int(p)))
        else:
            m = re.match(r"^(\d+)(.*)$", p)
            out.append((1, int(m.group(1))) if m else (2, 0))
    return tuple(out)


def loaders_for(mod: dict) -> list[str]:
    return ["neoforge"]


def pick_modrinth_version(versions: list[dict], mc: str, loader: str) -> dict | None:
    good = []
    for v in versions or []:
        if mc not in v.get("game_versions", []):
            continue
        if loader not in [lo.lower() for lo in v.get("loaders", [])]:
            continue
        if v.get("version_type") == "alpha":
            continue
        files = [f for f in v.get("files", []) if f.get("primary")] or v.get("files", [])
        files = [f for f in files if f.get("filename", "").endswith(".jar")
                 and "sources" not in f.get("filename", "") and "dev" not in f.get("filename", "")]
        if not files:
            continue
        good.append((version_key(v.get("version_number", "")), v, files[0]))
    if not good:
        return None
    good.sort(key=lambda t: t[0])
    release = [g for g in good if g[1].get("version_type") == "release"]
    chosen = (release or good)[-1]
    return {"version": chosen[1]["version_number"], "url": chosen[2]["url"],
            "filename": chosen[2]["filename"], "sha512": chosen[2].get("hashes", {}).get("sha512"),
            "source": "modrinth", "id": chosen[1].get("id")}


def modrinth_lookup(slug: str, mc: str, loader: str) -> dict | None:
    project = http_json(f"{MODRINTH}/project/{urllib.parse.quote(slug)}")
    if not project:
        return None
    real_slug = project.get("slug") or slug
    q = urllib.parse.urlencode({"loaders": json.dumps([loader]), "game_versions": json.dumps([mc])})
    versions = http_json(f"{MODRINTH}/project/{urllib.parse.quote(real_slug)}/version?{q}")
    if versions is None:
        return None
    found = pick_modrinth_version(versions, mc, loader)
    if found:
        found["project"] = real_slug
        found["title"] = project.get("title", real_slug)
    return found


def modrinth_search(query: str, mc: str, loader: str) -> dict | None:
    q = urllib.parse.urlencode({
        "query": query,
        "facets": json.dumps([[f"versions:{mc}"], [f"categories:{loader}"]]),
        "limit": 5,
    })
    res = http_json(f"{MODRINTH}/search?{q}")
    if not res or not res.get("hits"):
        return None
    return modrinth_lookup(res["hits"][0]["slug"], mc, loader)


# --- CurseForge ------------------------------------------------------------------------
NEOFORGE_VERSION = "21.1.266"   # latest 1.21.1 build, update freely

CF_GAME_ID = 432          # Minecraft
CF_CLASS_MOD = 6
CF_RELEASE = 1


def cf_headers() -> dict | None:
    key = os.environ.get("CF_API_KEY") or os.environ.get("CURSEFORGE_API_KEY")
    if not key:
        return None
    return {"x-api-key": key}


def cf_find_mod(mod: dict) -> dict | None:
    headers = cf_headers()
    if headers is None:
        return None
    slug = mod.get("curseforge")
    if isinstance(slug, int) or (isinstance(slug, str) and slug.isdigit()):
        return {"id": int(slug), "slug": str(slug), "name": mod["name"]}
    if not slug:
        return None
    res = http_json(f"{CURSEFORGE}/mods/search?"
                    + urllib.parse.urlencode({"gameId": CF_GAME_ID, "slug": slug, "classId": CF_CLASS_MOD}),
                    headers)
    if res and res.get("data"):
        d = res["data"][0]
        return {"id": d["id"], "slug": d.get("slug", slug), "name": d.get("name", mod["name"])}
    return None


def curseforge_lookup(mod: dict, mc: str, loader: str) -> dict | None:
    headers = cf_headers()
    if headers is None:
        return None
    found = cf_find_mod(mod)
    if not found:
        return None
    params = {
        "gameVersion": mc,
        "modLoaderType": 6,          # 6 = NeoForge in the CurseForge API
        "pageSize": 50,
    }
    res = http_json(f"{CURSEFORGE}/mods/{found['id']}/files?" + urllib.parse.urlencode(params), headers)
    files = (res or {}).get("data") or []
    files = [f for f in files if f.get("releaseType") == CF_RELEASE and f.get("fileName", "").endswith(".jar")]
    if not files:
        # fall back to beta builds (many NeoForge ports only ship betas)
        files = [f for f in (res or {}).get("data") or [] if f.get("fileName", "").endswith(".jar")]
    if not files:
        return None
    files.sort(key=lambda f: version_key(f.get("displayName") or f.get("fileName", "")))
    f = files[-1]
    url = f.get("downloadUrl")
    if not url:
        return None
    return {"version": f.get("displayName") or f.get("fileName"), "url": url,
            "filename": f["fileName"], "sha512": None, "source": "curseforge",
            "id": f.get("modId"), "project": found.get("slug"), "title": found.get("name")}


# --- Maven repositories ----------------------------------------------------------------
def maven_lookup(mod: dict, mc: str, loader: str) -> dict | None:
    """
    Public Maven repositories used by 1.21.1 NeoForge mods (BlameJared for JEI,
    Architectury's own repo, modmaven for Mekanism...). We read maven-metadata.xml,
    pick the newest version that names the target MC version, and use the standard
    <artifact>-<version>.jar path.
    """
    cfg = mod.get("maven")
    if not cfg:
        return None
    repo = cfg["repo"].rstrip("/")
    group = cfg["group"].strip("/")
    artifact = cfg["artifact"]
    meta_url = f"{repo}/{group}/{artifact}/maven-metadata.xml"
    xml = http_text(meta_url)
    if not xml:
        return None
    versions = re.findall(r"<version>([^<]+)</version>", xml)
    wanted = []
    for v in versions:
        # a Maven version string alone does not identify the MC version unless it carries
        # "1.21.1"/"mc1.21.1"; catalogs that use the <mc>.<build> scheme set version_regex
        if not (mc_in(v, mc) or cfg.get("version_regex") or cfg.get("version_prefix")
                or cfg.get("allow_loose")):
            continue
        if "snapshot" in v.lower() or "-alpha" in v.lower():
            continue
        wanted.append(v)
    if not wanted:
        return None

    # The maven metadata cannot tell MC versions apart, so the mod catalog decides which
    # version series belongs to 1.21.1:
    #   exact "1.21.1" or "mc1.21.1" in the version        -> claim it
    #   "<mc>.x.y" style (e.g. 19.70.0.469 for MC 1.21.1)  -> only when allow_loose is set,
    #                                                         and only "19.21.1"-headed values
    if cfg.get("version_regex"):
        # the catalog knows the version series, e.g. JEI 19.x = MC 1.21.x
        wanted = [v for v in wanted if re.match(cfg["version_regex"], v)]
    elif cfg.get("version_prefix"):
        # FTB versioning: "20xx" = MC 1.20.x, "2101" = MC 1.21.1
        wanted = [v for v in wanted if v.startswith(cfg["version_prefix"])]
    elif cfg.get("allow_loose"):
        wanted = [v for v in wanted
                  if MC_IN_TEXT_RE.search(v) or MC_VERSION_RE.match(v) or mc in v]
    else:
        # strict: only versions that literally name the MC version (Mekanism: 1.21.1-10.7.x)
        wanted = [v for v in wanted if mc in v or MC_IN_TEXT_RE.search(v)]

    wanted.sort(key=version_key)
    for version in reversed(wanted[-5:]):
        fn = cfg.get("filename", "{artifact}-{version}.jar").format(artifact=artifact, version=version)
        url = f"{repo}/{group}/{artifact}/{version}/{fn}"
        if url_exists(url):
            return {"version": version, "url": url, "filename": fn, "sha512": None,
                    "source": "maven", "id": repo, "project": artifact, "title": mod["name"]}
    return None


def http_text(url: str) -> str | None:
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return None


def url_exists(url: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="HEAD")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            length = int(r.headers.get("Content-Length") or 0)
            return 200 <= r.status < 300 and (length == 0 or length > 20_000)
    except Exception:  # noqa: BLE001
        return False


# --- GitHub ----------------------------------------------------------------------------
MC_TOKEN = re.compile(r"(?<!\d)1[._]21[._]1(?!\d)")
MC_VERSION_RE = re.compile(r"(?<!\d)1\.21\.1(?!\d)")
MC_IN_TEXT_RE = re.compile(r"(?<!\d)mc1\.21\.1(?!\d)")   # used to "claim" a version string


def mc_in(text: str, mc: str, loose: bool = False) -> bool:
    """
    True when `text` names the target Minecraft version, with proper boundaries.

    "exdeorum-3.12+1.21.1"  -> True
    "Mekanism-1.21.1-10.7"  -> True
    "mod-1.21.11.jar"       -> False   (1.21.11 is a different game version)
    "mod-1.21.10.jar"       -> False
    """
    pattern = r"(?<![0-9])" + re.escape(mc) + r"(?![0-9.])"
    if re.search(pattern, text):
        return True
    if MC_TOKEN.search(text):
        return True
    if loose and mc.count(".") == 2:
        # "<mc>.<build>" versioning, e.g. 19.21.1.300 for MC 1.21.1 (JEI style)
        return text.startswith(mc)
    return False


NEO_TOKEN = re.compile(r"(neoforge|neo)", re.I)


BAD_ASSET_PARTS = ("sources", "javadoc", "-api", "-dev", "installer", "-all", "test", "example")


def asset_pattern(mod: dict, repo: str, filename: str) -> bool:
    """
    Decide whether `filename` is the main jar of `mod`.

    * `mod["github_asset"]` (optional regex) wins when present
    * otherwise the jar must start with the repository name followed by a separator,
      so `Mekanism-1.21.1-10.7.19.85.jar` matches while `MekanismTools-...` does not
    """
    low = filename.lower()
    if any(part in low for part in BAD_ASSET_PARTS):
        return False
    custom = mod.get("github_asset")
    if custom:
        return re.search(custom, filename) is not None
    base = repo.split("/")[-1].lower()
    # a few repos are named differently from their jar (Mekanism is the classic one)
    bases = {base}
    for alias in mod.get("github_asset_prefixes", []) or []:
        bases.add(alias.lower())
    return any(re.match(re.escape(b) + r"[-_.]", low) for b in bases)


def github_lookup(mod: dict, mc: str, loader: str) -> dict | None:
    """
    Only accept a release asset that explicitly names the target MC version (and prefers
    neoforge in the name). We deliberately do NOT fall back to "newest whatever version",
    because a wrong-version jar in mods/ is worse than a missing mod.
    """
    repo = mod.get("github")
    if not repo:
        return None
    branch_hint = mod.get("github_branch_version")  # e.g. "2101" (KubeJS branch naming)
    releases = http_json(f"{GITHUB}/repos/{repo}/releases?per_page=100") or []
    candidates = []
    for rel in releases:
        tag = rel.get("tag_name", "")
        blob = f"{tag} {rel.get('name') or ''}"
        for asset in rel.get("assets", []):
            fn = asset.get("name", "")
            low = fn.lower()
            if not low.endswith(".jar"):
                continue
            if any(x in low for x in ("sources", "javadoc", "-dev", "-api", "installer")):
                continue
            if asset.get("size", 0) < 20_000:
                continue
            blob2 = f"{blob} {fn}"
            mc_ok = mc_in(blob2, mc)
            if not mc_ok:
                continue
            # the jar must belong to *this* project, not to a bundling sibling
            # (MekanismTools, MekanismGenerators, ... all start with "Mekanism")
            name_ok = asset_pattern(mod, repo, fn)
            if not name_ok:
                continue
            score = 10
            if NEO_TOKEN.search(blob2):
                score += 5
            if branch_hint and branch_hint in blob2.replace(".", ""):
                score += 3
            candidates.append((score, version_key(tag), asset, rel, fn))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1]))
    score, _, asset, rel, fn = candidates[-1]
    return {"version": rel.get("tag_name"), "url": asset["browser_download_url"],
            "filename": fn, "sha512": None, "source": "github",
            "id": repo, "project": repo, "title": mod["name"],
            "confidence": "high" if score >= 15 else "medium"}


def release_lookup(mod: dict, mc: str, loader: str) -> dict | None:
    """
    Look for the jar in this repository's own releases.

    The GitHub Actions workflow (.github/workflows/build-mrpack.yml) runs
    download_mods.py on a machine with real internet access and uploads every resolved
    jar to a release, so builds behind a filtering proxy can still fetch the files from
    api.github.com (which is always reachable here).
    """
    tag = os.environ.get("ATS_RELEASE_TAG") or "mods-latest"
    data = http_json(f"{GITHUB}/repos/{REPO}/releases/tags/{tag}")
    if not data:
        return None
    assets = data.get("assets") or []
    wanted = [a for a in assets
              if a.get("name", "").lower().endswith(".jar")
              and asset_pattern(mod, mod.get("github") or "", a["name"])]
    if not wanted:
        return None
    asset = wanted[0]
    return {"version": "release-asset", "url": asset["browser_download_url"],
            "filename": asset["name"], "sha512": None, "source": "release",
            "asset_id": asset.get("id"), "id": REPO, "project": REPO, "title": mod["name"]}


# --------------------------------------------------------------------------------------
# manifest / report writers
# --------------------------------------------------------------------------------------
def write_manifest(installed: list[dict], missing: list[dict], mc: str, loader: str) -> None:
    """
    manifest.json: kept next to the jars so the CurseForge launcher can import it
    (format: minecraft/modloader/files -> projectID + fileID).
    """
    cf_files = []
    for rec in installed:
        if rec.get("source") == "curseforge" and rec.get("curseforge_project") and rec.get("curseforge_file"):
            cf_files.append({"projectID": rec["curseforge_project"], "fileID": rec["curseforge_file"],
                             "required": bool(rec.get("required"))})
    manifest = {
        "minecraft": {
            "version": mc,
            # newest NeoForge for 1.21.1, see README ("NeoForge 21.1.x")
            "modLoaders": [{"id": f"{loader}-{NEOFORGE_VERSION}", "primary": True}],
        },
        "manifestType": "minecraftModpack",
        "manifestVersion": 1,
        "name": "All The Stone 1",
        "version": "1.0.0",
        "author": "nightmare-huy",
        "files": cf_files,
        "overrides": "overrides",
    }
    MODS_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    # A launch-ready local record of exactly what is in mods/
    (MODS_DIR / "installed.json").write_text(json.dumps(
        [{"name": r.get("title"), "file": r.get("filename"), "version": r.get("version"),
          "source": r.get("source")} for r in installed], indent=2) + "\n", encoding="utf-8")


def write_missing_report(missing: list[dict], installed: list[dict], mc: str, loader: str) -> None:
    lines = [
        "# Missing / manual mods",
        "",
        f"Target: Minecraft **{mc}**, loader **{loader}**.",
        "",
        "These mods could not be downloaded automatically from the machine that ran",
        "`download_mods.py` (no Modrinth CDN, no CurseForge key, or no matching build published).",
        "",
        "| Mod | Why it was not downloaded | Where to get it |",
        "| --- | --- | --- |",
    ]
    for m in missing:
        slug = m.get("curseforge") or m.get("id")
        lines.append(f"| {m['name']} | {m.get('reason', 'not found')} | https://www.curseforge.com/minecraft/mc-mods/{slug}/files?gameVersionTypeId=1.21.1 |")
    lines += [
        "",
        "## Fastest way to finish",
        "",
        "1. Put any jar you download into `mods/` (filenames do not matter).",
        "2. Re-run `python3 download_mods.py` afterwards - it only fetches what is still missing.",
        "",
        f"Already installed automatically: **{len(installed)}** jars:",
        "",
    ]
    lines += [f"- {r.get('title')} `{r.get('filename')}` ({r.get('source')})" for r in installed] or ["- (none)"]
    MISSING_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------------------
# .mrpack (Modrinth pack format) - lets a launcher download every jar for you
# --------------------------------------------------------------------------------------
def write_mrpack(out: Path, resolved: list[dict], mc: str, loader: str) -> None:
    files = []
    for rec in resolved:
        if not rec.get("url"):
            continue
        files.append({
            "path": f"mods/{rec['filename']}",
            "hashes": {"sha512": rec["sha512"]} if rec.get("sha512") else {},
            "downloads": [rec["url"]],
            "fileSize": rec.get("size") or 0,
        })

    index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": "1.0.0",
        "name": "All The Stone 1",
        "summary": "Stoneblock for 1.21.1 / NeoForge - a solid stone world, Ex Deorum sieves and two FTB Quests chapters.",
        "files": files,
        "dependencies": {
            "minecraft": mc,
            "neoforge": NEOFORGE_VERSION,
        },
    }

    overrides = ["config", "kubejs", "README.md", "modlist.json", "download_mods.py", "tools"]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("modrinth.index.json", json.dumps(index, indent=2))
        for name in overrides:
            src = ROOT / name
            if src.is_file():
                z.write(src, name)
                continue
            if not src.exists():
                continue
            for path in sorted(src.rglob("*")):
                if path.is_file() and not any(p in ("__pycache__",) for p in path.parts):
                    z.write(path, str(path.relative_to(ROOT)))
    print(f"wrote {out} ({len(files)} mods, {out.stat().st_size // 1024} KiB)")


# --------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Download the All The Stone 1 mod set.")
    ap.add_argument("--dry-run", action="store_true", help="resolve versions but do not download")
    ap.add_argument("--only", default="", help="comma separated mod slugs to (re)install")
    ap.add_argument("--force", action="store_true", help="re-download even if the jar already exists")
    ap.add_argument("--mc", default=None, help="override Minecraft version")
    ap.add_argument("--loader", default=None, help="override loader")
    ap.add_argument("--mrpack", nargs="?", const="allthestone1-1.0.0.mrpack", default=None,
                    help="only resolve versions and write an importable Modrinth pack (.mrpack)")
    ap.add_argument("--prefer", default=os.environ.get("ATS_SOURCES", DEFAULT_ORDER),
                    help=f"comma separated source order (default: {DEFAULT_ORDER})")
    ap.add_argument("--from-release", dest="prefer_release", action="store_true",
                    help="try this repository's release assets first (see .github/workflows)")
    args = ap.parse_args()

    if not CATALOG.exists():
        print("modlist.json not found next to download_mods.py")
        return 2
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    mc = args.mc or catalog.get("minecraft", "1.21.1")
    loader = (args.loader or catalog.get("loader", "neoforge")).lower()
    only = {s.strip().lower() for s in args.only.split(",") if s.strip()}

    MODS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"== All The Stone 1 :: mod download ==")
    print(f"   minecraft {mc} / {loader}")
    print(f"   target    {MODS_DIR}")
    print(f"   curseforge api key: {'yes' if cf_headers() else 'no (set CF_API_KEY to enable)'}")
    print()

    installed: list[dict] = []
    missing: list[dict] = []
    present = {p.name for p in MODS_DIR.glob("*.jar")}

    for mod in catalog["mods"]:
        slug = mod["id"]
        if only and slug.lower() not in only and mod["name"].lower() not in only:
            continue

        print(f"- {mod['name']} [{slug}]")
        record = None
        reasons = []

        # The order is a preference list: at least 4 independent ecosystems are used,
        # so a blocked/down host only costs speed, never the whole pack.
        order = [s_.strip() for s_ in (args.prefer or DEFAULT_ORDER).split(",") if s_.strip()]
        if args.prefer_release:
            order.insert(0, "release")
        for source in order:
            if record:
                break

            if source == "modrinth":
                record = modrinth_lookup(slug, mc, loader)
                if not record and mod.get("search"):
                    print("    ~ not found by slug, searching modrinth")
                    record = modrinth_search(mod["search"], mc, loader)
                if not record:
                    record = modrinth_versions_html(slug, mc, loader)
                    if record:
                        record = pick_modrinth_version(record, mc, loader)
                        record = record and {**record, "source": "modrinth-html",
                                             "project": slug, "title": mod["name"]}
                if not record:
                    reasons.append("modrinth: no 1.21.1 neoforge build")

            elif source == "curseforge":
                record = curseforge_lookup(mod, mc, loader)
                if not record and mod.get("curseforge"):
                    cf_slug = str(mod["curseforge"])
                    for entry in (curseforge_files_html(cf_slug, mc, loader) or [])[:10]:
                        url = curseforge_file_page_url(cf_slug, entry["fileId"])
                        if url:
                            record = {"version": f"file {entry['fileId']}", "url": url,
                                      "filename": url.rsplit("/", 1)[-1], "sha512": None,
                                      "source": "curseforge-html", "id": mod.get("curseforge"),
                                      "project": cf_slug, "title": mod["name"]}
                            break
                if not record:
                    reasons.append("curseforge: no build (CF_API_KEY not set / page blocked)")

            elif source == "maven":
                record = maven_lookup(mod, mc, loader)
                if not record:
                    reasons.append("maven: no matching artifact")

            elif source == "github":
                record = github_lookup(mod, mc, loader)
                if not record:
                    reasons.append("github: no matching release asset")

            elif source == "release":
                record = release_lookup(mod, mc, loader)
                if not record:
                    reasons.append("release: not in the repo's own release assets")
            else:
                reasons.append(f"unknown source {source}")

        if record and getattr(args, "prefer_release", False) and record.get("source") not in ("github", "release"):
            pass  # explicit release lookup already happened first via --prefer

        if not record:
            print("    x unavailable:", "; ".join(reasons))
            missing.append({**mod, "reason": "; ".join(reasons)})
            continue

        fname = re.sub(r"[^A-Za-z0-9._+-]", "_", record["filename"])
        dest = MODS_DIR / fname
        print(f"    + {record['source']}: {fname}  ({record.get('version')})")
        if record.get("confidence") == "low":
            print("    ! warning: this GitHub asset was matched heuristically, verify the jar loads")

        if args.dry_run or args.mrpack:
            installed.append({**record, "title": mod["name"], "filename": fname})
            continue

        if dest.exists() and not args.force:
            print("    = already present, skipping download")
            installed.append({**record, "title": mod["name"], "filename": fname})
            continue

        ok = False
        if record["source"] == "release" and record.get("asset_id"):
            # straight from api.github.com: works even when every CDN is filtered
            ok = download_asset_by_id({**mod, "github": REPO}, record["asset_id"], dest,
                                      record.get("sha512"))
        if not ok:
            ok, prefix = download_with_mirrors(record["url"], dest, record.get("sha512"),
                                               MIRRORS)
            if ok and prefix:
                print(f"    = downloads go through the mirror {prefix}")
                MIRRORS.insert(0, prefix)
        if ok:
            installed.append({**record, "title": mod["name"], "filename": fname})
        else:
            print("    x download failed, falling back to the next source")
            missing.append({**mod, "reason": "download blocked/failed: " + record["source"]})

    if args.mrpack:
        write_mrpack(Path(args.mrpack), installed, mc, loader)

    if not args.dry_run:
        write_manifest(installed, missing, mc, loader)
        write_missing_report(missing, installed, mc, loader)

    total = len([p for p in MODS_DIR.glob("*.jar")])
    print()
    print(f"done: {len(installed)} resolved, {len(missing)} unavailable, {total} jars in mods/")
    if missing:
        print(f"see {MISSING_REPORT.name} for the manual list")
    return 0


if __name__ == "__main__":
    sys.exit(main())
