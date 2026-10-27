@echo off
title "Zen Data Protsk - QR Verification & Accuracy Engine"
cls

echo ========================================================
echo     ZEN DATA PROTSK - QR SUBMISSION VERIFICATION HUB
echo ========================================================
echo  Compares website submitted forms directly against
echo  source card images (Zero internal database dependency).
echo ========================================================
echo.

if not "%~1"=="" (
    if not "%~2"=="" (
        echo [*] Running verification for range: QRCode - %~1 to QRCode - %~2...
        python verify_engine.py --start %~1 --end %~2
        echo.
        pause
        exit /b
    ) else (
        echo [*] Running verification for single: QRCode - %~1...
        python verify_engine.py --qr %~1
        echo.
        pause
        exit /b
    )
)

echo  [1] Verify ALL Submitted QRs on Website (Full Auto Check)
echo  [2] Verify Custom Range (e.g. QRs 1 to 50)
echo  [3] Verify Single Specific QR Code
echo  [4] View Verification Summary & Accuracy Report in Terminal
echo  [5] Launch Web Dashboard to "Verify Submissions" Tab
echo  [6] Exit
echo.
echo ========================================================
set /p choice="Enter your choice (1-6) [Default: 1]: "

if "%choice%"=="" set choice=1
if "%choice%"=="1" goto verify_all
if "%choice%"=="2" goto verify_custom
if "%choice%"=="3" goto verify_single
if "%choice%"=="4" goto verify_stats
if "%choice%"=="5" goto open_dashboard
if "%choice%"=="6" exit
goto verify_all

:verify_all
echo.
echo [*] Starting verification for ALL submitted QRs on the portal...
python verify_engine.py --start 1
echo.
pause
exit /b

:verify_custom
echo.
set /p start_num="Enter Start QR number [Default: 1]: "
if "%start_num%"=="" set start_num=1
set /p end_num="Enter End QR number: "
if "%end_num%"=="" (
    python verify_engine.py --start %start_num%
) else (
    python verify_engine.py --start %start_num% --end %end_num%
)
echo.
pause
exit /b

:verify_single
echo.
set /p single_qr="Enter QR number to verify (e.g. 1 or 153): "
if "%single_qr%"=="" set single_qr=1
python verify_engine.py --qr %single_qr%
echo.
pause
exit /b

:verify_stats
echo.
python verify_engine.py --stats
echo.
pause
exit /b

:open_dashboard
echo.
echo [*] Launching Web Dashboard on http://localhost:5000 ...
start "" http://localhost:5000
python web_dashboard.py
pause
exit /b
