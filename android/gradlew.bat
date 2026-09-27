@echo off
setlocal enabledelayedexpansion
set VERSION=8.9
set EXPECTED_SHA256=d725d707bfabd4dfdc958c624003b3c80accc03f7037b5122c4b1d0ef15cecab
set SCRIPT_DIR=%~dp0
set DIST_ROOT=%SCRIPT_DIR%.gradle-dist
set DIST_DIR=%DIST_ROOT%\gradle-%VERSION%
set ZIP=%DIST_ROOT%\gradle-%VERSION%-bin.zip
set URL=https://services.gradle.org/distributions/gradle-%VERSION%-bin.zip

if not exist "%DIST_DIR%\bin\gradle.bat" (
  if not exist "%DIST_ROOT%" mkdir "%DIST_ROOT%"
  if not exist "%ZIP%" (
    echo Downloading Gradle %VERSION%...
    powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%URL%' -OutFile '%ZIP%'"
    if errorlevel 1 exit /b 1
  )

  for /f "tokens=*" %%H in ('powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 '%ZIP%').Hash.ToLower()"') do set ACTUAL_SHA256=%%H
  if /I not "!ACTUAL_SHA256!"=="%EXPECTED_SHA256%" (
    echo Gradle distribution checksum mismatch.
    echo Expected: %EXPECTED_SHA256%
    echo Actual:   !ACTUAL_SHA256!
    del /q "%ZIP%"
    exit /b 1
  )

  if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
  powershell -NoProfile -Command "Expand-Archive -Force '%ZIP%' '%DIST_ROOT%'"
  if errorlevel 1 exit /b 1
)

call "%DIST_DIR%\bin\gradle.bat" %*
