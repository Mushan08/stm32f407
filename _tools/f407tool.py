# -*- coding: utf-8 -*-
"""f407.exe —— 罗彬_F407 单文件工具箱。

把原来散落的 12 个 .bat + _tools 下的脚本收进一个入口：既可以直接双击出菜单，
也可以当命令行用（适合 CLion External Tools / CI / 脚本串联）。

  f407.exe                       # 菜单（等同原「主菜单.bat」）
  f407.exe build                 # 构建（首次自动 configure）
  f407.exe build --relink        # 换过 .ld / HAL 后强制重链
  f407.exe flash                 # 构建 + ST-Link 烧录（300kHz + reset_config none 已固化）
  f407.exe flash --no-build      # 只烧 build/f407.elf
  f407.exe monitor               # 串口监视（自动找 CH340，Ctrl+] 退出）
  f407.exe probe                 # 板况检查（免 halt 采样 uwTick + GPIOE）
  f407.exe fault                 # HardFault 现场取证 + addr2line
  f407.exe gdb                   # 起 OpenOCD（gdb 3333 / telnet 4444，前台常驻）
  f407.exe gdb --client          # 起服务并自动拉起 arm-none-eabi-gdb
  f407.exe typec                 # Type-C 串口/DFU 烧录（无需 ST-Link，自动选通道）
  f407.exe ports                 # 列串口
  f407.exe open                  # 用 CLion 打开本工程
  f407.exe clean                 # 删除 build/ build-release/
  f407.exe doctor                # 环境自检（工具链/固件/cfg/pyserial）
  f407.exe tidy --apply          # 把冗余 .bat 归档进 _tools/legacy_bats（可逆）

工程根定位顺序：--root / 环境变量 F407_ROOT / exe 所在目录向上找 / 当前目录向上找。
所有工具链都用绝对路径，不依赖 PATH。只依赖标准库 + pyserial（打包时已收进 exe）。
"""
import argparse
import csv
import glob
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections import deque

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)
import toolpaths  # noqa: E402

VERSION = "1.2"

TOOLCHAIN = {
    "cmake": toolpaths.cmake(),
    "ninja": toolpaths.ninja(),
    "openocd": toolpaths.openocd(),
    "gdb": toolpaths.gdb(),
    "nm": toolpaths.nm(),
    "addr2line": toolpaths.addr2line(),
    "size": toolpaths.size(),
}

ROOT_MARKERS = ("CMakeLists.txt", os.path.join("openocd", "f407vet6.cfg"))

# 铁律固化：300kHz + reset_config none（HANDOFF §1，cfg 已写死，这里再显式一遍防退化）
SWD_ARGS = ["-c", "adapter speed 300", "-c", "reset_config none"]

LEGACY_BATS = [
    "主菜单.bat", "构建.bat", "烧录.bat", "烧录并监视.bat", "typec烧录.bat",
    "板况检查.bat", "故障定位.bat", "GDB调试服务.bat", "串口监视.bat",
    "查看串口.bat", "打开工程.bat", "清理构建.bat",
]

_ROOT_CACHE = None


# ---------------------------------------------------------------- 基础设施
def setup_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ---------------------------------------------------------------- 终端配色
GREEN, RED, YELLOW, CYAN, DIM = "32", "31", "33", "36", "90"
_COLOR = False

_TAG_COLORS = {
    "成功": GREEN, "正常": GREEN, "OK": GREEN, "完成": GREEN, "已清": GREEN,
    "失败": RED, "冻结": RED, "异常": RED, "HardFault": RED, "中断": YELLOW,
    "警告": YELLOW, "提示": CYAN, "采样": CYAN, "取证": CYAN, "等待": CYAN,
    "配置": CYAN, "编译": CYAN, "烧录": CYAN, "通道": CYAN, "整理": CYAN,
    "清理": YELLOW, "跳过": YELLOW, "结论": CYAN, "结束": CYAN,
}


def enable_color(force=None):
    """双击/终端里开 ANSI 色；管道/重定向/NO_COLOR 时自动关。"""
    global _COLOR
    if force is not None:
        _COLOR = force
        return _COLOR
    forced = os.environ.get("F407_COLOR", "").strip().lower() in ("1", "always", "yes", "on")
    # NO_COLOR 是常规退出口；F407_COLOR=1 视为显式覆盖（有些环境会全局塞 NO_COLOR=1）
    if not forced and (os.environ.get("NO_COLOR") or not sys.stdout.isatty()):
        return False
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            pass
    _COLOR = True
    return True


def c(text, code=None, bold=False):
    if not _COLOR or not code:
        return text
    return ("\x1b[1m" if bold else "") + "\x1b[%sm%s\x1b[0m" % (code, text)


def _paint_line(line):
    if not _COLOR or not line.startswith("["):
        return line
    end = line.find("]")
    if end <= 0:
        return line
    code = _TAG_COLORS.get(line[1:end])
    if not code:
        return line
    return c(line[:end + 1], code, bold=True) + line[end + 1:]


class _ColorStream:
    """按行给 [成功]/[失败] 这类标签上色；保留原 stream 的其它接口（isatty/reconfigure）。"""

    def __init__(self, stream):
        self._s = stream
        self._pending = ""

    def write(self, data):
        if not isinstance(data, str):
            data = str(data)
        text = self._pending + data
        lines = text.split("\n")
        self._pending = lines.pop()
        for ln in lines:
            self._s.write(_paint_line(ln) + "\n")
        return len(data)

    def flush(self):
        if self._pending:
            self._s.write(_paint_line(self._pending))
            self._pending = ""
        self._s.flush()

    def __getattr__(self, name):
        return getattr(self._s, name)


def install_color():
    if enable_color():
        sys.stdout = _ColorStream(sys.stdout)
        sys.stderr = _ColorStream(sys.stderr)
    return _COLOR


def bar(pct, width=26):
    fill = int(round(max(0.0, min(100.0, pct)) / 100.0 * width))
    code = GREEN if pct < 70 else (YELLOW if pct < 90 else RED)
    return c("#" * fill, code) + c("-" * (width - fill), DIM)


def set_console_title(title):
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(title)
    except Exception:
        pass


# ---------------------------------------------------------------- ST-Link 占用
def _tasklist(image):
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq %s" % image, "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10)
    except Exception:
        return []
    rows = []
    for row in csv.reader(r.stdout.splitlines()):
        if len(row) >= 2 and row[0].strip().lower() == image.lower():
            try:
                rows.append((int(row[1]), row[0].strip()))
            except ValueError:
                pass
    return rows


def _parent_pid(pid):
    """取父进程 PID（PyInstaller onefile 是 父bootloader -> 子app，必须认出来）。"""
    if os.name != "nt":
        return 0
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if snap in (-1, 0xFFFFFFFF):
            return 0
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(entry)
        parent = 0
        if kernel32.Process32First(snap, ctypes.byref(entry)):
            while True:
                if entry.th32ProcessID == pid:
                    parent = entry.th32ParentProcessID
                    break
                if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                    break
        kernel32.CloseHandle(snap)
        return parent
    except Exception:
        return 0


def _self_chain(depth=4):
    """自己 + 父链。onefile 时父进程也叫 f407.exe，不能把它当"残留"杀掉。"""
    pids = set()
    pid = os.getpid()
    for _ in range(depth):
        if not pid or pid in pids:
            break
        pids.add(pid)
        pid = _parent_pid(pid)
    return pids


def stlink_holders():
    skip = _self_chain()
    return [x for x in (_tasklist("openocd.exe") + _tasklist("f407.exe")) if x[0] not in skip]


def warn_holders(what="接下来的 SWD 操作"):
    procs = stlink_holders()
    if procs:
        detail = ", ".join("%s(PID %d)" % (name, pid) for pid, name in procs)
        print("[提示] %s 正在运行，%s 可能连不上 ST-Link；先 f407.exe kill-stlink" % (detail, what))
    return procs


def cmd_kill_stlink(args):
    procs = stlink_holders()
    if not procs:
        print("[完成] 没有残留的 openocd / f407 进程，ST-Link 是空闲的")
        return 0
    print("[提示] 找到可能占用 ST-Link 的进程:")
    for pid, name in procs:
        print("  %-12s PID %d" % (name, pid))
    if not args.yes:
        ans = input("结束这些进程？[y/N] ").strip().lower()
        if ans != "y":
            print("[跳过] 未做改动")
            return 1
    for pid, name in procs:
        # /T 连子进程一起收：单杀 onefile 外壳会留下 openocd 继续占 ST-Link
        subprocess.call(["taskkill", "/PID", str(pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("[完成] 已结束 %d 个进程，ST-Link 已释放" % len(procs))
    return 0


def find_stlink_instance():
    """找 ST-Link 的 PnP 实例 ID（VID_0483&PID_3748）。"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match "
             "'VID_0483&PID_3748' } | Select-Object -First 1 -ExpandProperty InstanceId"],
            capture_output=True, text=True, timeout=25)
    except Exception:
        return None
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.upper().startswith("USB\\"):
            return line
    return None


def cmd_usbreset(args):
    """软重启 ST-Link（openocd 被强杀后常枚举成 API v0 / 连不上）。没有管理员权限时给拔插指引。"""
    inst = find_stlink_instance()
    if not inst:
        print("[失败] 没找到 ST-Link（VID_0483&PID_3748）。USB 线没插？")
        return 1
    print("[提示] ST-Link: %s" % inst)
    try:
        r = subprocess.run(["pnputil", "/restart-device", inst],
                           capture_output=True, text=True, timeout=30)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as exc:
        out = "pnputil 调用失败: %s" % exc
    if out:
        print(out)
    low = out.lower()
    if "denied" not in low and "拒绝" not in out and "失败" not in out:
        print("[完成] ST-Link 已重启，等 2 秒再跑 f407.exe probe")
        return 0
    print()
    print("[警告] 软重启需要管理员权限。二选一：")
    print("  1) 直接拔插 ST-Link 的 USB（最快，效果一样）")
    print("  2) 管理员 PowerShell 执行:")
    print('     pnputil /restart-device "%s"' % inst)
    return 1


def project_root(explicit=None):
    global _ROOT_CACHE
    if explicit:
        return os.path.abspath(explicit)
    if _ROOT_CACHE:
        return _ROOT_CACHE
    env = os.environ.get("F407_ROOT")
    if env and os.path.isdir(env):
        _ROOT_CACHE = os.path.abspath(env)
        return _ROOT_CACHE

    starts = []
    if getattr(sys, "frozen", False):
        starts.append(os.path.dirname(os.path.abspath(sys.executable)))
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        starts += [here, os.path.dirname(here)]
    starts.append(os.getcwd())

    for start in starts:
        cur = os.path.abspath(start)
        for _ in range(8):
            if all(os.path.exists(os.path.join(cur, m)) for m in ROOT_MARKERS):
                _ROOT_CACHE = cur
                return cur
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    _ROOT_CACHE = os.path.abspath(starts[0])
    return _ROOT_CACHE


def missing_tools(names):
    return [n for n in names if not os.path.isfile(TOOLCHAIN[n])]


def require_tools(names):
    miss = missing_tools(names)
    if miss:
        print("[失败] 工具链缺件（dev-toolkit 被移动/删除？）:")
        for n in miss:
            print("  %-10s %s" % (n, TOOLCHAIN[n]))
        print("  修正 _tools/f407tool.py 顶部的 TOOLKIT 路径，或跑 f407.exe doctor 看全貌。")
        return False
    return True


def run(argv, cwd=None):
    return subprocess.call(argv, cwd=cwd)


def artifact_report(root):
    build = os.path.join(root, "build")
    for name in ("f407.elf", "f407.hex", "f407.bin", "f407.map"):
        p = os.path.join(build, name)
        if os.path.isfile(p):
            print("  %-10s %8.1f KB  %s" % (name, os.path.getsize(p) / 1024.0, p))


def find_clion():
    cands = glob.glob(r"C:\Program Files\JetBrains\CLion*\bin\clion64.exe")
    cands += glob.glob(r"C:\Users\*\AppData\Local\Programs\CLion*\bin\clion64.exe")
    if not cands:
        return None
    cands.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return cands[0]


def pick_port(prefer_ch340=True):
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    ports = list(list_ports.comports())
    if not ports:
        return None
    if prefer_ch340:
        for p in ports:
            if "CH34" in (p.description or "").upper():
                return p.device
    return None


def print_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        print("[失败] 缺 pyserial")
        return []
    ports = list(list_ports.comports())
    if not ports:
        print("  (没有检测到任何串口设备)")
        print("  CH340 的 USB 在 H1 排针（1=GND 2=D- 3=D+），与 Type-C 无关；只插 Type-C 不会有 COM 口。")
        return []
    print("  %-8s %-10s %s" % ("端口", "描述", "备注"))
    for p in ports:
        tag = "CH340*" if "CH34" in (p.description or "").upper() else ""
        print("  %-8s %-40s %s" % (p.device, p.description, tag))
    return ports


def load_tool(name):
    """源码运行时从 _tools 导入；exe 运行时用打包进来的模块。"""
    root = project_root()
    tools_dir = os.path.join(root, "_tools")
    if os.path.isdir(tools_dir) and tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    os.environ["F407_ROOT"] = root  # probe.py 用它定位 elf/cfg
    if name == "probe":
        import probe
        return probe
    if name == "fault":
        import fault
        return fault
    if name == "flasher":
        import flasher
        return flasher
    raise ImportError(name)


# ---------------------------------------------------------------- 构建 / 烧录
def cmd_build(args):
    root = project_root(args.root)
    if not require_tools(["cmake", "ninja"]):
        return 1
    build_dir = os.path.join(root, "build")
    elf = os.path.join(build_dir, "f407.elf")

    if getattr(args, "clean", False) and os.path.isdir(build_dir):
        print("[清理] 删除 %s" % build_dir)
        shutil.rmtree(build_dir, ignore_errors=True)
    if getattr(args, "relink", False) and os.path.isfile(elf):
        print("[重链] 删除旧 elf（ninja 不追踪 .ld 改动）")
        os.remove(elf)

    cache = os.path.join(build_dir, "CMakeCache.txt")
    if not os.path.isfile(cache):
        print("[配置] cmake -S . -B build -G Ninja (Debug)")
        code = run([
            TOOLCHAIN["cmake"], "-S", root, "-B", build_dir, "-G", "Ninja",
            "-DCMAKE_BUILD_TYPE=Debug",
            "-DCMAKE_MAKE_PROGRAM=" + TOOLCHAIN["ninja"],
        ], cwd=root)
        if code != 0:
            print("[失败] 配置出错（退出码 %d）" % code)
            return code
    print("[编译] cmake --build build")
    code = run([TOOLCHAIN["cmake"], "--build", build_dir], cwd=root)
    if code != 0:
        print("[失败] 编译出错（退出码 %d），看上方报错" % code)
        return code
    print("[成功] 产物:")
    artifact_report(root)
    return 0


def cmd_flash(args):
    root = project_root(args.root)
    warn_holders("烧录")
    if not args.no_build:
        code = cmd_build(argparse.Namespace(root=args.root, clean=False, relink=args.relink))
        if code != 0:
            print("[失败] 编译未通过，不烧录")
            return code
    if not require_tools(["openocd"]):
        return 1
    elf = os.path.join(root, "build", "f407.elf")
    if not os.path.isfile(elf):
        print("[失败] 没有 %s，先跑 f407.exe build" % elf)
        return 1
    cfg = os.path.join(root, "openocd", "f407vet6.cfg")
    argv = [TOOLCHAIN["openocd"], "-f", cfg] + SWD_ARGS + [
        "-c", 'program "%s" verify reset exit' % elf.replace("\\", "/")
    ]
    print("[烧录] ST-Link / SWD @300kHz ...")
    code = run(argv, cwd=root)
    if code != 0:
        print()
        print("[失败] 烧录出错（退出码 %d）。按顺序查:" % code)
        print("  1. ST-Link 插好了吗？有别的 gdb/openocd 会话占着吗？（f407.exe gdb 先关）")
        print("  2. Type-C 拔了吗？调试时 ST-Link 3.3V 必须是唯一电源（双电源共轨会弄死 SWD）")
        print("  3. SWDIO=PA13 / SWCLK=PA14 / GND / 3V3，先查 GND；线松 = 间歇性怪象第一嫌疑")
        print("  4. 速度已是 300kHz，连不上是线/供电问题，不是速度问题")
        return code
    print("[成功] 固件已烧录并复位运行。")
    return 0


def cmd_monitor(args):
    project_root(args.root)
    port = args.port
    if not port and getattr(args, "wait", False):
        print("[等待] 插入 CH340（H1 排针 1=GND 2=D- 3=D+）后自动进入；Ctrl+C 取消 ...")
        try:
            while not port:
                port = pick_port()
                if port:
                    break
                time.sleep(2)
        except KeyboardInterrupt:
            print()
            return 130
    if not port:
        port = pick_port()
    if not port:
        print("可用串口:")
        ports = print_ports()
        if not ports:
            print()
            print("没有 CH340：printf 的物理出口是 H1 排针（1=GND 2=D- 3=D+），与 Type-C 无关。")
            print("不接 H1 时固件照常跑，只是没人能听见打印。")
            return 1
        if not sys.stdin.isatty():
            port = ports[0].device
            print("[提示] 非交互环境，默认用 %s" % port)
        else:
            raw = input("串口名（如 COM5，回车=第一个）: ").strip() or ports[0].device
            port = raw
    baud = args.baud
    print("[监视] %s @%d 8N1，退出按 Ctrl+]" % (port, baud))
    try:
        from serial.tools import miniterm
    except ImportError:
        print("[失败] 缺 pyserial（源码运行: pip install pyserial）")
        return 1
    old_argv = sys.argv
    sys.argv = ["f407-miniterm", port, str(baud)]
    try:
        miniterm.main(default_port=port, default_baudrate=baud)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        sys.argv = old_argv


def cmd_typec(args):
    root = project_root(args.root)
    if not args.no_build:
        code = cmd_build(argparse.Namespace(root=args.root, clean=False, relink=False))
        if code != 0:
            print("[失败] 编译未通过，不烧录")
            return code
    flasher = load_tool("flasher")
    firmware = args.file or os.path.join(root, "build", "f407.hex")
    if not os.path.isfile(firmware):
        print("[失败] 没有固件 %s" % firmware)
        return 1

    print("进入 bootloader（Type-C 通道，不需要 ST-Link）:")
    print("  1. 按住 SW1(BOOT0)")
    print("  2. 点一下 SW2(NRST) 复位")
    print("  3. 松开 SW1 -> 板子停在出厂 bootloader，再开始烧录")
    print()

    kind, dev = args.channel, args.port or ""
    if not kind:
        chans = flasher.discover_all()
        if not chans:
            print("[失败] 没有可用通道（UART/DFU 都没探测到）")
            print("  检查: Type-C 插了吗 / CH340 串口在设备管理器里有吗 / 是否已按上面三步进 bootloader")
            return 1
        kind, dev, desc = chans[0]
        print("[通道] 自动选择 %s %s (%s)" % (kind, dev, desc))
    return flasher.run(kind, dev, firmware)


def cmd_gdb(args):
    root = project_root(args.root)
    warn_holders("gdb 服务")
    if not require_tools(["openocd"]):
        return 1
    cfg = os.path.join(root, "openocd", "f407vet6.cfg")
    argv = [TOOLCHAIN["openocd"], "-f", cfg] + SWD_ARGS
    print("[GDB Server] gdb=localhost:%d  telnet=localhost:%d   (Ctrl+C 停止)" % (args.port, args.telnet))

    if not args.client:
        print()
        print("另开终端连进来:")
        print('  "%s" "%s" -ex "target remote localhost:%d" -ex "monitor reset halt" -ex "break main" -ex "c"'
              % (TOOLCHAIN["gdb"], os.path.join(root, "build", "f407.elf"), args.port))
        print("  或直接: f407.exe gdb --client（本工具自动拉起 gdb 客户端）")
        print()
        try:
            return run(argv, cwd=root)
        except KeyboardInterrupt:
            print()
            print("[停止] GDB Server 已关闭")
            return 0

    if not require_tools(["gdb"]):
        return 1
    elf = os.path.join(root, "build", "f407.elf")
    if not os.path.isfile(elf):
        print("[失败] 没有 %s，先 f407.exe build" % elf)
        return 1
    server = subprocess.Popen(argv, cwd=root)
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", args.port), timeout=0.4):
                    break
            except OSError:
                if server.poll() is not None:
                    print("[失败] OpenOCD 提前退出（退出码 %s），看上方输出" % server.returncode)
                    return 1
                time.sleep(0.2)
        else:
            print("[警告] 10 秒内没等到 gdb 端口，仍尝试连接")
        gdb_argv = [TOOLCHAIN["gdb"], elf]
        gdb_script = os.path.join(root, "调试.gdb")
        if os.path.isfile(gdb_script):
            gdb_argv += ["-x", gdb_script]
        gdb_argv += [
            "-ex", "target remote localhost:%d" % args.port,
            "-ex", "monitor reset halt",
            "-ex", "break main",
            "-ex", "continue",
        ]
        return run(gdb_argv, cwd=root)
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                server.kill()
            print("[停止] GDB Server 已关闭")


# ---------------------------------------------------------------- 观测 / 取证
GPIOE_IDR_ADDR = "0x40021010"
LED_BITS = ((2, "1"), (3, "2"), (4, "3"), (5, "4"))


def _led_marks(idr):
    parts = []
    for bit, name in LED_BITS:
        if not ((idr >> bit) & 1):
            parts.append(c("●" + name, GREEN, bold=True))
        else:
            parts.append(c("○" + name, DIM))
    return " ".join(parts)


def cmd_watch(args):
    """实时看板：一个 openocd 会话持续 200ms 采样 uwTick+GPIOE，Ctrl+C 出统计。"""
    project_root(args.root)
    warn_holders("实时看板")
    probe = load_tool("probe")
    addr, err = probe.get_uwtick_addr()
    if addr is None:
        print("[警告] %s -> 只显示灯位，不算速率" % err)
    interval = max(50, int(args.interval))
    tcl = ["init", "proc mon {} {", "  for {set i 0} {$i < 500000} {incr i} {"]
    if addr:
        tcl += [
            "    set t [lindex [read_memory 0x%X 32 1] 0]" % addr,
            "    set u [lindex [read_memory %s 32 1] 0]" % GPIOE_IDR_ADDR,
            '    echo "W [format %u $t] [format 0x%08X $u]"',
        ]
    else:
        tcl += [
            "    set u [lindex [read_memory %s 32 1] 0]" % GPIOE_IDR_ADDR,
            '    echo "W none [format 0x%08X $u]"',
        ]
    tcl += ["    sleep %d" % interval, "  }", "}", "mon", "shutdown"]

    fd, path = tempfile.mkstemp(suffix=".tcl", prefix="f407_watch_")
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(tcl) + "\n")
    interactive = sys.stdout.isatty()
    proc = None
    samples = 0
    last_t = last_ts = None
    rates = deque(maxlen=10)
    seq = []
    last_cur = None
    frozen = 0
    alerts = 0
    tail = deque(maxlen=30)
    t0 = time.time()
    print("[采样] 每 %d ms 一拍（Ctrl+C 结束并出统计）" % interval, flush=True)
    try:
        proc = subprocess.Popen(
            [probe.OPENOCD, "-f", probe.CFG, "-c", "script " + path.replace("\\", "/")],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for raw in proc.stdout:
            s = raw.strip()
            if not s:
                continue
            m = re.match(r"W (none|\d+) (0x[0-9A-Fa-f]+)", s)
            if not m:
                tail.append(s)
                continue
            now = time.time()
            tick = None if m.group(1) == "none" else int(m.group(1))
            idr = int(m.group(2), 16)
            samples += 1
            if tick is not None:
                if last_t is not None and tick >= last_t and now > (last_ts or 0):
                    rates.append((tick - last_t) / (now - last_ts))
                frozen = frozen + 1 if (last_t is not None and tick == last_t) else 0
                last_t, last_ts = tick, now
            else:
                frozen = 0
            rate = (sum(rates) / len(rates)) if rates else 0.0
            lit = [n for bit, n in LED_BITS if not ((idr >> bit) & 1)]
            cur = lit[0] if len(lit) == 1 else ("-" if not lit else "?")
            if cur != last_cur:
                seq.append(cur)
                last_cur = cur
            rate_txt = ("%6.0f/s" % rate) if rates else "    -- "
            text = "tick %-9s %s  LED %s  IDR %08X" % (
                ("%d" % tick) if tick is not None else " -- ", rate_txt, _led_marks(idr), idr)
            if interactive:
                sys.stdout.write("\r" + text + "   ")
                sys.stdout.flush()
            else:
                print(text, flush=True)
            if frozen == 3:
                alerts += 1
                if interactive:
                    sys.stdout.write("\n")
                print("[冻结] uwTick 连续 3 拍不变 -> 停表/供电塌陷；停掉后跑 f407.exe probe 复核",
                      flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            os.remove(path)
        except OSError:
            pass

    if interactive:
        print()
    if samples == 0:
        print("[失败] 一个采样都没拿到（退出码 %s）" % (proc.returncode if proc else "?"))
        tail_lines = list(tail)[-6:]
        for ln in tail_lines:
            print("  " + ln)
        if any("API v0" in ln or "init mode failed" in ln for ln in tail):
            print("[提示] ST-Link 枚举异常（API v0 / init failed）：拔插 ST-Link USB，或 f407.exe usbreset")
        print("  前提: ST-Link 四线在 / Type-C 已拔 / 没有 gdb 会话占着")
        return 1
    avg = (sum(rates) / len(rates)) if rates else 0.0
    print("[结束] %d 采样 / %.1f 秒；平均 %.0f 拍/秒；灯序 %s；冻结告警 %d"
          % (samples, time.time() - t0, avg, " -> ".join(seq[-10:]) or "-", alerts))
    return 0


def cmd_size(args):
    root = project_root(args.root)
    if not require_tools(["size"]):
        return 1
    elf = os.path.join(root, "build", "f407.elf")
    if not os.path.isfile(elf):
        print("[失败] 没有 %s，先 f407.exe build" % elf)
        return 1
    r = subprocess.run([TOOLCHAIN["size"], elf], capture_output=True, text=True)
    rows = [ln.split() for ln in r.stdout.splitlines() if ln.strip()]
    if len(rows) < 2 or len(rows[1]) < 3:
        print("[失败] size 输出异常:\n%s" % r.stdout)
        return 1
    try:
        text, data, bss = int(rows[1][0]), int(rows[1][1]), int(rows[1][2])
    except ValueError:
        print("[失败] size 输出无法解析: %s" % rows[1])
        return 1
    flash, ram = text + data, data + bss
    print("---------- 固件容量 ----------")
    for name, used, total in (("FLASH", flash, 512 * 1024), ("RAM", ram, 128 * 1024)):
        pct = used * 100.0 / total
        print("  %-5s %7d B / %7d B  %5.1f%%  %s" % (name, used, total, pct, bar(pct)))
    print("  (data 同时计入 FLASH 初值与 RAM，属正常；CCM 64K 未使用)")
    print()
    artifact_report(root)
    return 0


def cmd_probe(args):
    warn_holders("板况检查")
    probe = load_tool("probe")
    return probe.main()


def cmd_fault(args):
    warn_holders("HardFault 取证")
    fault = load_tool("fault")
    return fault.main()


def cmd_ports(args):
    print_ports()
    return 0


RCC_CR = "0x40023800"    # HSION/HSIRDY(0/1) HSEON/HSERDY(16/17) PLLON/PLLRDY(24/25)
RCC_CFGR = "0x40023808"  # SWS[3:2] PLLSRC(22) PLLM[5:0] PLLN[14:6] PLLP[17:16]
RCC_CSR = "0x40023874"   # bit25 BORRST / bit26 PINRST / bit28 SFTRST


def cmd_clock(args):
    """§4.2 的自动化版：读 RCC_CR/CFGR/CSR 判 HSE 起振、PLL、系统时钟源、复位史（免 halt）。"""
    warn_holders("时钟取证")
    probe = load_tool("probe")
    clear = getattr(args, "clear", False)
    tcl = "\n".join([
        "init",
        "set a [lindex [read_memory %s 32 1] 0]" % RCC_CR,
        "set b [lindex [read_memory %s 32 1] 0]" % RCC_CFGR,
        "set c [lindex [read_memory %s 32 1] 0]" % RCC_CSR,
        'echo "CLK_CR [format 0x%08X $a]"',
        'echo "CLK_CFGR [format 0x%08X $b]"',
        'echo "CLK_CSR [format 0x%08X $c]"',
    ] + ([
        "# 清复位标志：RCC_CSR.RMVF(bit24)=1，写 1 清 0",
        "write_memory %s 32 0x01000000" % RCC_CSR,
        "set d [lindex [read_memory %s 32 1] 0]" % RCC_CSR,
        'echo "CLK_CSR2 [format 0x%08X $d]"',
    ] if clear else []) + [
        "shutdown",
    ]) + "\n"
    code, text = probe.run_probe(tcl)
    vals = {m.group(1): int(m.group(2), 16)
            for m in re.finditer(r"CLK_(\w+) 0x([0-9A-Fa-f]+)", text)}
    if len(vals) < 3:
        print("[失败] 读不到 RCC 寄存器（openocd 连不上/被 gdb 会话占用，退出码 %s）" % code)
        print("  前提: ST-Link 四线在、Type-C 已拔、f407.exe gdb 没开着")
        if "Error" in text:
            print("---- openocd 尾部输出 ----")
            print("\n".join(text.strip().splitlines()[-6:]))
        return 1

    cr, cfgr, csr = vals["CR"], vals["CFGR"], vals["CSR"]
    bit = lambda v, b: (v >> b) & 1  # noqa: E731
    hse_ready = bit(cr, 17)
    pll_ready = bit(cr, 25)
    sws = (cfgr >> 2) & 3
    pll_src = bit(cfgr, 22)
    m, n, p = cfgr & 0x3F, (cfgr >> 6) & 0x1FF, ((cfgr >> 16) & 3) + 1
    src = {0: "HSI", 1: "HSE", 2: "PLL", 3: "?"}[sws]

    print("---------- 时钟 / 复位状态 ----------")
    print("  RCC_CR   = 0x%08X   HSEON=%d HSERDY=%d PLLON=%d PLLRDY=%d"
          % (cr, bit(cr, 16), hse_ready, bit(cr, 24), pll_ready))
    print("  RCC_CFGR = 0x%08X   SWS=%d(%s) PLLSRC=%s PLLM=%d PLLN=%d PLLP=%d"
          % (cfgr, sws, src, "HSE" if pll_src else "HSI", m, n, p))
    print("  RCC_CSR  = 0x%08X" % csr)
    print()

    flags = []
    if csr & (1 << 27):
        flags.append("PORRST=上电复位")
    if csr & (1 << 25):
        flags.append("BORRST=欠压史(杜邦线第一嫌疑)")
    if csr & (1 << 26):
        flags.append("PINRST=引脚复位")
    if csr & (1 << 28):
        flags.append("SFTRST=软件复位")
    if flags:
        print("  复位标志: " + "; ".join(flags))
    else:
        print("  复位标志: 无已知标志（已清或上电复位）")

    if clear:
        csr2 = vals.get("CSR2")
        if csr2 is None:
            print("[警告] 清零命令没回读，可能写保护/连接中断")
        else:
            print()
            print("[已清] 复位标志 RMVF 已置位，回读 RCC_CSR = 0x%08X" % csr2)
            print("       现在开始计时：跑几分钟后再 `f407.exe probe`，")
            print("       若 BORRST 重新出现 = 这段时间真掉过压（查供电/杜邦线）；一直是 0 = 电源稳。")

    print()
    if hse_ready:
        print("[HSE] 已起振（HSERDY=1）——X2 8MHz 正常，可用 PLLSRC=HSE 跑精确 48MHz USB")
    else:
        print("[HSE] 未起振（HSERDY=0）——X2 仍是坏的/没焊好；USB 时钟不合规，别切 PLLSRC=HSE")
        print("      修法见 HANDOFF §6.3：先烙铁润 X2+C3/C4 焊点，再跑一次本命令看 HSERDY")
    if pll_ready:
        print("[PLL] 已锁定（PLLRDY=1），当前系统时钟源 = %s" % src)
    else:
        print("[PLL] 未锁定（PLLRDY=0）——若系统还在跑，说明用的是 HSI 直出")
    return 0


# ---------------------------------------------------------------- 杂项
def cmd_open(args):
    root = project_root(args.root)
    clion = args.path or find_clion()
    if not clion or not os.path.isfile(clion):
        print("[失败] 没找到 CLion。用 --path 指定 clion64.exe，或直接打开目录:")
        print("  %s" % root)
        return 1
    print("[打开] %s" % clion)
    subprocess.Popen([clion, root], cwd=root)
    return 0


def cmd_clean(args):
    root = project_root(args.root)
    targets = [os.path.join(root, d) for d in ("build", "build-release")]
    existing = [p for p in targets if os.path.isdir(p)]
    if not existing:
        print("[清理] 没有 build/ 或 build-release/，无事可做")
        return 0
    for p in existing:
        if not args.yes:
            ans = input("删除 %s ? [y/N] " % p).strip().lower()
            if ans != "y":
                print("[跳过] %s" % p)
                continue
        shutil.rmtree(p, ignore_errors=True)
        print("[清理] 已删除 %s" % p)
    return 0


def cmd_doctor(args):
    root = project_root(args.root)
    print("f407.exe %s   运行形态=%s" % (VERSION, "exe" if getattr(sys, "frozen", False) else "py"))
    print("工程根 : %s" % root)
    ok = True
    print()
    print("工具链:")
    for name in ("cmake", "ninja", "openocd", "gdb", "nm", "addr2line"):
        path = TOOLCHAIN[name]
        good = os.path.isfile(path)
        ok = ok and good
        print("  %-10s %s  %s" % (name, "OK  " if good else "MISS", path))
    print()
    print("工程文件:")
    for rel in ("CMakeLists.txt", os.path.join("openocd", "f407vet6.cfg"),
                os.path.join("build", "f407.elf"), os.path.join("build", "f407.hex")):
        path = os.path.join(root, rel)
        good = os.path.exists(path)
        ok = ok and good
        print("  %-32s %s" % (rel, "OK" if good else "缺"))
    print()
    try:
        import serial
        print("pyserial   OK   %s" % serial.VERSION)
    except ImportError:
        ok = False
        print("pyserial   MISS（源码运行: pip install pyserial）")
    elf = os.path.join(root, "build", "f407.elf")
    if os.path.isfile(elf):
        print("固件时间   %s" % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(elf))))
    try:
        r = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            print("git HEAD   %s" % r.stdout.strip())
    except Exception:
        pass
    holders = stlink_holders()
    print("ST-Link    %s（设备本身是否在线用 f407.exe probe 验）" % ("无进程占用" if not holders else
          "被占用: " + ", ".join("%s(PID %d)" % (n, p) for p, n in holders)))
    clion = find_clion()
    print("CLion      %s" % (clion or "未找到（f407.exe open 会失败，可 --path 指定）"))
    print()
    print("[结论] " + ("一切就绪" if ok else "有缺件，按上面 MISS/缺 处理"))
    return 0 if ok else 1


def cmd_tidy(args):
    root = project_root(args.root)
    dst = os.path.join(root, "_tools", "legacy_bats")
    moves = [n for n in LEGACY_BATS if os.path.isfile(os.path.join(root, n))]
    if not moves:
        print("[整理] 根目录已经没有可归档的 .bat（已整理过？）")
        return 0
    print("[整理] 目标目录: %s" % dst)
    for n in moves:
        print("  %s" % n)
    if not args.apply:
        print()
        print("这是预演。确认无误后加 --apply 执行（可逆：文件只是移动）。")
        return 0
    os.makedirs(dst, exist_ok=True)
    for n in moves:
        src = os.path.join(root, n)
        raw = open(src, "rb").read()
        text = raw.decode("gbk", "replace")
        # 移动后相对路径深两层，把 cd 目标改回工程根，旧 bat 仍可直接双击用
        text = text.replace('cd /d "%~dp0"', 'cd /d "%~dp0..\\.."')
        text = text.replace('"%~dp0."', '"%~dp0..\\.."')
        for other in LEGACY_BATS:
            text = text.replace("call " + other, 'call "%%~dp0%s"' % other)
        if 'cd /d "%~dp0..\\.."' not in text:
            text = text.replace("@echo off\r\n", "@echo off\r\ncd /d \"%~dp0..\\..\"\r\n", 1)
        out = os.path.join(dst, n)
        with open(out, "wb") as f:
            f.write("\r\n".join(text.replace("\r\n", "\n").split("\n")).encode("gbk", "replace"))
        os.remove(src)
        print("  移动 %s -> %s" % (n, out))
    print()
    print("[完成] 根目录只留 f407.exe 一个入口；旧 bat 在 _tools/legacy_bats/（仍可双击）。")
    print("       gen_bats.py 已同步改为生成到该目录，重跑不会再往根目录堆文件。")
    return 0


# ---------------------------------------------------------------- 菜单
def _ns(**kw):
    base = dict(root=None, clean=False, relink=False, no_build=False, port=None,
                baud=115200, file=None, channel=None, client=False, path=None,
                yes=False, apply=False, telnet=4444, clear=False,
                interval=200, wait=False)
    base.update(kw)
    return argparse.Namespace(**base)


def cmd_flashmon(args):
    """编译 + 烧录 + 串口监视（原「烧录并监视.bat」）。"""
    code = cmd_flash(args)
    if code != 0:
        return code
    print()
    print("======== 串口监视 ========")
    print("printf 出口 = H1 排针的 CH340N；没接 H1 时固件照常跑，只是打印没人听。")
    return cmd_monitor(args)


MENU = [
    ("1", "构建", lambda: cmd_build(_ns())),
    ("2", "编译 + 烧录 (ST-Link)", lambda: cmd_flash(_ns())),
    ("3", "构建 + 烧录 + 串口监视  一条龙", lambda: cmd_flashmon(_ns())),
    ("4", "Type-C 串口烧录 (无 ST-Link)", lambda: cmd_typec(_ns())),
    ("5", "板况检查 (免 halt 采样)", lambda: cmd_probe(_ns())),
    ("C", "时钟/复位状态 (HSE? PLL? 欠压史?)", lambda: cmd_clock(_ns())),
    ("W", "实时看板 (tick/LED 连续刷新)", lambda: cmd_watch(_ns())),
    ("6", "故障定位 (HardFault 取证)", lambda: cmd_fault(_ns())),
    ("7", "GDB 调试服务 (3333/4444)", lambda: cmd_gdb(_ns())),
    ("8", "串口监视 115200", lambda: cmd_monitor(_ns())),
    ("9", "查看串口 (列 COM)", lambda: cmd_ports(_ns())),
    ("S", "固件容量 (FLASH/RAM 百分比)", lambda: cmd_size(_ns())),
    ("0", "用 CLion 打开工程", lambda: cmd_open(_ns())),
    ("A", "清理构建 (build/ build-release/)", lambda: cmd_clean(_ns(yes=True))),
    ("K", "释放 ST-Link (清残留 openocd)", lambda: cmd_kill_stlink(_ns())),
    ("U", "重置 ST-Link (USB 软复位 / 拔插提示)", lambda: cmd_usbreset(_ns())),
    ("D", "环境自检 (工具链/固件/串口)", lambda: cmd_doctor(_ns())),
    ("Q", "退出", None),
]


def cmd_menu(args):
    last_key = last_label = None
    while True:
        os.system("cls")
        print(" " + c("=" * 46, DIM))
        print("   " + c("F407 工具箱", CYAN, bold=True) + "   罗彬_F407 VET6")
        print("   f407.exe %s   根: %s" % (VERSION, project_root(args.root)))
        print(" " + c("=" * 46, DIM))
        for key, label, _ in MENU:
            print("   %s. %s" % (c(key, YELLOW, bold=True), label))
        print("   %s. 重跑上次%s" % (c("R", YELLOW, bold=True),
                                     c("  (%s)" % last_label, DIM) if last_label else ""))
        print(" " + c("=" * 46, DIM))
        try:
            choice = input("   " + c("选择", CYAN) + ": ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice in ("Q", ""):
            return 0
        if choice == "R":
            if last_key is None:
                continue
            choice = last_key
        action = None
        for key, label, fn in MENU:
            if choice == key:
                action, last_key, last_label = fn, key, label
                break
        if action is None:
            continue
        print()
        try:
            action()
        except KeyboardInterrupt:
            print("\n[中断]")
        except Exception as exc:  # 菜单里不炸飞整个窗口
            print("[异常] %s: %s" % (type(exc).__name__, exc))
        print()
        try:
            input("回车返回菜单...")
        except (EOFError, KeyboardInterrupt):
            return 0


# ---------------------------------------------------------------- 入口
def build_parser():
    ap = argparse.ArgumentParser(
        prog="f407",
        description="罗彬_F407 单文件工具箱（构建/烧录/串口/板况/HardFault/GDB/Type-C）",
        epilog="不带参数直接双击 = 菜单。",
    )
    ap.add_argument("-r", "--root", help="工程根目录（默认自动向上查找 CMakeLists.txt + openocd/f407vet6.cfg）")
    ap.add_argument("-V", "--version", action="version", version="f407.exe " + VERSION)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("build", aliases=["b"], help="构建")
    p.add_argument("--clean", action="store_true", help="先删 build/ 再配置")
    p.add_argument("--relink", action="store_true", help="删旧 elf 强制重链（换过 .ld/HAL）")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("flash", aliases=["f"], help="构建 + ST-Link 烧录")
    p.add_argument("--no-build", action="store_true", help="跳过构建，直接烧 build/f407.elf")
    p.add_argument("--relink", action="store_true", help="构建前删旧 elf")
    p.set_defaults(func=cmd_flash)

    p = sub.add_parser("flashmon", aliases=["fm"], help="构建 + 烧录 + 串口监视")
    p.add_argument("--no-build", action="store_true", help="跳过构建，直接烧 build/f407.elf")
    p.add_argument("--relink", action="store_true", help="构建前删旧 elf")
    p.add_argument("--port", help="串口名（默认自动找 CH340）")
    p.add_argument("-b", "--baud", type=int, default=115200)
    p.set_defaults(func=cmd_flashmon)

    p = sub.add_parser("monitor", aliases=["mon", "serial"], help="串口监视")
    p.add_argument("port", nargs="?", help="串口名，如 COM5（默认自动找 CH340）")
    p.add_argument("-b", "--baud", type=int, default=115200)
    p.add_argument("--wait", action="store_true", help="没有串口时每 2 秒重试，插上自动进入")
    p.set_defaults(func=cmd_monitor)

    p = sub.add_parser("typec", aliases=["isp"], help="Type-C 串口/DFU 烧录（无需 ST-Link）")
    p.add_argument("-c", "--channel", choices=["uart", "dfu"], help="强制通道")
    p.add_argument("-p", "--port", help="串口号（uart 通道）")
    p.add_argument("-f", "--file", help="固件 .hex（默认 build/f407.hex）")
    p.add_argument("--no-build", action="store_true", help="跳过构建")
    p.set_defaults(func=cmd_typec)

    p = sub.add_parser("probe", aliases=["status", "check"], help="板况检查（免 halt 采样）")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("fault", help="HardFault 现场取证")
    p.set_defaults(func=cmd_fault)

    p = sub.add_parser("clock", aliases=["clk"], help="时钟/复位状态（HSE 起振/PLL/复位史，免 halt）")
    p.add_argument("--clear", action="store_true", help="顺手清 RCC_CSR 复位标志（跑一段再看 BOR 是否回来）")
    p.set_defaults(func=cmd_clock)

    p = sub.add_parser("watch", aliases=["w"], help="实时看板（tick/LED 连续采样）")
    p.add_argument("-i", "--interval", type=int, default=200, help="采样间隔 ms（默认 200）")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("size", aliases=["sz"], help="固件 FLASH/RAM 占用")
    p.set_defaults(func=cmd_size)

    p = sub.add_parser("kill-stlink", aliases=["kill"], help="释放 ST-Link（结束残留 openocd/f407）")
    p.add_argument("-y", "--yes", action="store_true", help="不再询问")
    p.set_defaults(func=cmd_kill_stlink)

    p = sub.add_parser("usbreset", aliases=["usb"], help="软重启 ST-Link（哑掉/API v0 时）")
    p.set_defaults(func=cmd_usbreset)

    p = sub.add_parser("gdb", help="GDB 调试服务")
    p.add_argument("--client", action="store_true", help="同时拉起 arm-none-eabi-gdb 客户端")
    p.add_argument("--port", type=int, default=3333, help="gdb 端口（默认 3333）")
    p.add_argument("--telnet", type=int, default=4444, help="telnet 端口（默认 4444）")
    p.set_defaults(func=cmd_gdb)

    p = sub.add_parser("ports", aliases=["ls"], help="列串口")
    p.set_defaults(func=cmd_ports)

    p = sub.add_parser("open", aliases=["ide"], help="用 CLion 打开工程")
    p.add_argument("--path", help="clion64.exe 路径")
    p.set_defaults(func=cmd_open)

    p = sub.add_parser("clean", help="删除 build/ build-release/")
    p.add_argument("-y", "--yes", action="store_true", help="不再询问")
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser("doctor", aliases=["doc"], help="环境自检")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("tidy", help="把冗余 .bat 归档到 _tools/legacy_bats（默认预演）")
    p.add_argument("--apply", action="store_true", help="真的移动")
    p.set_defaults(func=cmd_tidy)

    p = sub.add_parser("menu", aliases=["ui"], help="交互菜单（默认）")
    p.set_defaults(func=cmd_menu)

    return ap


def main(argv=None):
    setup_console()
    install_color()
    set_console_title("f407 工具箱 · 罗彬_F407")
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        code = cmd_menu(argparse.Namespace(root=None))
        if getattr(sys, "frozen", False):
            try:
                input("按回车关闭...")
            except (EOFError, KeyboardInterrupt):
                pass
        return code
    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 1
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n[中断]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
