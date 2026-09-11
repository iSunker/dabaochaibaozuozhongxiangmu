@echo off
REM ---------------------------------------------------------------
REM  Windows scheduled-task entry point for drive-loop.py
REM
REM  Why a wrapper:
REM   1. The python.exe path contains a non-ASCII user name, which
REM      schtasks / MINGW mangles when passed on a command line.
REM      %USERPROFILE% is expanded by cmd.exe at RUN time, so the
REM      task definition itself stays pure ASCII.
REM   2. Keeps the whole invocation in one reviewable place.
REM
REM  Registered by:
REM   schtasks /Create /TN "reseed-drive-loop" /F /SC MINUTE /MO 15 ^
REM     /TR "D:\Projects\dabaochaibaozuozhongxiangmu\reseed-toolkit\scripts\drive-loop-once.cmd"
REM ---------------------------------------------------------------
setlocal

set "PY=%USERPROFILE%\AppData\Local\Python\pythoncore-3.14-64\python.exe"
set "SCRIPT=%~dp0drive-loop.py"

if not exist "%PY%" (
  echo [!!] python not found: %PY%
  exit /b 2
)
if not exist "%SCRIPT%" (
  echo [!!] drive-loop.py not found: %SCRIPT%
  exit /b 2
)

REM --once = run at most one batch, then exit.
REM The script self-throttles via scripts\.drive-loop.state:
REM   * a batch already running  -> exits immediately
REM   * last batch ended <30min ago -> exits immediately
REM so a 15-minute wake-up can never overlap a ~24-minute batch.
REM Real progress lives in scripts\drive-loop.log -- not in this console.
"%PY%" "%SCRIPT%" --once --indexers HDFans,NanyangPT --limit 50
exit /b %ERRORLEVEL%
