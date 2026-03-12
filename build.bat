@echo off
cd /d "%~dp0"
pip install --upgrade pyinstaller --quiet
pyinstaller my_game_hub.spec --clean

echo.
echo Copying Qt DLLs from conda env to fix ordinal errors...
for %%f in ("%CONDA_PREFIX%\Lib\site-packages\PySide6\Qt6*.dll") do (
    copy /y "%%f" "dist\MyGameHub\" >nul
)

echo.
echo Done! Your app is in: dist\MyGameHub\
echo Run: dist\MyGameHub\MyGameHub.exe
pause
