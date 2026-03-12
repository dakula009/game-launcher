@echo off
echo This will remove My Game Hub and all its data.
echo.
echo The following will be deleted:
echo   - App folder: %~dp0
echo   - User data:  %APPDATA%\MyGameHub\
echo.
set /p confirm=Are you sure? Type YES to confirm:
if /i not "%confirm%"=="YES" (
    echo Cancelled.
    pause
    exit /b 0
)

echo.
echo Removing user data...
if exist "%APPDATA%\MyGameHub\" (
    rmdir /s /q "%APPDATA%\MyGameHub\"
    echo Done.
) else (
    echo No user data found, skipping.
)

echo.
echo Removing app folder...
cd /d "%USERPROFILE%"
rmdir /s /q "%~dp0"

echo.
echo My Game Hub has been removed.
pause
