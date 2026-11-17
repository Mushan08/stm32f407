# -*- coding: utf-8 -*-
"""STM32F4 UART bootloader (AN3155) 烧录器 —— 走板载 CH340N (USART1 PA9/PA10) 经 Type-C 烧录。
用法:
  python _tools/stm32_isp.py -a -f build/f407.hex -g     # 自动找 CH340 口
  python _tools/stm32_isp.py -p COM5 -f build/f407.hex -g
进 bootloader: 按住 SW1(BOOT0) -> 按一下 SW2(NRST) -> 松开 SW1。
"""
import argparse
import sys
import time

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("缺少 pyserial: conda/pip 装 pyserial")
    sys.exit(1)

ACK, NACK = 0x79, 0x1F
CH340_VID = 0x1A86


def xor_bytes(data):
    c = 0
    for b in data:
        c ^= b
    return c


def addr_frame(addr):
    b = bytes([(addr >> 24) & 0xFF, (addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF])
    return b + bytes([xor_bytes(b)])


def parse_intel_hex(path):
    """Intel HEX -> [(addr, bytes), ...] 合并后的连续数据块列表（地址升序）"""
    mem = {}
    base = 0
    with open(path, "r") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line or not line.startswith(":"):
                continue
            if len(line) < 11 or len(line) % 2 != 1:
                raise ValueError("第 %d 行格式错误" % ln)
            rec = bytes.fromhex(line[1:])
            n, hi, lo, rtype = rec[0], rec[1], rec[2], rec[3]
            data = rec[4:4 + n]
            if n != len(data):
                raise ValueError("第 %d 行长度不符" % ln)
            if rtype == 0x00:
                addr = base + (hi << 8 | lo)
                for i, b in enumerate(data):
                    mem[addr + i] = b
            elif rtype == 0x01:
                break
            elif rtype == 0x04:
                base = (data[0] << 24) | (data[1] << 16)
            elif rtype == 0x02:
                base = ((data[0] << 8) | data[1]) << 4
            else:
                pass  # 05 (起始线性地址) 等忽略
    if not mem:
        raise ValueError("没有数据记录")
    spans = []
    start = None
    prev = None
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


def find_ch340():
    for p in serial.tools.list_ports.comports():
        if p.vid == CH340_VID:
            return p.device, p.description
    return None, None


class Bootloader:
    def __init__(self, sp):
        self.sp = sp

    def _xfer(self, payload, expect=ACK, timeout=2.0):
        """发送单字节命令帧并等 ACK；AN3155 命令校验 = NOT(命令字节)"""
        self.sp.write(payload + bytes([payload[0] ^ 0xFF]))
        return self._wait_ack(timeout)

    def _wait_ack(self, timeout=2.0):
        t0 = time.time()
        self.sp.timeout = timeout
        r = self.sp.read(1)
        if not r:
            raise TimeoutError("等待应答超时")
        b = r[0]
        if b == ACK:
            return ACK
        if b == NACK:
            raise RuntimeError("收到 NACK")
        raise RuntimeError("意外应答 0x%02X" % b)

    def sync(self, tries=5):
        self.sp.timeout = 1.0
        for i in range(tries):
            self.sp.write(b"\x7f")
            r = self.sp.read(1)
            if r and r[0] == ACK:
                return True
            time.sleep(0.5)
        raise TimeoutError("同步失败：bootloader 无响应")

    def cmd(self, code):
        if self._xfer(bytes([code])) != ACK:
            raise RuntimeError("命令 0x%02X 未确认" % code)

    def get_version(self):
        self.cmd(0x00)
        self.sp.timeout = 2.0
        n = self.sp.read(1)[0]      # N = 随后的字节数（version + 命令表）
        data = self.sp.read(n)
        self._wait_ack()
        return data[0], bytes(data[1:])  # (version byte, 支持的命令表)

    def extended_erase_global(self):
        self.cmd(0x44)
        # global erase: 页数/代码 N=0xFFFF，校验 0x00
        self.sp.write(b"\xff\xff\x00")
        self._wait_ack(45.0)  # mass erase 可能要十几秒

    def write_memory(self, addr, data):
        # AN3155: 每块（≤256B）都是独立 Write Memory 命令 0x31 + 起始地址 + 数据帧
        for off in range(0, len(data), 256):
            chunk = data[off:off + 256]
            self.cmd(0x31)
            self.sp.write(addr_frame(addr + off))
            self._wait_ack(2.0)
            nb1 = len(chunk) - 1
            self.sp.write(bytes([nb1]) + chunk + bytes([xor_bytes(bytes([nb1]) + chunk)]))
            self._wait_ack(2.0)

    def read_memory(self, addr, n):
        self.cmd(0x11)
        self.sp.write(addr_frame(addr))
        self._wait_ack(2.0)
        self.sp.write(bytes([n - 1, (n - 1) ^ 0xFF]))
        self.sp.timeout = 2.0
        data = self.sp.read(n)
        if len(data) != n:
            raise TimeoutError("读内存不足")
        return data

    def go(self, addr):
        self.cmd(0x21)
        self.sp.write(addr_frame(addr))
        self._wait_ack(2.0)


def open_port(name, baud):
    # bootloader: 8 数据位 + 偶校验 + 1 停止位 (8E1)
    return serial.Serial(name, baud, bytesize=8, parity=serial.PARITY_EVEN,
                         stopbits=1, timeout=1.0, write_timeout=2.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--port", help="串口名，如 COM5")
    ap.add_argument("-a", "--auto", action="store_true", help="自动找 CH340 口")
    ap.add_argument("-f", "--firmware", required=True, help="Intel HEX 固件")
    ap.add_argument("-b", "--baud", type=int, default=115200)
    ap.add_argument("-g", "--go", action="store_true", help="烧完跳转运行 app")
    args = ap.parse_args()

    port = args.port
    if port is None and args.auto:
        port, desc = find_ch340()
        if port:
            print("[口] 自动选中 %s (%s)" % (port, desc))
    if port is None:
        print("[口] 未找到 CH340，可用串口:")
        for p in serial.tools.list_ports.comports():
            print("      %s  %s" % (p.device, p.description))
        port = input("输入 COM 口 (回车放弃): ").strip()
        if not port:
            return 1

    spans = parse_intel_hex(args.firmware)
    total = sum(len(d) for _, d in spans)
    print("[固件] %s  %d 块  %d 字节" % (args.firmware, len(spans), total))

    try:
        sp = open_port(port, args.baud)
    except Exception as e:
        print("[错误] 打开 %s 失败: %s" % (port, e))
        print("  串口可能被占用（关掉串口助手/CLion 监视），或口号不对")
        return 1

    try:
        bl = Bootloader(sp)
        try:
            bl.sync()
        except TimeoutError:
            print("[错误] 板子没进 bootloader。操作步骤:")
            print("  1) Type-C 数据线连电脑（确认不是只充电的线）")
            print("  2) 按住 SW1 (BOOT0) 不放")
            print("  3) 按一下 SW2 (NRST) 复位")
            print("  4) 松开 SW1，立刻重跑本脚本")
            print("  原理: BOOT0=1 复位 -> 出厂 bootloader 在 USART1(PA9/PA10) 等待")
            return 1

        ver, cmds = bl.get_version()
        print("[boot] bootloader v%d.%d, %d 条命令" % (ver >> 4, ver & 0x0F, len(cmds)))

        print("[擦除] 全片擦除中（最长 45s）...")
        bl.extended_erase_global()
        print("[擦除] 完成")

        for i, (addr, data) in enumerate(spans, 1):
            bl.write_memory(addr, data)
            print("[写入] 0x%08X  %5d B  (%d/%d)" % (addr, len(data), i, len(spans)))

        bad = 0
        for addr, data in spans:
            got = b""
            for off in range(0, len(data), 256):
                got += bl.read_memory(addr + off, min(256, len(data) - off))
            if got != data:
                diff = sum(1 for a, b in zip(got, data) if a != b) + abs(len(got) - len(data))
                print("[校验] 0x%08X 不一致 %d 字节" % (addr, diff))
                bad += diff
        if bad:
            print("[失败] 校验 %d 字节不符" % bad)
            return 1
        print("[校验] 全部通过")

        if args.go:
            bl.go(spans[0][0])
            print("[运行] 跳转 0x%08X 执行" % spans[0][0])
        else:
            print("[提示] 按一下 SW2 (NRST) 或重新上电运行新固件（BOOT0 保持松开）")
        return 0
    finally:
        sp.close()


if __name__ == "__main__":
    sys.exit(main())
