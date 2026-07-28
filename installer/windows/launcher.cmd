@echo off
setlocal EnableExtensions
set "APP_ROOT=%~dp0"
set "CURRENT_FILE=%APP_ROOT%current.txt"
if not exist "%CURRENT_FILE%" (
    echo Public Real Time Checker n'a pas de version active.
    echo Relance Setup.bat depuis le dossier extrait.
    pause
    exit /b 1
)
set "RELEASE_DIR="
set /p "RELEASE_DIR="<"%CURRENT_FILE%"
if not defined RELEASE_DIR goto :invalid
if not exist "%RELEASE_DIR%\.venv\Scripts\pythonw.exe" goto :invalid
start "" /D "%APP_ROOT%" "%RELEASE_DIR%\.venv\Scripts\pythonw.exe" -m sc_web_companion
exit /b 0
:invalid
echo La version active est incomplete :
echo %RELEASE_DIR%
echo Relance Setup.bat.
pause
exit /b 1
