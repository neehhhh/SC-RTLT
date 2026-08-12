@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "APP_ROOT=%LOCALAPPDATA%\SCRTLTPublic"
set "CURRENT_FILE=%APP_ROOT%\current.txt"
set "CONFIG_DIR=%APPDATA%\SCRTLTPublic"
set "DATA_DIR=%LOCALAPPDATA%\SCRTLTPublicData"
set "OUT=%USERPROFILE%\Desktop\SC-RTLT_Public_Diagnostic.txt"
set "REGISTRY_FILE=%DATA_DIR%\registry\SC-RTLT_Public_Registry.json"
set "RELEASE_DIR="
if exist "%CURRENT_FILE%" set /p "RELEASE_DIR="<"%CURRENT_FILE%"
>"%OUT%" echo SC-RTLT Public - Diagnostic
>>"%OUT%" echo Date : %DATE% %TIME%
>>"%OUT%" echo Version active : %RELEASE_DIR%
>>"%OUT%" echo Configuration : %CONFIG_DIR%
>>"%OUT%" echo Donnees : %DATA_DIR%
>>"%OUT%" echo Registre : %REGISTRY_FILE%
if exist "%REGISTRY_FILE%" (>>"%OUT%" echo Registre present) else (>>"%OUT%" echo Registre non cree)
>>"%OUT%" echo.
if defined RELEASE_DIR if exist "%RELEASE_DIR%\.venv\Scripts\python.exe" (
    "%RELEASE_DIR%\.venv\Scripts\python.exe" -c "import sys,sc_web_companion,PySide6; print(sys.version); print('SC-RTLT Public',sc_web_companion.__version__); print('PySide6',PySide6.__version__)" >>"%OUT%" 2>&1
) else (
    >>"%OUT%" echo Version active absente ou incomplete.
)
>>"%OUT%" echo.
>>"%OUT%" echo --- Journal d'installation ---
if exist "%TEMP%\SC-RTLT_Public-install.log" type "%TEMP%\SC-RTLT_Public-install.log" >>"%OUT%"
echo Rapport cree : %OUT%
pause
