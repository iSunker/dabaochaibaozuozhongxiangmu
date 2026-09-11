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
REM
REM 2>> keeps ONLY stderr (tracebacks / hard-crash messages).
REM   Why: under the Task Scheduler this console goes nowhere, so until now an
REM   unhandled traceback was invisible -- the process would just "vanish".
REM   drive-loop.log only gets what goes through the logging module; anything
REM   raised outside its try blocks lands here instead. Append-only and tiny.
REM
REM ---- 起跑/收尾留痕 (2026-09-11) ----
REM   背景：批次会「凭空消失」—— drive-loop.log 停在半路，没有 traceback，
REM   连 finally 里的状态收尾都没执行。能造成这种效果只有 TerminateProcess
REM   这一种（异常/崩溃都会留下痕迹）。python 自己被抹掉时什么都写不了，
REM   所以把留痕放到 cmd 这一层：
REM     * 起来先记一行 start
REM     * 结束后记退出码 —— 这是**完整 32 位码**，能区分
REM         0xC000013A = 控制台被关闭 / 整棵进程树被终止
REM         != 0       = 被 TerminateProcess 传入了这个值
REM         0          = 自己正常退出（那就说明问题在 python 内部）
REM   ★ 如果连 "exit=" 这一行都没出现 —— 说明 cmd 自己也被一起抹掉了，
REM     那本身就是「整个任务实例被强杀」的直接证据。
echo [%DATE% %TIME%] start >> "%~dp0drive-loop.attempts.log"
"%PY%" "%SCRIPT%" --once --indexers HDFans,NanyangPT --limit 50 2>> "%~dp0drive-loop.task.err"
set "RC=%ERRORLEVEL%"
echo [%DATE% %TIME%] exit=%RC% >> "%~dp0drive-loop.attempts.log"
exit /b %RC%
