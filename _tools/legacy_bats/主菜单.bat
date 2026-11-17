@echo off
cd /d "%~dp0..\.."
chcp 936 >nul
title F407 工具箱
:menu
cls
echo  ==========================================
echo    F407-HAL 工具箱    罗彬_F407 VET6
echo  ==========================================
echo    1. 编译
echo    2. 编译并烧录 (ST-Link)
echo    3. 编译+烧录+串口监视 一条龙
echo    4. Type-C 串口烧录 (无 ST-Link)
echo    5. 板况检查 (固件活着? 不动核)
echo    6. 故障定位 (HardFault 取证)
echo    7. GDB 调试服务
echo    8. 串口监视 115200
echo    9. 查看串口 (找 COM 号)
echo    0. 用 CLion 打开工程
echo    A. 清理构建产物
echo    Q. 退出
echo  ==========================================
choice /c 1234567890AQ /n /m "  选择: "
if errorlevel 12 exit /b 0
if errorlevel 11 call "%~dp0清理构建.bat" & goto menu
if errorlevel 10 call "%~dp0打开工程.bat" & goto menu
if errorlevel 9 call "%~dp0查看串口.bat" & goto menu
if errorlevel 8 call "%~dp0串口监视.bat" & goto menu
if errorlevel 7 call "%~dp0GDB调试服务.bat" & goto menu
if errorlevel 6 call "%~dp0故障定位.bat" & goto menu
if errorlevel 5 call "%~dp0板况检查.bat" & goto menu
if errorlevel 4 call "%~dp0typec烧录.bat" & goto menu
if errorlevel 3 call "%~dp0烧录并监视.bat" & goto menu
if errorlevel 2 call "%~dp0烧录.bat" & goto menu
if errorlevel 1 call "%~dp0构建.bat" & goto menu
