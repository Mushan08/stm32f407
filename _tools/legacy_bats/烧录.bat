@echo off
chcp 936 >nul
cd /d "%~dp0..\.."
echo ======== 1/2 编译 ========
call "%~dp0构建.bat" nopause
if errorlevel 1 (
  echo [失败] 编译未通过，不烧录
  pause
  exit /b 1
)
echo.
echo ======== 2/2 烧录 ST-Link ========
"E:\zwork\dev-toolkit\tools\openocd\xpack-openocd-0.12.0-7\bin\openocd.exe" -f openocd\f407vet6.cfg -c "adapter speed 300" -c "reset_config none" -c "program build/f407.elf verify reset exit"
if errorlevel 1 (
  echo [失败] 烧录出错，检查: ST-Link 是否插好 / SWD 四根线 / 板子供电 / 有无其他程序占用
  pause
  exit /b 1
)
echo.
echo [成功] 固件已烧录并复位运行
if "%~1"=="" pause
exit /b 0
