@echo off
REM ============================================================
REM  Invoice Converter - daily BATCH (Task Scheduler calls this 2x/day)
REM  Preflight (once): confirm the data folder path in config\settings.yaml,
REM  set ANTHROPIC_API_KEY as a MACHINE env var, and `pip install -e .[extract]`.
REM ============================================================
setlocal
set "CODE=%~dp0.."
cd /d "%CODE%"
set "PYTHONPATH=%CODE%\src"

if "%ANTHROPIC_API_KEY%"=="" (
  echo [ERROR] ANTHROPIC_API_KEY is not set - aborting batch. 1>&2
  exit /b 2
)

if exist "%CODE%\.venv\Scripts\python.exe" (
  "%CODE%\.venv\Scripts\python.exe" -m pdi_invoice_converter.cli batch
) else (
  python -m pdi_invoice_converter.cli batch
)
exit /b %ERRORLEVEL%
