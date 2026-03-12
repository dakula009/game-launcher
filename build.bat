@echo off
cd /d "%~dp0"

:: Auto-detect conda installation
set CONDA_PATH=%USERPROFILE%\anaconda3
if not exist "%CONDA_PATH%" set CONDA_PATH=%USERPROFILE%\miniconda3
if not exist "%CONDA_PATH%" set CONDA_PATH=C:\ProgramData\anaconda3
if not exist "%CONDA_PATH%" set CONDA_PATH=C:\ProgramData\miniconda3
if not exist "%CONDA_PATH%" (
    echo ERROR: Could not find Anaconda/Miniconda installation.
    pause & exit /b 1
)

:: Activate conda env
call "%CONDA_PATH%\Scripts\activate.bat" "%CONDA_PATH%\envs\py310"
if errorlevel 1 (
    echo ERROR: Failed to activate conda env py310.
    pause & exit /b 1
)

pip install --upgrade pyinstaller --quiet

pyinstaller my_game_hub.spec --clean
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    pause & exit /b 1
)

echo.
echo Copying Qt DLLs from conda env to fix ordinal errors...
for %%f in ("%CONDA_PREFIX%\Lib\site-packages\PySide6\Qt6*.dll") do (
    copy /y "%%f" "dist\MyGameHub\" >nul
)

echo.
echo Done! Your app is in: dist\MyGameHub\
echo Run: dist\MyGameHub\MyGameHub.exe
pause
