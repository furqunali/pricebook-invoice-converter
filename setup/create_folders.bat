@echo off
REM ============================================================
REM  Invoice Converter - DATA folders
REM  EDIT the BASE line to your own data location, then double-click.
REM  (Code stays with the owner's private copy; only DATA goes here.)
REM ============================================================
set "BASE=C:\InvoiceConverterData"
REM ============================================================
echo Creating data folders under: %BASE%
mkdir "%BASE%"                                  2>nul
mkdir "%BASE%\invoices\1-incoming"              2>nul
mkdir "%BASE%\invoices\2-converted"             2>nul
mkdir "%BASE%\invoices\3-review"                2>nul
mkdir "%BASE%\invoices\3-review\reprocess"      2>nul
mkdir "%BASE%\invoices\4-archive"               2>nul
mkdir "%BASE%\invoices\5-pdi-dropzone"          2>nul
mkdir "%BASE%\reports"                          2>nul
mkdir "%BASE%\logs"                             2>nul
mkdir "%BASE%\logs\chat"                        2>nul
mkdir "%BASE%\Sample Past Invoices"             2>nul
echo.
echo Done. Team drops mixed vendor PDFs into %BASE%\invoices\1-incoming
echo Code + prompt master stay on your Desktop (private).
pause
