# my_game_hub.spec — PyInstaller build spec for My Game Hub
# Run on Windows: pyinstaller my_game_hub.spec

import os
from PyInstaller.utils.hooks import collect_binaries, collect_data_files

a = Analysis(
    ['main.py'],
    pathex=['.'],
    datas=(collect_data_files('PySide6', includes=['*.pyi'])
           + ([('assets', 'assets')] if os.path.isdir('assets') else [])),
    binaries=collect_binaries('PySide6'),
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
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name='MyGameHub',
)
