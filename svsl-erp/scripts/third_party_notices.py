"""Generate the third-party licence notices shipped with A Prime Transport ERP.

    python scripts/third_party_notices.py            # run from svsl-erp/, with the backend requirements installed

Reads the packages that are actually installed (Python) and the production npm packages of the web app and the
Android wrapper, so the notices always match what is shipped. Writes:

    THIRD_PARTY_NOTICES.md             summary table + licence obligations (repository, server bundle)
    third-party-licenses.txt           summary + full licence texts
    frontend/public/third-party-licenses.txt, mobile/www/third-party-licenses.txt   copies served by the apps

Run it on the platform being packaged (the Windows build runs it on Windows), because some Python dependencies
are platform specific.
"""
from __future__ import annotations

import importlib.metadata as md
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIC = Path(__file__).resolve().parent / "licenses"
DEV_ONLY = {"pytest", "pyinstaller"}


# ------------------------------------------------------------------ Python
def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def python_packages() -> list[dict]:
    from packaging.requirements import Requirement

    roots: list[tuple[str, set[str]]] = []
    for line in (ROOT / "backend" / "requirements.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        r = Requirement(line)
        if _norm(r.name) not in DEV_ONLY:
            roots.append((r.name, set(r.extras)))
    seen: dict[str, dict] = {}
    stack = list(roots)
    while stack:
        name, extras = stack.pop()
        key = _norm(name)
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            print(f"  warning: {name} is not installed – skipped", file=sys.stderr)
            continue
        entry = seen.get(key)
        if entry is None:
            entry = seen[key] = {"dist": dist, "extras": set()}
        elif extras <= entry["extras"]:
            continue
        entry["extras"] |= extras
        for req in dist.requires or []:
            r = Requirement(req)
            envs = [{"extra": e} for e in (entry["extras"] or {""})]
            if r.marker is None or any(r.marker.evaluate(env) for env in envs):
                stack.append((r.name, set(r.extras)))
    out = []
    for key, e in sorted(seen.items()):
        d = e["dist"]
        meta = d.metadata
        lic = meta.get("License-Expression") or ""
        if not lic:
            classifiers = [c.split(" :: ")[-1] for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")]
            raw = (meta.get("License") or "").strip()
            lic = "; ".join(classifiers) or (raw if raw and len(raw) < 80 else (raw.splitlines()[0][:80] if raw else "see licence text"))
        texts = []
        for f in d.files or []:
            name = str(f)
            base = name.rsplit("/", 1)[-1].upper()
            if ".dist-info/" in name and (base.startswith(("LICEN", "COPYING", "NOTICE", "AUTHORS")) or "/licenses/" in name):
                try:
                    texts.append((name.split(".dist-info/")[-1], Path(d.locate_file(f)).read_text(encoding="utf-8", errors="replace")))
                except OSError:
                    pass
        url = meta.get("Home-page") or ""
        for pu in meta.get_all("Project-URL") or []:
            label, _, link = pu.partition(",")
            if not url or label.strip().lower() in ("source", "source code", "repository", "homepage"):
                url = link.strip()
        out.append({"name": meta["Name"], "version": d.version, "license": lic, "url": url, "texts": texts, "part": "Server (Python)"})
    return out


# ------------------------------------------------------------------ npm
def npm_packages(project: Path, part: str) -> list[dict]:
    if not (project / "node_modules").exists():
        print(f"  warning: {project}/node_modules missing – run npm ci first", file=sys.stderr)
        return []
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    res = subprocess.run([npm, "ls", "--omit=dev", "--all", "--parseable"], cwd=project, capture_output=True, text=True)
    out = []
    for line in sorted(set(res.stdout.splitlines())):
        p = Path(line.strip())
        if p.resolve() == project.resolve() or not (p / "package.json").exists():
            continue
        pkg = json.loads((p / "package.json").read_text(encoding="utf-8"))
        lic = pkg.get("license") or (pkg.get("licenses") or [{}])[0].get("type") or "see licence text"
        if isinstance(lic, dict):
            lic = lic.get("type", "see licence text")
        texts = [(f.name, f.read_text(encoding="utf-8", errors="replace")) for f in sorted(p.iterdir())
                 if f.is_file() and f.name.upper().startswith(("LICEN", "COPYING", "NOTICE"))]
        repo = pkg.get("repository")
        url = (repo.get("url") if isinstance(repo, dict) else repo) or pkg.get("homepage") or f"https://www.npmjs.com/package/{pkg['name']}"
        out.append({"name": pkg["name"], "version": pkg.get("version", ""), "license": lic, "url": url, "texts": texts, "part": part})
    return out


# ------------------------------------------------------------------ components that are not Python / npm packages
def bundled_components() -> list[dict]:
    apache = next((t for n, t in _pytexts("cryptography") if "APACHE" in n.upper()), "")
    comps = [
        {"name": "Python", "version": f"{sys.version_info.major}.{sys.version_info.minor}", "license": "PSF-2.0", "url": "https://www.python.org/",
         "part": "Windows server bundle", "texts": [("LICENSE.txt", _read(Path(sys.base_prefix) / "LICENSE.txt") or _read(Path(sys.base_prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt"))]},
        {"name": "PyInstaller bootloader", "version": _ver("pyinstaller"), "license": "GPL-2.0-or-later WITH Bootloader-exception", "url": "https://pyinstaller.org/",
         "part": "Windows server bundle", "texts": [t for t in _pytexts("pyinstaller")],
         "note": "Only the PyInstaller bootloader is included. Its licence has a special exception that allows it to be distributed with programs under any licence."},
        {"name": "PostgreSQL", "version": "16", "license": "PostgreSQL", "url": "https://www.postgresql.org/", "part": "Windows desktop (bundled database)", "texts": [("PostgreSQL copyright", _read(LIC / "PostgreSQL-copyright.txt"))]},
        {"name": "Libraries shipped with the PostgreSQL Windows binaries", "version": "", "url": "https://www.enterprisedb.com/download-postgresql-binaries", "part": "Windows desktop (bundled database)",
         "license": "OpenSSL (Apache-2.0), ICU (Unicode-3.0), libxml2 / libxslt (MIT), zlib (Zlib), lz4 (BSD-2-Clause), zstd (BSD-3-Clause), gettext libintl & libiconv (LGPL-2.1-or-later)",
         "texts": [("LGPL-2.1", _read(LIC / "LGPL-2.1.txt"))] + ([("Apache-2.0", apache)] if apache else []),
         "note": "Shipped unmodified as separate DLL files in the installation folder (resources\\pgsql\\bin); they can be replaced by the user. Source code: openssl.org, icu.unicode.org, gitlab.gnome.org/GNOME/libxml2, zlib.net, github.com/lz4/lz4, github.com/facebook/zstd, gnu.org/software/gettext and gnu.org/software/libiconv. Any licence files included in the PostgreSQL download are installed in resources\\pgsql\\licenses."},
        {"name": "Microsoft Visual C++ runtime (vcruntime140, msvcp140)", "version": "", "license": "Microsoft Visual Studio redistributable", "url": "https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files",
         "part": "Windows desktop (bundled database)", "texts": [], "note": "Redistributable runtime files, shipped unmodified."},
        {"name": "Electron (includes Chromium and Node.js)", "version": _npmver(ROOT / "desktop", "electron"), "license": "MIT (Electron); Chromium and Node.js components under their own licences",
         "url": "https://www.electronjs.org/", "part": "Windows desktop app", "texts": [("LICENSE", _read(ROOT / "desktop" / "node_modules" / "electron" / "LICENSE"))],
         "note": "The complete Chromium licence list is installed with the app as LICENSES.chromium.html (and LICENSE.electron.txt) in the installation folder."},
        {"name": "AndroidX libraries (appcompat, coordinatorlayout, core, core-splashscreen, webkit, activity, fragment)", "version": "", "license": "Apache-2.0",
         "url": "https://developer.android.com/jetpack/androidx", "part": "Android app", "texts": [("Apache-2.0", apache)] if apache else []},
        {"name": "Apache Cordova Android framework", "version": "10.1.1", "license": "Apache-2.0", "url": "https://cordova.apache.org/", "part": "Android app", "texts": []},
    ]
    return comps


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _ver(name: str) -> str:
    try:
        return md.version(name)
    except md.PackageNotFoundError:
        return ""


def _pytexts(name: str) -> list[tuple[str, str]]:
    try:
        d = md.distribution(name)
    except md.PackageNotFoundError:
        return []
    return [(str(f).split(".dist-info/")[-1], _read(Path(d.locate_file(f)))) for f in d.files or [] if ".dist-info/" in str(f) and str(f).rsplit("/", 1)[-1].upper().startswith(("LICEN", "COPYING"))]


def _npmver(project: Path, name: str) -> str:
    try:
        return json.loads((project / "node_modules" / name / "package.json").read_text())["version"]
    except OSError:
        return ""


# ------------------------------------------------------------------ output
OBLIGATIONS = """## Licence obligations and how A Prime Transport ERP meets them

* **Notices** – every component below keeps its copyright and licence notice. The full texts are in
  `third-party-licenses.txt`, which is shipped with the server, inside the Windows app and the Android app, and can be
  opened from the app under *Profile → About & licences*.
* **psycopg (LGPL-3.0)** – the PostgreSQL driver is used unmodified as a separate library. In the Windows server bundle
  it is shipped as plain, replaceable files (`_internal\\psycopg\\…` and `_internal\\psycopg_binary\\…`), so a user can
  replace it with a modified version, as the LGPL requires. Its source code is available at
  https://github.com/psycopg/psycopg (version listed below).
* **psycopg-binary** also contains the PostgreSQL client library (libpq, PostgreSQL licence) and OpenSSL (Apache-2.0),
  shipped unmodified as separate files.
* **certifi (MPL-2.0)** – the list of trusted certificate authorities is used unmodified; its source code is available at
  https://github.com/certifi/python-certifi.
* **LGPL libraries bundled with the PostgreSQL Windows binaries (gettext libintl, libiconv)** – shipped unmodified as
  separate, replaceable DLL files; source code is available from the GNU project.
* **PyInstaller bootloader** – GPL with an explicit exception that allows distribution with any program.
* **Fonts** – the Windows server bundle does not include ReportLab's sample fonts; PDFs use fonts already installed on
  the computer (DejaVu Sans / Segoe UI).
* **Apache-2.0 components** – their NOTICE files (where provided) are reproduced in `third-party-licenses.txt`.
"""


def main() -> None:
    py = python_packages()
    web = npm_packages(ROOT / "frontend", "Web app (browser, Windows app, Android app)")
    mob = npm_packages(ROOT / "mobile", "Android app")
    comps = py + web + mob + bundled_components()
    head = "# Third-party software in A Prime Transport ERP\n\nA Prime Transport ERP is built with the open-source components listed below. They remain the property of their authors and are used under their licences.\n" \
           f"Generated by `scripts/third_party_notices.py` on {sys.platform} (Python {sys.version_info.major}.{sys.version_info.minor}); {len(comps)} components.\n\n" + OBLIGATIONS
    rows = ["| Component | Version | Licence | Used in | Source |", "|---|---|---|---|---|"]
    for c in comps:
        rows.append(f"| {c['name']} | {c['version']} | {c['license']} | {c['part']} | {c['url']} |")
    md_text = head + "\n## Components\n\n" + "\n".join(rows) + "\n"
    (ROOT / "THIRD_PARTY_NOTICES.md").write_text(md_text, encoding="utf-8")

    parts = ["A Prime Transport ERP – THIRD-PARTY SOFTWARE NOTICES AND LICENCES", "=" * 60, "", re.sub(r"[`*]", "", head), ""]
    for c in comps:
        parts += ["", "-" * 78, f"{c['name']} {c['version']}".strip(), f"Licence: {c['license']}", f"Used in: {c['part']}", f"Source: {c['url']}"]
        if c.get("note"):
            parts.append(f"Note: {c['note']}")
        seen = set()
        for name, text in c["texts"]:
            if text and text not in seen:
                seen.add(text)
                parts += ["", f"--- {name} ---", text.strip()]
        if not c["texts"]:
            parts.append("(No separate licence file is distributed with this component; the licence named above applies.)")
    full = "\n".join(parts) + "\n"
    (ROOT / "third-party-licenses.txt").write_text(full, encoding="utf-8")
    for target in (ROOT / "frontend" / "public", ROOT / "mobile" / "www"):
        if target.exists():
            (target / "third-party-licenses.txt").write_text(full, encoding="utf-8")
    print(f"{len(comps)} components ({len(py)} Python, {len(web)} web, {len(mob)} Android npm); third-party-licenses.txt {len(full) // 1024} KB")
    missing = [c["name"] for c in comps if not c["texts"] and c["part"].startswith(("Server", "Web"))]
    if missing:
        print("  note: no licence file inside these packages (licence named in the table applies): " + ", ".join(missing))


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
