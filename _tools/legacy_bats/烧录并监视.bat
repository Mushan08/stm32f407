@echo off
chcp 936 >nul
cd /d "%~dp0..\.."
title F407 编译+烧录+串口监视
echo ======== 1/3 编译 ========
call "%~dp0构建.bat" nopause
if errorlevel 1 (
  echo [失败] 编译未通过，不烧录
  pause
  exit /b 1
)
echo.
echo ======== 2/3 烧录 ST-Link ========
"E:\zwork\dev-toolkit\tools\openocd\xpack-openocd-0.12.0-7\bin\openocd.exe" -f openocd\f407vet6.cfg -c "adapter speed 300" -c "reset_config none" -c "program build/f407.elf verify reset exit"
if errorlevel 1 (
  echo [失败] 烧录出错，检查: ST-Link / SWD 四根线 / 板子供电 / GDB服务占用
  pause
  exit /b 1
)
echo.
echo [成功] 固件已复位运行
echo.
echo ======== 3/3 串口监视 115200 ========
echo   printf 物理出口 = H1 排针的 CH340N；没接 H1 飞线时看不到打印（固件照常跑）
echo.
set "COM="
for /f "delims=" %%P in ('python -c "import serial.tools.list_ports as L; ps=[p.device for p in L.comports() if 'CH34' in p.description.upper()]; print(ps[0] if ps else '')"') do set COM=%%P
if not defined COM (
  echo [提示] 没找到 CH340 串口 -> 想看打印: H1 排针 1=GND 2=D- 3=D+ 接 USB 线到电脑
  pause
  exit /b 0
)
echo [监视 %COM% @115200] 退出按 Ctrl+]
python -m serial.tools.miniterm %COM% 115200
pause
