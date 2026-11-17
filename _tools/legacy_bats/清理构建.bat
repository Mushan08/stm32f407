@echo off
chcp 936 >nul
cd /d "%~dp0..\.."
if exist build rmdir /s /q build
if exist build-release rmdir /s /q build-release
echo [完成] 已删除 build 与 build-release
pause
