@echo off
REM Update OLT MONITOR - kode diganti, folder data & .env tetap
REM Usage: update.bat C:\path\to\zte_c320_monitor.zip

set APP_DIR=%~dp0
set APP_DIR=%APP_DIR:~0,-1%
set ZIP=%~1

if "%ZIP%"=="" (
  echo Usage: update.bat path\to\zte_c320_monitor.zip
  exit /b 1
)

set BACKUP=%APP_DIR%\.backup_%DATE:~6,4%%DATE:~3,2%%DATE:~0,2%_%RANDOM%
mkdir "%BACKUP%" 2>nul
if exist "%APP_DIR%\data" xcopy /E /I /Y "%APP_DIR%\data" "%BACKUP%\data\" >nul
if exist "%APP_DIR%\.env" copy /Y "%APP_DIR%\.env" "%BACKUP%\.env" >nul

set TMP=%TEMP%\olt_upd_%RANDOM%
mkdir "%TMP%"
powershell -Command "Expand-Archive -Path '%ZIP%' -DestinationPath '%TMP%' -Force"

set SRC=%TMP%\zte_c320_monitor
if not exist "%SRC%" set SRC=%TMP%

echo Updating code from %SRC% ...
xcopy /E /Y /I "%SRC%\*.py" "%APP_DIR%\" >nul
xcopy /E /Y /I "%SRC%\templates" "%APP_DIR%\templates\" >nul
if exist "%SRC%\static" xcopy /E /Y /I "%SRC%\static" "%APP_DIR%\static\" >nul
copy /Y "%SRC%\requirements.txt" "%APP_DIR%\" >nul
copy /Y "%SRC%\VERSION" "%APP_DIR%\" >nul
copy /Y "%SRC%\README.md" "%APP_DIR%\" >nul
copy /Y "%SRC%\CHANGELOG.md" "%APP_DIR%\" >nul
copy /Y "%SRC%\update.sh" "%APP_DIR%\" >nul
copy /Y "%SRC%\update.bat" "%APP_DIR%\" >nul

REM restore data if missing
if not exist "%APP_DIR%\data" if exist "%BACKUP%\data" xcopy /E /I /Y "%BACKUP%\data" "%APP_DIR%\data\" >nul
if not exist "%APP_DIR%\.env" if exist "%BACKUP%\.env" copy /Y "%BACKUP%\.env" "%APP_DIR%\.env" >nul

echo Done. Backup: %BACKUP%
echo Restart: python app.py
