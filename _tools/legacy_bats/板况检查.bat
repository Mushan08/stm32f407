@echo off
chcp 936 >nul
cd /d "%~dp0..\.."
title F407 板况检查
echo [板况检查] 免 halt 采样 uwTick + GPIOE，约 10 秒，自动判定: 活着/冻结/灯不转/欠压史
echo   前提: ST-Link 四线已接、Type-C 已拔（铁律1）、GDB调试服务没开着
echo.
python -I _tools\probe.py
echo.
pause
