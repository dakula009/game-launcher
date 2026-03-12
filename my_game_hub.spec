# my_game_hub.spec — PyInstaller build spec for My Game Hub
# Run on Windows: pyinstaller my_game_hub.spec

import os
a = Analysis(
    ['main.py'],
    pathex=['.'],
    datas=[('assets', 'assets')] if os.path.isdir('assets') else [],
    hiddenimports=[],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name='MyGameHub',
    icon='assets/icon.ico',
    console=False,  # no terminal window
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name='MyGameHub',
)
