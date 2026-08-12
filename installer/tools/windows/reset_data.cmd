@echo off
setlocal
chcp 65001 >nul
set "DATA_DIR=%LOCALAPPDATA%\SCRTLTPublicData"
set "CONFIG_DIR=%APPDATA%\SCRTLTPublic"
echo ATTENTION : cette action efface les reglages, les onglets personnalises,
echo les cookies, les sessions et les identifiants chiffres enregistres.
echo Le registre SC-RTLT Public est conserve.
echo.
choice /C ON /M "Continuer ? O=Oui, N=Non"
if errorlevel 2 exit /b 0
if exist "%DATA_DIR%\web-profile" rmdir /s /q "%DATA_DIR%\web-profile"
if exist "%DATA_DIR%\web-cache" rmdir /s /q "%DATA_DIR%\web-cache"
if exist "%CONFIG_DIR%" rmdir /s /q "%CONFIG_DIR%"
echo Donnees locales reinitialisees. Registre conserve.
pause
