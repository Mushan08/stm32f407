# -*- coding: utf-8 -*-
"""把 _tools/f407tool.py 打成工程根目录的 f407.exe（PyInstaller onefile, console）。

用法（任意目录）:
    python _tools/build_exe.py            # 重新打包
    python _tools/build_exe.py --check    # 只检查 pyinstaller 是否可用

产物: <工程根>\f407.exe   （约 8~12 MB，自带 Python 运行时 + pyserial）
中间文件都关在 build/_pyi/ 下，不污染工程根。
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY = os.path.join(ROOT, "_tools", "f407tool.py")
NAME = "f407"
VERSION = "1.1.0.0"

VERSION_FILE = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(%(v1)d, %(v2)d, 0, 0),
    prodvers=(%(v1)d, %(v2)d, 0, 0),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404b0', [
        StringStruct('CompanyName', 'ColdBrew'),
        StringStruct('FileDescription', 'F407 single-file toolbox'),
        StringStruct('FileVersion', '%(ver)s'),
        StringStruct('InternalName', 'f407'),
        StringStruct('OriginalFilename', 'f407.exe'),
        StringStruct('ProductName', 'F407 Toolbox'),
        StringStruct('ProductVersion', '%(ver)s')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""


def main():
    ap = argparse.ArgumentParser(description="打包 f407.exe")
    ap.add_argument("--check", action="store_true", help="只检查 PyInstaller")
    ap.add_argument("--dist", default=ROOT, help="输出目录（默认工程根）")
    args = ap.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[失败] 没装 PyInstaller: python -m pip install pyinstaller")
        return 1
    if args.check:
        print("[OK] PyInstaller %s" % getattr(PyInstaller, "__version__", "?"))
        print("入口: %s" % ENTRY)
        return 0

    for path in (ENTRY, os.path.join(ROOT, "_tools", "probe.py"),
                 os.path.join(ROOT, "_tools", "fault.py"),
                 os.path.join(ROOT, "_tools", "flasher.py")):
        if not os.path.isfile(path):
            print("[失败] 缺文件: %s" % path)
            return 1

    work = os.path.join(ROOT, "build", "_pyi")
    os.makedirs(work, exist_ok=True)
    v1, v2 = (int(x) for x in VERSION.split(".")[:2])
    version_file = os.path.join(work, "version.txt")
    with open(version_file, "w", encoding="ascii") as f:
        f.write(VERSION_FILE % {"v1": v1, "v2": v2, "ver": VERSION})

    argv = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--console",
        "--name", NAME,
        "--distpath", args.dist,
        "--workpath", os.path.join(work, "work"),
        "--specpath", work,
        "--hidden-import", "probe",
        "--hidden-import", "fault",
        "--hidden-import", "flasher",
        "--hidden-import", "serial.tools.miniterm",
        "--collect-submodules", "serial",
        "--version-file", version_file,
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc",
        ENTRY,
    ]
    print("[打包] " + " ".join(argv))
    code = subprocess.call(argv, cwd=ROOT)
    if code != 0:
        print("[失败] PyInstaller 退出码 %d" % code)
        return code
    exe = os.path.join(args.dist, NAME + ".exe")
    print()
    print("[成功] %s  %.1f MB" % (exe, os.path.getsize(exe) / 1048576.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
