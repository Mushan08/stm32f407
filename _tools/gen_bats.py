# -*- coding: utf-8 -*-
"""生成旧入口 .bat 薄壳：一律转调工程根的 f407.exe，不再写任何绝对路径。

输出目录 _tools/legacy_bats/（GBK + CRLF）；工程根只保留 f407.exe 一个入口。
改脚本后重跑：python _tools/gen_bats.py
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "_tools", "legacy_bats")

# 文件名 -> f407.exe 子命令
BATS = {
    "主菜单.bat": "menu",
    "构建.bat": "build",
    "烧录.bat": "flash",
    "烧录并监视.bat": "flashmon",
    "typec烧录.bat": "typec",
    "板况检查.bat": "probe",
    "故障定位.bat": "fault",
    "GDB调试服务.bat": "gdb",
    "串口监视.bat": "monitor",
    "查看串口.bat": "ports",
    "打开工程.bat": "open",
    "清理构建.bat": "clean -y",
}

TEMPLATE = """@echo off
chcp 936 >nul
set "ROOT=%~dp0..\\.."
cd /d "%ROOT%"
if not exist "%ROOT%\\f407.exe" (
  echo [失败] 找不到 f407.exe，先生成：python _tools\\build_exe.py
  pause
  exit /b 1
)
"%ROOT%\\f407.exe" {cmd} %*
if errorlevel 1 pause
exit /b %errorlevel%
"""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, cmd in BATS.items():
        path = os.path.join(OUT_DIR, name)
        with open(path, "w", encoding="gbk", newline="\r\n") as f:
            f.write(TEMPLATE.format(cmd=cmd))
        print("written", path)


if __name__ == "__main__":
    main()
