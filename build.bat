@echo off
cd /d "%~dp0"
pip install pyinstaller --quiet
pyinstaller my_game_hub.spec --clean
echo.
echo Done! Your app is in: dist\MyGameHub\
echo Run: dist\MyGameHub\MyGameHub.exe
pause
