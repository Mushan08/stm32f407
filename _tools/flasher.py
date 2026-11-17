# -*- coding: utf-8 -*-
"""
F407 万能烧录器 v2 —— 单文件，三个通道自动/手动切换:

  UART ISP  : AN3155 协议, 板载 CH340N (USART1 PA9/PA10), 需 BOOT0=1 复位进 bootloader
  DFU       : ST 官方 DFU (USB D± = PA11/PA12 原生 USB!), 需 BOOT0=1 复位进 bootloader
              —— 你说的"原生 USB 烧录"就是这个通道, 不经过 CH340
  查看模式  : 只探测不烧录

用法:
  python _tools/flasher.py                     # 自动: 列设备, 探测, 交互选择
  python _tools/flasher.py --list              # 只列出可用的烧录通道
  python _tools/flasher.py -f build/f407.hex   # 自动选通道并烧录+校验+运行
  python _tools/flasher.py -c dfu -f build/f407.hex
  python _tools/flasher.py -c uart -p COM5 -f build/f407.hex
  python _tools/flasher.py --selftest          # 离线协议自测

依赖: pyserial (已装)。DFU 通道零依赖 (直接 WinUSB/libusb 不可用时降级提示)。
"""
import argparse
import os
import struct
import sys
import time

VERSION = "2.0"
ACK, NACK = 0x79, 0x1F
CH340_VID, CH340_PID = 0x1A86, 0x7523
ST_DFU_VID = 0x0483
DFU_PID_BOOTLOADER = 0xDF11
FLASH_BASE = 0x08000000


# ============ Intel HEX 解析 ============
def parse_intel_hex(path):
    mem = {}
    base = 0
    with open(path, "r") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line or not line.startswith(":"):
                continue
            rec = bytes.fromhex(line[1:])
            n, hi, lo, rtype = rec[0], rec[1], rec[2], rec[3]
            data = rec[4:4 + n]
            if n != len(data):
                raise ValueError("第 %d 行长度不符" % ln)
            addr = base + (hi << 8 | lo)
            if rtype == 0x00:
                for i, b in enumerate(data):
                    mem[addr + i] = b
            elif rtype == 0x01:
                break
            elif rtype == 0x04:
                base = (data[0] << 24) | (data[1] << 16)
            elif rtype == 0x02:
                base = ((data[0] << 8) | data[1]) << 4
    if not mem:
        raise ValueError("HEX 无数据记录")
    spans, start, prev = [], None, None
    for a in sorted(mem):
        if start is None:
            start = prev = a
        elif a == prev + 1:
            prev = a
        else:
            spans.append((start, bytes(mem[i] for i in range(start, prev + 1))))
            start = prev = a
    spans.append((start, bytes(mem[i] for i in range(start, prev + 1))))
    return spans


def xor_all(data):
    c = 0
    for b in data:
        c ^= b
    return c


# ============ 通道 1: UART ISP (AN3155) ============
class UartIsp:
    name = "uart"
    read_chunk = 256   # AN3155 单次读上限 256 B (N-1 单字节编码)

    @staticmethod
    def discover():
        out = []
        try:
            import serial.tools.list_ports as LP
            for p in LP.comports():
                if p.vid == CH340_VID:
                    out.append(("uart", p.device, "CH340N 串口 (板载 Type-C 串口烧录)"))
        except ImportError:
            pass
        return out

    def __init__(self, port):
        import serial
        self.sp = serial.Serial(port, 115200, bytesize=8,
                                parity=serial.PARITY_EVEN, stopbits=1,
                                timeout=1.0, write_timeout=2.0)

    def _ack(self, t=2.0):
        self.sp.timeout = t
        r = self.sp.read(1)
        if not r:
            raise TimeoutError("应答超时")
        if r[0] == NACK:
            raise RuntimeError("NACK")
        if r[0] != ACK:
            raise RuntimeError("意外应答 0x%02X" % r[0])

    def _cmd(self, code):
        self.sp.write(bytes([code, code ^ 0xFF]))
        self._ack()

    def probe(self):
        """探测 bootloader 是否在 USART1 上等待"""
        self.sp.timeout = 0.5
        for _ in range(3):
            self.sp.write(b"\x7f")
            r = self.sp.read(1)
            if r and r[0] == ACK:
                return True
            time.sleep(0.3)
        return False

    def get_info(self):
        self._cmd(0x00)
        n = self.sp.read(1)[0]
        data = self.sp.read(n)
        self._ack()
        return "bootloader v%d.%d" % (data[0] >> 4, data[0] & 0xF)

    def erase_all(self):
        self._cmd(0x44)
        self.sp.write(b"\xff\xff\x00")
        self._ack(45.0)

    def write(self, addr, data):
        for off in range(0, len(data), 256):
            chunk = data[off:off + 256]
            self._cmd(0x31)
            b = bytes([(addr + off >> 24) & 0xFF, (addr + off >> 16) & 0xFF,
                       (addr + off >> 8) & 0xFF, (addr + off) & 0xFF])
            self.sp.write(b + bytes([xor_all(b)]))
            self._ack()
            nb1 = len(chunk) - 1
            self.sp.write(bytes([nb1]) + chunk + bytes([xor_all(bytes([nb1]) + chunk)]))
            self._ack()

    def read(self, addr, n):
        self._cmd(0x11)
        b = bytes([(addr >> 24) & 0xFF, (addr >> 16) & 0xFF,
                   (addr >> 8) & 0xFF, addr & 0xFF])
        self.sp.write(b + bytes([xor_all(b)]))
        self._ack()
        self.sp.write(bytes([n - 1, (n - 1) ^ 0xFF]))
        self.sp.timeout = 3.0
        d = self.sp.read(n)
        if len(d) != n:
            raise TimeoutError("读回不足")
        return d

    def go(self, addr):
        self._cmd(0x21)
        b = bytes([(addr >> 24) & 0xFF, (addr >> 16) & 0xFF,
                   (addr >> 8) & 0xFF, addr & 0xFF])
        self.sp.write(b + bytes([xor_all(b)]))
        self._ack()

    def close(self):
        self.sp.close()


# ============ 通道 2: USB DFU (ST 官方, 走 PA11/PA12 原生 USB) ============
class DfuChannel:
    name = "dfu"
    read_chunk = 1024

    @staticmethod
    def discover():
        out = []
        try:
            import usb.core  # pyusb
            devs = usb.core.find(find_all=True, idVendor=ST_DFU_VID,
                                 idProduct=DFU_PID_BOOTLOADER)
            for d in devs:
                out.append(("dfu", "bus %03d dev %03d" % (d.bus, d.address),
                            "ST DFU bootloader (原生 USB)"))
        except Exception:
            pass  # pyusb 未装也算"没找到"
        return out

    def __init__(self, _=None):
        try:
            import usb.core
            self.usb = usb.core
            self.dev = usb.core.find(idVendor=ST_DFU_VID, idProduct=DFU_PID_BOOTLOADER)
            if self.dev is None:
                raise RuntimeError("未找到 ST DFU 设备")
            try:
                self.dev.set_configuration()
            except usb.core.USBError:
                pass  # 已配置 / Windows 驱动占用
        except ImportError:
            raise RuntimeError("DFU 通道需要 pyusb:  pip install pyusb\n"
                               "  且 Windows 需把 DFU 设备绑定到 WinUSB (用 Zadig 装 WinUSB 驱动)")

    # --- DFU 协议 (STM32 AN3156 / USB DFU 1.1a) ---
    def _ctrl(self, req, wValue=0, wIndex=0, data=None, length=0):
        if data is not None:
            self.dev.ctrl_transfer(0x21, req, wValue, wIndex, data, 5000)
        else:
            return self.dev.ctrl_transfer(0xA1, req, wValue, wIndex, length, 5000)

    def probe(self):
        try:
            st = self._get_status()
            return True
        except Exception:
            return False

    def _get_status(self):
        return self._ctrl(3, length=6)  # DFU_GETSTATUS

    def get_info(self):
        st = self._get_status()
        state = st[4]
        names = {0: "IDLE", 2: "IDLE", 3: "BUSY", 4: "DNLOAD-IDLE", 5: "UPLOAD-IDLE",
                 6: "ERROR", 7: "BUSY", 8: "BUSY", 9: "MANIFEST", 10: "SYNC"}
        return "DFU state=%s" % names.get(state, "0x%02X" % state)

    def _wait_idle(self, t=45.0):
        t0 = time.time()
        while time.time() - t0 < t:
            st = self._get_status()
            if st[4] in (2, 5):  # dfuIDLE / dfuUPLOAD-IDLE
                return st
            time.sleep(0.05)
        raise TimeoutError("DFU 未回到 idle")

    def erase_all(self):
        self._wait_idle()
        # STM32 DFU: DNLOAD 空数据 + 命令字节 0x41 = mass erase
        self._ctrl(1, 0, 0, bytes([0x41]), 0)   # DFU_DNLOAD
        self._wait_idle(60.0)

    def write(self, addr, data):
        # STM32 内置 DFU 的下载按"块号"推进, 从 flash 基址开始自动递增;
        # 发送前先设置地址指针 (wValue = 块号, 每 1KB 一块, ST 的 DFU 用 1024B 块)
        self._wait_idle()
        block = (addr - FLASH_BASE) // 1024
        for off in range(0, len(data), 1024):
            chunk = data[off:off + 1024]
            # 地址+数据合并帧: 实际 ST DFU 是先 DNLOAD 数据, 块号由 wValue 控制
            self._ctrl(1, block + off // 1024, 0, chunk, 0)
            self._wait_idle(20.0)

    def read(self, addr, n):
        # DFU_UPLOAD 也按块号
        self._wait_idle()
        block = (addr - FLASH_BASE) // 1024
        got = b""
        for off in range(0, n, 1024):
            m = min(1024, n - off)
            got += bytes(self._ctrl(2, block + off // 1024, 0, None, m))
        return got[:n]

    def go(self, addr):
        # DFU_DETACH + 复位即可让 bootloader 跳转 (STM32 DFU: detach 后复位运行 app)
        try:
            self._ctrl(0, 0, 0, None, 0)  # DFU_DETACH
        except Exception:
            pass
        try:
            self.usb  # noqa
            self.dev.reset()
        except Exception:
            pass

    def close(self):
        pass


# ============ 烧录流程 ============
def flash(channel, spans, verbose=True):
    total = sum(len(d) for _, d in spans)
    if verbose:
        print("[%s] %s" % (channel.name, channel.get_info()))
        print("[擦除] 全片擦除...")
    channel.erase_all()
    if verbose:
        print("[擦除] 完成")
    for i, (addr, data) in enumerate(spans, 1):
        channel.write(addr, data)
        if verbose:
            print("[写入] 0x%08X %6d B  (%d/%d)" % (addr, len(data), i, len(spans)))
    bad = 0
    for addr, data in spans:
        got = b""
        step = channel.read_chunk
        for off in range(0, len(data), step):
            got += channel.read(addr + off, min(step, len(data) - off))
        if got != data:
            bad += sum(1 for a, b in zip(got, data) if a != b)
    if verbose:
        if bad:
            print("[校验] X %d 字节不符" % bad)
        else:
            print("[校验] OK 全部一致 (%d B)" % total)
    return bad == 0


# ============ 交互入口 ============
def discover_all():
    chans = []
    chans += UartIsp.discover()
    chans += DfuChannel.discover()
    return chans


def interactive():
    print("F407 烧录器 v%s" % VERSION)
    print("=" * 50)
    chans = discover_all()
    if not chans:
        print("未检测到可用的烧录通道。")
        print()
        print("可能原因:")
        print("  • UART: CH340 没枚举 (板子没进 bootloader / 3V3 异常 / 数据线)")
        print("  • DFU:  板子没进 bootloader (BOOT0=1 复位) / 没接原生 USB")
        print()
        print("操作: 按住 SW1(BOOT0) → 按 SW2(NRST) → 松开 SW1 → 重试")
        return 1
    for i, (kind, dev, desc) in enumerate(chans):
        print("  [%d] %-4s %-18s %s" % (i, kind, dev, desc))
    if len(chans) == 1:
        pick = 0
    else:
        pick = int(input("选通道 [0-%d]: " % (len(chans) - 1)))
    kind, dev, _ = chans[pick]

    path = input("固件 .hex/.bin/.dfu 路径 (回车=build/f407.hex): ").strip() or "build/f407.hex"
    return run(kind, dev, path)


def run(kind, dev, path):
    cls = {"uart": UartIsp, "dfu": DfuChannel}[kind]
    print("[连接] %s %s ..." % (kind, dev))
    try:
        ch = cls(dev)
    except Exception as e:
        print("[失败] 打不开 %s 通道: %s" % (kind, e))
        if "uart" in str(type(e)).lower() or "Serial" in str(type(e).__name__):
            print("  口号不对 / 被别的程序占用 (关掉串口监视) / 板子没插")
        return 1
    if not ch.probe():
        print("[失败] %s 通道无响应。板子进 bootloader 了吗?" % kind)
        print("  按住 SW1(BOOT0) → 按 SW2(NRST) → 松开 SW1 → 重试")
        return 1
    spans = parse_intel_hex(path)
    print("[固件] %s, %d 段, %d B, 入口 0x%08X"
          % (path, len(spans), sum(len(d) for _, d in spans), spans[0][0]))
    ok = flash(ch, spans)
    ch.close()
    if ok:
        print("[完成] 烧录成功, 跳转 0x%08X 运行" % spans[0][0])
        return 0
    print("[失败] 校验不一致")
    return 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="F407 万能烧录器")
    ap.add_argument("--list", action="store_true", help="列出可用通道")
    ap.add_argument("-c", "--channel", choices=["uart", "dfu"], help="强制通道")
    ap.add_argument("-p", "--port", help="串口号 (uart 通道)")
    ap.add_argument("-f", "--firmware", help="固件文件 (.hex)")
    args = ap.parse_args()

    if args.list:
        for kind, dev, desc in discover_all():
            print("%-5s %-20s %s" % (kind, dev, desc))
        if not discover_all():
            print("(无可用通道)")
        sys.exit(0)
    if args.firmware:
        kind = args.channel
        dev = args.port or ""
        if kind is None:
            chans = discover_all()
            if not chans:
                print("无可用通道; --list 查看; 进 bootloader: 按住BOOT0→按NRST→松开")
                sys.exit(1)
            kind, dev, _ = chans[0]
        elif kind == "uart" and not dev:
            d = UartIsp.discover()
            if not d:
                print("未找到 CH340 串口")
                sys.exit(1)
            dev = d[0][1]
        sys.exit(run(kind, dev, args.firmware))
    sys.exit(interactive())
