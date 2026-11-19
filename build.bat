@echo off
setlocal
cd /d "%~dp0"
echo === 1/4 Installing requirements ===
python -m pip install --upgrade pip
python -m pip install psutil pystray pillow pyinstaller || goto error

echo === 2/4 Creating icon ===
python net_speed_monitor.py --make-icon || goto error

echo === 3/4 Building NetSpeedMonitor.exe ===
python -m PyInstaller --onefile --noconsole --clean --name NetSpeedMonitor --icon app.ico net_speed_monitor.py || goto error

echo === 4/4 Building installer ===
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" goto noinno
"%ISCC%" installer.iss || goto error
echo.
echo DONE. Installer: installer_output\NetSpeedMonitor_Setup.exe
goto end

:noinno
echo.
echo The program is ready: dist\NetSpeedMonitor.exe
echo To also build the Setup file, install Inno Setup 6 from https://jrsoftware.org/isdl.php
echo then run build.bat again.
goto end

:error
echo.
echo Build failed. Check the messages above.

:end
pause
