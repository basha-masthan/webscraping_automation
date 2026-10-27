@echo off
title Zen Data Protsk Control Hub
cls
echo ========================================================
echo        ZEN DATA PROTSK - AUTOMATION & DASHBOARD
echo ========================================================
echo.
echo  [1] Start Automated Data Entry Loop (Normal - Next QR)
echo  [2] Fill Unfilled Previous Forms First, Then Continue Next QRs
echo  [3] Open Web Dashboard (View QRs, Unfilled Forms & Verification)
echo  [4] Start BOTH Automation + Web Dashboard
echo  [5] View DB Stats & Unfilled Forms in Terminal
echo  [6] Verify Submitted QRs & Accuracy Cross-Check (verify_run)
echo  [7] Exit
echo.
echo ========================================================
set /p choice="Enter your choice (1-7) [Default: 1]: "

if "%choice%"=="" set choice=1
if "%choice%"=="1" goto run_automation
if "%choice%"=="2" goto run_unfilled_first
if "%choice%"=="3" goto run_dashboard
if "%choice%"=="4" goto run_both
if "%choice%"=="5" goto run_stats
if "%choice%"=="6" goto run_verify
if "%choice%"=="7" exit
goto run_automation


:run_automation
echo.
echo [*] Starting Data Entry Automation Loop (Normal)...
python data_entry_automation.py
pause
exit

:run_unfilled_first
echo.
echo [*] Starting Automation: Filling Unfilled Forms First, Then Continuing...
python data_entry_automation.py --fill-unfilled-first
pause
exit

:run_dashboard
echo.
echo [*] Starting Web Dashboard on http://localhost:5000 ...
python web_dashboard.py
pause
exit

:run_both
echo.
echo [*] Launching Web Dashboard in background...
start "" python web_dashboard.py
timeout /t 2 /nobreak >nul
echo [*] Starting Data Entry Automation Loop...
python data_entry_automation.py
pause
exit

:run_stats
echo.
python data_entry_automation.py --stats
python data_entry_automation.py --unfilled
echo.
pause
exit

:run_verify
echo.
call verify_run.bat
exit

