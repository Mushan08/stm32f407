@echo off
chcp 936 >nul
cd /d "%~dp0..\.."
title F407 GDB Server
echo [GDB Server] gdb 端口 3333 / telnet 端口 4444，窗口保持运行，Ctrl+C 停止
echo.
echo 手动调试命令:
echo   "E:\zwork\dev-toolkit\tools\arm-none-eabi-gcc\xpack-arm-none-eabi-gcc-14.2.1-1.1\bin\arm-none-eabi-gdb.exe" build\f407.elf -x 调试.gdb -ex "target remote localhost:3333" -ex "monitor reset halt" -ex "b main" -ex "c"
echo   （调试.gdb 内置 faultinfo：读 HardFault 现场+addr2line）
echo.
"E:\zwork\dev-toolkit\tools\openocd\xpack-openocd-0.12.0-7\bin\openocd.exe" -f openocd\f407vet6.cfg -c "adapter speed 300" -c "reset_config none"
pause
