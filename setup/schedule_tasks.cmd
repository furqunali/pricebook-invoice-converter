@echo off
REM ============================================================
REM  Register the 2x-daily batch + a review re-run in Windows Task Scheduler.
REM  RUN AS ADMINISTRATOR, on the always-on server.
REM
REM  DO THIS FIRST (see setup\PHASE3_DEPLOY.md):
REM    1. Confirm the data folder path in config\settings.yaml.
REM    2. Set ANTHROPIC_API_KEY as a MACHINE (system) environment variable.
REM    3. Run the API preflight (convert one real invoice) and confirm it ties out.
REM  Times are configurable; defaults follow docs\BATCH_PROCESSING.md.
REM ============================================================
set "HERE=%~dp0"

schtasks /Create /TN "Invoice Converter - Batch AM" /TR "\"%HERE%run_batch.cmd\""  /SC DAILY /ST 11:45 /RL HIGHEST /F
schtasks /Create /TN "Invoice Converter - Batch PM" /TR "\"%HERE%run_batch.cmd\""  /SC DAILY /ST 17:45 /RL HIGHEST /F
schtasks /Create /TN "Invoice Converter - Review"   /TR "\"%HERE%run_review.cmd\"" /SC DAILY /ST 18:15 /RL HIGHEST /F

echo.
echo Registered: Batch AM (11:45), Batch PM (17:45), Review (18:15).
echo Verify with:  schtasks /Query /TN "Invoice Converter - Batch AM"
pause
