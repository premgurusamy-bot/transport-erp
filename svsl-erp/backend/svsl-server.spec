# PyInstaller spec for the bundled Windows server:  pyinstaller svsl-server.spec
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hidden = collect_submodules("app") + collect_submodules("uvicorn") + collect_submodules("psycopg") + ["psycopg_binary", "alembic", "sqlalchemy.dialects.postgresql.psycopg"]
datas = [("alembic", "alembic")] + collect_data_files("reportlab") + collect_data_files("alembic")

a = Analysis(["svsl_server.py"], pathex=["."], hiddenimports=hidden, datas=datas, excludes=["pytest", "tkinter"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="svsl-server", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="svsl-server")
