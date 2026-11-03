@echo off
title Zen Data Protsk - Live Terminal Automation
echo ========================================================
echo   STARTING LIVE AUTOMATION IN TERMINAL
echo   - Batch size: 35-48 forms in a row
echo   - Batch break: 10-17 minutes
echo   - Starting from next QR in queue
echo   - Stop anytime with Ctrl+C
echo ========================================================
python -u data_entry_automation.py --auto
pause
