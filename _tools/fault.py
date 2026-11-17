# -*- coding: utf-8 -*-
"""HardFault 取证：免 halt 读固件捕获的异常现场 + addr2line 直出源码行。

固件侧（stm32f4xx_it.c 的 HardFault_Capture）在崩的瞬间把栈帧 + CFSR/BFAR/MMFAR/HFSR
抄进 g_fault_capture（14 字），然后全灯急闪等待取证。本工具：
  1. nm 解析 g_fault_capture 地址（随构建漂移，不能写死）
  2. openocd read_memory 读出 14 个字，校验魔数 0xFA17C0DE
  3. 解码 CFSR 判定故障类型（精确/非精确、升级来源、BFAR 地址）
  4. addr2line 定位 PC（出错指令）与 LR（返回地址）到 源文件:行号

使用前提：板子正处全灯急闪状态、且没按过复位（复位/断电 = 现场清零）。
入口：工程根 f407.exe（菜单 6）或 `f407.exe fault`。只依赖标准库。
"""
import re
import subprocess
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe import run_probe, out, NM, ROOT, ELF  # noqa: E402
from toolpaths import addr2line as _addr2line  # noqa: E402

ADDR2LINE = _addr2line()

FAULT_MAGIC = 0xFA17C0DE
N_WORDS = 14
FIELD_NAMES = ["magic", "r0", "r1", "r2", "r3", "r12", "lr", "pc", "xpsr", "sp",
               "CFSR", "BFAR", "MMFAR", "HFSR"]


def find_symbol(sym):
    if not os.path.isfile(ELF):
        return None, "build/f407.elf 不存在，先编译"
    r = subprocess.run([NM, ELF], capture_output=True, timeout=30)
    # 注意别用 $ 锚点：Windows nm 输出行尾带 \r，$ 会永远匹配不上（probe 用 \b 就没这个坑）
    m = re.search(r"^([0-9a-fA-F]{8}) [A-Za-z] " + re.escape(sym) + r"\b",
                  r.stdout.decode(errors="replace"), re.M)
    if not m:
        return None, f"elf 里没有 {sym} 符号（固件是不是旧版？先烧新固件）"
    return int(m.group(1), 16), None


def addr2line(addr):
    r = subprocess.run([ADDR2LINE, "-e", ELF, "-f", "-C", hex(addr)],
                       capture_output=True, timeout=30)
    lines = r.stdout.decode(errors="replace").strip().splitlines()
    func = lines[0] if len(lines) > 0 else "?"
    where = lines[1] if len(lines) > 1 else "?"
    return func, where


def decode_cfsr(cfsr):
    flags = []
    mm, bf, uf = cfsr & 0xFF, (cfsr >> 8) & 0xFF, (cfsr >> 16) & 0xFFFF
    if mm & 0x01:
        flags.append("IACCVIOL=存储器区执行")
    if mm & 0x10:
        flags.append("MSTKERR=入栈失败")
    if mm & 0x80:
        flags.append("MMARVALID")
    if bf & 0x01:
        flags.append("IBUSERR=取指总线错")
    if bf & 0x02:
        flags.append("PRECISERR=精确总线错误(PC可信)")
    if bf & 0x04:
        flags.append("IMPRECISERR=非精确总线错误(PC不可信,写缓冲延迟)")
    if bf & 0x07:
        flags.append("BFARVALID" if bf & 0x80 else "BFAR无效(BFARVALID=0)")
    if uf & 0x0001:
        flags.append("UNDEFINSTR=未定义指令")
    if uf & 0x0002:
        flags.append("INVSTATE=状态错(T位)")
    if uf & 0x0004:
        flags.append("INVPC=非法返回(EXC_RETURN坏)")
    if uf & 0x0008:
        flags.append("NOCP=协处理器没开(FPU?)")
    if uf & 0x0200:
        flags.append("DIVBYZERO=除零")
    return flags


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    addr, err = find_symbol("g_fault_capture")
    if addr is None:
        out(f"[失败] {err}")
        return 1

    tcl = "\n".join([
        "init",
        "set v [read_memory 0x%08X 32 %d]" % (addr, N_WORDS),
        "set i 0",
        "foreach w $v { echo \"FAULT_W $i [format 0x%08X $w]\"; incr i }",
        "shutdown",
    ]) + "\n"
    out(f"[取证] g_fault_capture @ 0x{addr:08X}（免 halt）...")
    code, text = run_probe(tcl)

    words = {}
    for m in re.finditer(r"FAULT_W (\d+) 0x([0-9A-Fa-f]+)", text):
        words[int(m.group(1))] = int(m.group(2), 16)
    if len(words) < N_WORDS:
        out(f"[失败] 读现场失败（openocd 连不上/被占用，退出码 {code}）")
        out("  前提检查: ST-Link 四线在、GDB服务没开、Type-C 已拔（铁律同板况检查）")
        if "Error" in text:
            out("---- openocd 尾部输出 ----")
            out("\n".join(text.strip().splitlines()[-6:]))
        return 1

    if words[0] != FAULT_MAGIC:
        out("[结论] 没有未处置的 HardFault 现场（魔数不符）")
        out("  两种情况：")
        out("  a) 板子没崩过（灯语是流水灯 = 正常，跑 f407.exe probe 确认）")
        out("  b) 崩过但已经复位/断电 -> 现场被清了。下次崩溃后【别按复位】直接跑本工具")
        return 1

    out()
    out("---------- HardFault 现场 ----------")
    for i in range(N_WORDS):
        out(f"  {FIELD_NAMES[i]:>5} = 0x{words[i]:08X}")
    out()

    pc, lr, xpsr, cfsr, bfar = words[7], words[6], words[8], words[10], words[11]
    flags = decode_cfsr(cfsr)
    out(f"CFSR 解码: {'; '.join(flags) if flags else '（无标志位）'}")
    if not flags:
        out("[警告] CFSR 全零：异常在抄寄存器前已被清（ unlikely）或旧固件现场")
    if "IMPRECISERR" in " ".join(flags):
        out("[警告] 非精确总线错误：栈帧 PC 是错误爆发点不是出错点！")
        out("       正常应已被 DISDEFWBUF 变精确——若再现，查是否换了旧固件/别的总线主闯祸")
    if "BFARVALID" in " ".join(flags):
        out(f"出错总线地址 BFAR = 0x{bfar:08X}")

    hfsr = words[13]
    if hfsr & (1 << 30):
        out("HFSR.FORCED=1：由下方 flags 里的低级故障升级而来")
    if hfsr & (1 << 1):
        out("HFSR.VECTTBL=1：向量表读取错（VTOR 指错地方）")

    ok = True
    for tag, val in (("PC（出错指令）", pc), ("LR（返回地址）", lr)):
        func, where = addr2line(val)
        out(f"{tag}: 0x{val:08X} -> {func} @ {where}")

    if "IMPRECISERR" in " ".join(flags):
        ok = False
        out("[结论] 非精确错误：定位不可信。先确认固件开了 DISDEFWBUF，再复现一次")
    else:
        func, where = addr2line(pc)
        known = ("?? " not in where) and where != "?"
        ok = known
        out()
        if ok:
            out(f"[结论] 崩溃点已定位（{where} 即源码行）")
        else:
            out("[结论] PC 落在无源码区域（0xffffffxx=非法跳转/回调表坏），查 LR 和函数指针")
    out("[提醒] 取证完成后：板子复位即可恢复流水灯；把崩溃点行号发给下一轮对话可直接修")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
