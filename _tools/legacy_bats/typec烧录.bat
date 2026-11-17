@echo off
chcp 936 >nul
cd /d "%~dp0..\.."
title F407 Type-C 串口烧录
echo ======== 1/2 编译 ========
call "%~dp0构建.bat" nopause
if errorlevel 1 (
  echo [失败] 编译未通过，不烧录
  pause
  exit /b 1
)
echo.
echo ======== 2/2 Type-C 串口烧录 (CH340N - USART1 bootloader) ========
echo.
echo 操作步骤:
echo   1. Type-C 数据线连接电脑（设备管理器能看到 CH340 串口）
echo   2. 按住 SW1 (BOOT0) 不放
echo   3. 按一下 SW2 (NRST) 复位
echo   4. 松开 SW1，然后按任意键开始烧录
echo.
pause
python -I _tools\flasher.py -f build\f407.hex
if errorlevel 1 (
  echo [失败] 烧录未完成，按上方提示排查后重试
  echo   或跑主菜单 6 查看串口是否枚举出来
  pause
  exit /b 1
)
echo.
echo [成功] 固件已烧录并跳转运行（BOOT0 松开无需再动）
if "%~1"=="" pause
exit /b 0
