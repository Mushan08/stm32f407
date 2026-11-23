@echo off
chcp 936 >nul
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
if not exist "%ROOT%\f407.exe" (
  echo [失败] 找不到 f407.exe，先生成：python _tools\build_exe.py
  pause
  exit /b 1
)
"%ROOT%\f407.exe" monitor %*
if errorlevel 1 pause
exit /b %errorlevel%
