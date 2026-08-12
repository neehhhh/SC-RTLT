@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "APP_ROOT=%LOCALAPPDATA%\SCRTLTPublic"
set "DATA_DIR=%LOCALAPPDATA%\SCRTLTPublicData"
set "CONFIG_DIR=%APPDATA%\SCRTLTPublic"
if exist "%APP_ROOT%\stop_running_app.ps1" powershell -NoProfile -ExecutionPolicy Bypass -File "%APP_ROOT%\stop_running_app.ps1" -AppRoot "%APP_ROOT%" >nul 2>&1
timeout /t 1 /nobreak >nul
if exist "%APP_ROOT%" rmdir /s /q "%APP_ROOT%"
if exist "%DATA_DIR%\web-profile" rmdir /s /q "%DATA_DIR%\web-profile"
if exist "%DATA_DIR%\web-cache" rmdir /s /q "%DATA_DIR%\web-cache"
if exist "%CONFIG_DIR%" rmdir /s /q "%CONFIG_DIR%"
del /q "%USERPROFILE%\Desktop\SC-RTLT Public.lnk" >nul 2>&1
del /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\SC-RTLT Public.lnk" >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v SCRTLTPublic /f >nul 2>&1
echo Desinstallation terminee.
echo Le registre est conserve dans :
echo %DATA_DIR%\registry\SC-RTLT_Public_Registry.json
pause
