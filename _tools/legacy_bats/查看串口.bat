@echo off
cd /d "%~dp0..\.."
chcp 936 >nul
title 查看串口
echo 当前电脑上的串口设备:
echo.
python -c "import serial.tools.list_ports as L; ps=list(L.comports()); [print('  %s  (%s)' % (p.device, p.description)) for p in ps] if ps else print('  (没有检测到任何串口设备——检查线是否插好/是否数据线)')"
echo.
echo 设备管理器位置: Win+X -> 设备管理器 -> 端口(COM 和 LPT) -> USB-SERIAL CH340 (COMx)
echo 若在[其他设备]里看到带感叹号的 USB2.0-Serial = CH340 驱动没装，装 WCH 官方 CH341SER
pause
