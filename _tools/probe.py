# -*- coding: utf-8 -*-
"""板况检查：免 halt 内存采样，判定固件是否活着（HANDOFF §4.1 / §8 的自动化版）。

流程：
  1. arm-none-eabi-nm 解析 build/f407.elf 里的 uwTick 地址（地址随构建漂移，不能写死）
  2. openocd mem2array 采样 uwTick + GPIOE IDR，每秒一次 x6（不 halt，不碰核）
  3. 顺带读 RCC_CSR 复位标志（bit25 BORRST = 有欠压史）
  4. 输出判定：活着 / 冻结 / 灯不转 / 连不上

失败最常见原因：ST-Link 没插好 / GDB 调试服务占用 / 双电源共轨（调试时 Type-C 必须拔）。
只依赖标准库。入口：工程根 f407.exe（菜单 5）或 `f407.exe probe`。
"""
import re
import subprocess
import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from toolpaths import nm as _nm, openocd as _openocd  # noqa: E402


def _project_root():
    """工程根。打包成 exe 后 __file__ 落在 _MEIPASS 里，不能用；按 环境变量 -> 可执行文件 -> 源码位置 兜底。"""
    env = os.environ.get("F407_ROOT")
    if env:
        return os.path.abspath(env)
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


ROOT = _project_root()
ELF = os.path.join(ROOT, "build", "f407.elf")
CFG = os.path.join(ROOT, "openocd", "f407vet6.cfg")
OPENOCD = _openocd()
NM = _nm()

GPIOE_IDR = "0x40021010"  # 低电平=灯亮：0x38=PE2 0x34=PE3 0x2C=PE4 0x1C=PE5
RCC_CSR = "0x40023874"    # bit25 BORRST 欠压史 / bit26 PINRST 引脚复位 / bit28 SFTRST
SAMPLES = 6


def out(*args):
    try:
        print(*args)
        sys.stdout.flush()
    except UnicodeEncodeError:
        print(*[str(a).encode("gbk", "replace").decode("gbk") for a in args])


def get_uwtick_addr():
    """nm 找 uwTick；找不到返回 None（退化成只看灯）。"""
    if not os.path.isfile(ELF):
        return None, "build/f407.elf 不存在，先编译"
    try:
        r = subprocess.run([NM, ELF], capture_output=True, timeout=30)
    except Exception as e:
        return None, f"nm 运行失败: {e}"
    m = re.search(r"^([0-9a-fA-F]{8}) [A-Za-z] uwTick\b", r.stdout.decode(errors="replace"), re.M)
    if not m:
        return None, "elf 里没有 uwTick 符号"
    return int(m.group(1), 16), None


def build_tcl(uw_addr):
    """采样脚本。要点：①init 之后 read_memory 才可用 ②echo 的参数必须整体加引号
    （多词会被当成多个参数报 usage）③read_memory 取代弃用的 mem2array。"""
    lines = []
    lines.append("init")
    lines.append("set csr [lindex [read_memory " + RCC_CSR + " 32 1] 0]")
    lines.append('echo "PROBE_CSR [format 0x%08X $csr]"')
    if uw_addr:
        lines.append("proc mon {} {")
        lines.append("  for {set i 0} {$i < %d} {incr i} {" % SAMPLES)
        lines.append("    set t [lindex [read_memory 0x%08X 32 1] 0]" % int(uw_addr))
        lines.append("    set u [lindex [read_memory " + GPIOE_IDR + " 32 1] 0]")
        lines.append('    echo "PROBE_S $i [format 0x%08X $t] [format 0x%08X $u]"')
        lines.append("    sleep 1000")
        lines.append("  }")
        lines.append("}")
    else:
        lines.append("proc mon {} {")
        lines.append("  for {set i 0} {$i < %d} {incr i} {" % SAMPLES)
        lines.append("    set u [lindex [read_memory " + GPIOE_IDR + " 32 1] 0]")
        lines.append('    echo "PROBE_S $i -- [format 0x%08X $u]"')
        lines.append("    sleep 1000")
        lines.append("  }")
        lines.append("}")
    lines.append("mon")
    lines.append("shutdown")
    return "\n".join(lines) + "\n"


def run_probe(tcl):
    fd, path = tempfile.mkstemp(suffix=".tcl", prefix="f407_probe_")
    with os.fdopen(fd, "w") as f:
        f.write(tcl)
    try:
        try:
            r = subprocess.run(
                [OPENOCD, "-f", CFG, "-c", "script " + path.replace("\\", "/")],
                capture_output=True, timeout=45)
            text = (r.stdout or b"") + b"\n" + (r.stderr or b"")
            return r.returncode, text.decode(errors="replace")
        except subprocess.TimeoutExpired as e:
            text = (e.stdout or b"") + b"\n" + (e.stderr or b"")
            return -1, text.decode(errors="replace")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


TRIAGE = [
    "分诊（HANDOFF 铁律）:",
    "  1. ST-Link 插好了吗？gdb 服务开着吗？（f407.exe gdb 会占用 ST-Link，先关）",
    "  2. Type-C 拔了吗？调试时 ST-Link 3.3V 必须是唯一电源（双电源共轨会弄死 SWD）",
    "  3. 四根线：SWDIO=PA13 / SWCLK=PA14 / GND / 3.3V，先查 GND",
    "  4. 速度已内置 300kHz（cfg 固化），再连不上查线不查速度",
    "  5. 若 openocd 打印 STLINK V0J8S0 (API v0) / 被强杀过: 拔插 ST-Link USB，或 f407.exe usbreset",
]


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    addr, err = get_uwtick_addr()
    if addr is None:
        out(f"[警告] {err} -> 只采样 GPIOE 灯位")
    else:
        out(f"[采样] uwTick @ 0x{addr:08X} + GPIOE-IDR，每秒 1 次 x{SAMPLES}（全程不 halt）...")

    code, text = run_probe(build_tcl(addr))

    samples = re.findall(r"PROBE_S (\d+) (\S+) (0x[0-9A-Fa-f]+)", text)
    if not samples:
        out()
        out(f"[失败] openocd 连不上 / 采样中断（退出码 {code}）")
        out()
        for line in TRIAGE:
            out(line)
        if "unable" in text or "Error:" in text:
            out()
            out("---- openocd 尾部输出 ----")
            out("\n".join(text.strip().splitlines()[-8:]))
        return 1

    ticks = [int(s[1], 16) for s in samples if s[1] != "--"]
    idrs = [int(s[2], 16) for s in samples]
    csr_m = re.search(r"PROBE_CSR 0x([0-9A-Fa-f]+)", text)
    csr = int(csr_m.group(1), 16) if csr_m else None

    out()
    out("---------- 采样结果 ----------")
    for s in samples:
        out(f"  #{s[0]}  tick={s[1]}  IDR={s[2]}")
    out()

    verdict = []
    if ticks:
        rate = (ticks[-1] - ticks[0]) // (len(ticks) - 1)
        out(f"tick 速率: {rate} 拍/秒（健康≈1000，HSI-PLL 实测 1006~1016）")
        if rate <= 0:
            verdict.append("[冻结] uwTick 不走 = SysTick 停表，典型供电塌陷签名 -> 查杜邦线/换 Type-C 直通供电")
        else:
            verdict.append("[正常] SysTick 在跑")
    else:
        out("tick: 未采样（无 uwTick 符号）")

    led_names = {0x38: "PE2/LED1", 0x34: "PE3/LED2", 0x2C: "PE4/LED3", 0x1C: "PE5/LED4"}
    distinct = sorted({v for v in idrs})
    fault_blink = {0x00, 0x3C}  # 全灯急闪 = HardFault_Capture 等待取证
    err_blink = {0x14, 0x28}    # PE2+PE4 / PE3+PE5 交替 = Error_Handler
    if set(distinct) <= fault_blink:
        out("灯语: 全灯急闪 = HardFault 现场等待取证")
        verdict.append("[HardFault] 全灯急闪 -> 别按复位，立刻跑 f407.exe fault")
    elif set(distinct) <= err_blink:
        out("灯语: 双灯交替急闪 = Error_Handler（初始化失败）")
        verdict.append("[异常] Error_Handler 签名 -> 查时钟/GPIO/UART 初始化（接串口看打印）")
    elif len(distinct) >= 2:
        names = " -> ".join(led_names.get(v, hex(v)) for v in distinct)
        out(f"灯位轮转: {names}")
        verdict.append("[正常] 流水灯在轮转")
    elif idrs and all(v in led_names for v in idrs):
        out(f"灯位: 恒在 {led_names.get(idrs[0])}，没轮转")
        if ticks and (ticks[-1] - ticks[0]) > 0:
            verdict.append("[异常] tick 在走但灯不轮转 -> 固件主循环卡死/被改，或引脚被外部拉死")
        else:
            verdict.append("[冻结] tick 与灯都停 -> 供电塌陷签名，查线")
    else:
        out(f"灯位: IDR 序列 {[hex(v) for v in idrs]} 不在已知灯位表 -> 固件不是流水灯版/引脚电平异常")

    if csr is not None:
        flags = []
        if csr & (1 << 25):
            flags.append("BORRST=欠压史(杜邦线第一嫌疑)")
        if csr & (1 << 26):
            flags.append("PINRST=正常引脚复位")
        if csr & (1 << 28):
            flags.append("SFTRST=软件复位")
        out(f"RCC_CSR: 0x{csr:08X}  {'; '.join(flags) if flags else '（复位标志已清/无已知标志）'}")

    out()
    for v in verdict:
        out(v)
    ok = len(verdict) >= 2 and all(v.startswith("[正常]") for v in verdict)
    out("[结论] 板子活着，一切正常" if ok else "[结论] 见上方异常项")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
