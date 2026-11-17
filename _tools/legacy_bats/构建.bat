@echo off
chcp 936 >nul
cd /d "%~dp0..\.."
if not exist build\CMakeCache.txt (
  echo [首次] 配置工程...
  "E:\zwork\dev-toolkit\tools\cmake\bin\cmake.exe" -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug -DCMAKE_MAKE_PROGRAM=E:\zwork\dev-toolkit\tools\ninja\ninja.exe
  if errorlevel 1 (
    echo [失败] 配置出错
    pause
    exit /b 1
  )
)
"E:\zwork\dev-toolkit\tools\cmake\bin\cmake.exe" --build build
if errorlevel 1 (
  echo [失败] 编译出错，看上方报错
  pause
  exit /b 1
)
echo.
echo [成功] 产物: build\f407.elf  build\f407.hex  build\f407.bin
if "%~1"=="" pause
exit /b 0
