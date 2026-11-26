# PyInstaller spec for the bundled Windows server:  pyinstaller svsl-server.spec
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hidden = collect_submodules("app") + collect_submodules("uvicorn") + collect_submodules("psycopg") + ["psycopg_binary", "alembic", "sqlalchemy.dialects.postgresql.psycopg"]
# ReportLab's bundled font files are not used (PDFs use the system's DejaVu Sans / Segoe UI), so they are not shipped:
# this also keeps the GPL-licensed DarkGarden sample font out of the installer.
datas = [("alembic", "alembic")] + collect_data_files("alembic") + [("../THIRD_PARTY_NOTICES.md", "."), ("../third-party-licenses.txt", ".")]

# psycopg is LGPL-3.0: ship it as plain .py files (not inside the PYZ archive) so a user can replace it with a modified
# version, as the LGPL requires. Its compiled part (psycopg_binary) is already shipped as separate DLL / .pyd files.
a = Analysis(["svsl_server.py"], pathex=["."], hiddenimports=hidden, datas=datas, excludes=["pytest", "tkinter"],
             module_collection_mode={"psycopg": "py"})
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="svsl-server", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="svsl-server")
