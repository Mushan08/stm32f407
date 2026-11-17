@echo off
chcp 936 >nul
cd /d "%~dp0..\.."
title F407 HardFault 取证
echo [HardFault 取证] 免 halt 读 g_fault_capture + addr2line 直出崩溃源码行
echo   前提: 板子全灯急闪中、还没按复位（复位/断电=现场清零）
echo.
python -I _tools\fault.py
echo.
pause
