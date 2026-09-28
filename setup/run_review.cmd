@echo off
REM ============================================================
REM  Invoice Converter - REVIEW re-run (produces R-n from reprocess\)
REM  Same preflight as run_batch.cmd. Can be scheduled or triggered on demand.
REM ============================================================
setlocal
set "CODE=%~dp0.."
cd /d "%CODE%"
set "PYTHONPATH=%CODE%\src"

if "%ANTHROPIC_API_KEY%"=="" (
  echo [ERROR] ANTHROPIC_API_KEY is not set - aborting review-run. 1>&2
  exit /b 2
)

if exist "%CODE%\.venv\Scripts\python.exe" (
  "%CODE%\.venv\Scripts\python.exe" -m pdi_invoice_converter.cli review-run
) else (
  python -m pdi_invoice_converter.cli review-run
)
exit /b %ERRORLEVEL%
