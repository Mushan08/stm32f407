@echo off
cd /d "%~dp0..\.."
chcp 936 >nul
title F407 串口监视 115200
echo 本机串口:
python -c "import serial.tools.list_ports as L; [print('  ' + p.device + '  ' + p.description) for p in L.comports()]"
echo.
set "COM="
set /p COM=输入 COM 口后回车 (如 COM5，直接回车默认 COM5):
if not defined COM set COM=COM5
echo [监视 %COM% @115200] 退出按 Ctrl+]
python -m serial.tools.miniterm %COM% 115200
pause
