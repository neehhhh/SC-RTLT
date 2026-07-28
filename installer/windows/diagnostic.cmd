@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "APP_ROOT=%LOCALAPPDATA%\PublicRealTimeChecker"
set "CURRENT_FILE=%APP_ROOT%\current.txt"
set "CONFIG_DIR=%APPDATA%\PublicRealTimeChecker"
set "DATA_DIR=%LOCALAPPDATA%\PublicRealTimeCheckerData"
set "OUT=%USERPROFILE%\Desktop\Public_Real_Time_Checker_Diagnostic.txt"
set "REGISTRY_FILE=%DATA_DIR%\registry\Public_Real_Time_Checker_Registry.json"
set "RELEASE_DIR="
if exist "%CURRENT_FILE%" set /p "RELEASE_DIR="<"%CURRENT_FILE%"
>"%OUT%" echo Public Real Time Checker - Diagnostic
>>"%OUT%" echo Date : %DATE% %TIME%
>>"%OUT%" echo Version active : %RELEASE_DIR%
>>"%OUT%" echo Configuration : %CONFIG_DIR%
>>"%OUT%" echo Donnees : %DATA_DIR%
>>"%OUT%" echo Registre : %REGISTRY_FILE%
if exist "%REGISTRY_FILE%" (>>"%OUT%" echo Registre present) else (>>"%OUT%" echo Registre non cree)
>>"%OUT%" echo.
if defined RELEASE_DIR if exist "%RELEASE_DIR%\.venv\Scripts\python.exe" (
    "%RELEASE_DIR%\.venv\Scripts\python.exe" -c "import sys,sc_web_companion,PySide6; print(sys.version); print('Public Real Time Checker',sc_web_companion.__version__); print('PySide6',PySide6.__version__)" >>"%OUT%" 2>&1
) else (
    >>"%OUT%" echo Version active absente ou incomplete.
)
>>"%OUT%" echo.
>>"%OUT%" echo --- Journal d'installation ---
if exist "%TEMP%\Public_Real_Time_Checker-install.log" type "%TEMP%\Public_Real_Time_Checker-install.log" >>"%OUT%"
echo Rapport cree : %OUT%
pause
