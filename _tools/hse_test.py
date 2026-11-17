# -*- coding: utf-8 -*-
"""HSE 晶振(X2 8MHz)检测：SWD 直接置 RCC_CR.HSEON，轮询 HSERDY（HANDOFF §6-3 复检手法）。

不动系统时钟——PLL 仍由 HSI 供着，开/关 HSE 只碰 X2 振荡器本身，对跑着的固件零影响。
判据：置 HSEON 后 ~3 秒窗口内 HSERDY 置位 = 起振；恒 0 = 还没起振。
测完自动把 HSEON 清掉复原。用法：python -I _tools/hse_test.py
"""
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe import run_probe, out  # noqa: E402

RCC_CR = "0x40023800"
HSEON = 1 << 16    # 0x00010000
HSERDY = 1 << 17   # 0x00020000
POLLS = 20         # x150ms = 3s 窗口（HSE 起振典型 1~2ms）


def build_tcl(clear_at_end):
    """clear_at_end=False 时绝不清 HSEON——固件自己开的 HSE（PLL 正吃着它）动不得，
    清了 = 掐死系统时钟。只有我们自设的 HSEON（init 时 HSEON=0）才由我们收掉。"""
    lines = []
    lines.append("init")
    lines.append("set cr [lindex [read_memory %s 32 1] 0]" % RCC_CR)
    lines.append('echo "HSE_INIT [format 0x%08X $cr]"')
    lines.append("mww %s [expr {$cr | 0x%08X}]" % (RCC_CR, HSEON))
    lines.append("proc poll {} {")
    lines.append("  for {set i 1} {$i <= %d} {incr i} {" % POLLS)
    lines.append("    sleep 150")
    lines.append("    set v [lindex [read_memory %s 32 1] 0]" % RCC_CR)
    lines.append('    echo "POLL $i [format 0x%08X $v]"')
    lines.append("  }")
    lines.append("}")
    lines.append("poll")
    if clear_at_end:
        lines.append("set cr2 [lindex [read_memory %s 32 1] 0]" % RCC_CR)
        lines.append("mww %s [expr {$cr2 & 0xFFFEFFFF}]" % RCC_CR)  # 清自设的 HSEON
    lines.append("shutdown")
    return "\n".join(lines) + "\n"


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    out(f"[晶振检测] 每 150ms 查 HSERDY x{POLLS}（不动系统时钟；若 HSEON 原本就开着则测完不碰它）...")
    code, text = run_probe(build_tcl(clear_at_end=False))

    init_m = re.search(r"HSE_INIT (0x[0-9A-Fa-f]+)", text)
    polls = re.findall(r"POLL (\d+) (0x[0-9A-Fa-f]+)", text)
    if not init_m or not polls:
        out(f"[失败] 没采到读数（openocd 连不上/被占用，退出码 {code}）")
        out("  前提: ST-Link 四线在、GDB服务没开、Type-C 已拔（铁律同板况检查）")
        if "Error" in text:
            out("---- openocd 尾部输出 ----")
            out("\n".join(text.strip().splitlines()[-6:]))
        return 1

    cr0 = int(init_m.group(1), 16)
    fw_on = bool(cr0 & HSEON)
    out(f"初始 RCC_CR = 0x{cr0:08X}（HSEON={(cr0 >> 16) & 1}, HSERDY={(cr0 >> 17) & 1}）"
        + ("  <- 固件自己开的 HSE" if fw_on else ""))
    out()

    ready_at = None
    for idx, val in polls:
        v = int(val, 16)
        if v & HSERDY and ready_at is None:
            ready_at = int(idx)
        out(f"  #{idx:>2}  RCC_CR=0x{v:08X}  HSEON={(v >> 16) & 1} HSERDY={(v >> 17) & 1}"
            + ("  <<< 起振!" if v & HSERDY else ""))

    out()
    if ready_at is not None:
        if fw_on:
            out("[结论] 晶振正常 ✓——且固件本尊已开 HSE（HSERDY=1）= 系统 clock 走 HSE-PLL 的最强证明")
            out("       这是最硬状态：不需要再做任何事")
        else:
            out(f"[结论] 晶振正常 ✓ HSERDY 在置 HSEON 后 ~{ready_at * 150}ms 置位（典型 1~2ms 量级）")
            out("       X2 8MHz 能起振；要用它跑 PLL：固件 SystemClock_Config 的 HSE 分支即可")
        return 0
    out("[结论] X2 仍未起振 ✗ 3 秒窗口 HSERDY 恒 0")
    out("       下一步: ①烙铁再润 X2/C3/C4 焊点 ②确认脱焊的引脚是不是晶振回路上的")
    out("       ③仍不行换 8MHz 晶振（HANDOFF §6-3）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
