# my_game_hub.spec — PyInstaller build spec for My Game Hub
# Run on Windows: pyinstaller my_game_hub.spec

import os
from PyInstaller.utils.hooks import collect_all

pyside6_datas, pyside6_binaries, pyside6_hiddenimports = collect_all('PySide6')

a = Analysis(
    ['main.py'],
    pathex=['.'],
    datas=pyside6_datas + ([('assets', 'assets')] if os.path.isdir('assets') else []),
    binaries=pyside6_binaries,
    hiddenimports=pyside6_hiddenimports,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name='MyGameHub',
    icon='assets/icon.ico',
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name='MyGameHub',
)
