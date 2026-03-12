# my_game_hub.spec — PyInstaller build spec for My Game Hub
# Run on Windows: pyinstaller my_game_hub.spec

import os

a = Analysis(
    ['main.py'],
    pathex=['.'],
    datas=[('assets', 'assets')] if os.path.isdir('assets') else [],
    binaries=[],
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
    ],
    excludes=[
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuickWidgets',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DRender',
        'PySide6.QtWebEngine',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtMultimedia',
        'PySide6.QtBluetooth',
        'PySide6.QtNfc',
        'PySide6.QtLocation',
        'PySide6.QtPositioning',
    ],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name='MyGameHub',
    icon='assets/gamehub.ico',
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name='MyGameHub',
)
