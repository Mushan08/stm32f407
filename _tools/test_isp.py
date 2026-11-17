# -*- coding: utf-8 -*-
"""stm32_isp 协议自测：FakeSerial 模拟 AN3155 bootloader，不接硬件验证全流程。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import stm32_isp as isp  # noqa: E402

ACK, NACK = 0x79, 0x1F
CMD_GET, CMD_WRITE, CMD_READ, CMD_EE, CMD_GO = 0x00, 0x31, 0x11, 0x44, 0x21


class FakeSerial:
    """模拟 STM32 出厂 bootloader 的串口两端"""

    def __init__(self):
        self.rx = bytearray()          # bootloader -> host 应答队列
        self.flash = {}
        self.buf = bytearray()         # host -> bootloader 帧缓冲
        self.state = "sync"
        self.pending_cmd = None
        self.pending_addr = None
        self.timeout = 1.0

    # ---- host -> bootloader ----
    def write(self, data):
        for b in data:
            self._feed(b)

    # ---- bootloader -> host ----
    def read(self, n):
        out = self.rx[:n]
        del self.rx[:n]
        return bytes(out)

    def close(self):
        pass

    # ---- helpers ----
    def _ack(self):
        self.rx.append(ACK)

    def _nack(self):
        self.rx.append(NACK)
        self.state = "cmd"
        self.buf.clear()

    def _feed(self, b):
        self.buf.append(b)
        st, buf = self.state, self.buf

        if st == "sync":
            if b == 0x7F:
                self._ack()
                self.state = "cmd"
                self.buf.clear()
            return

        if st == "cmd":
            if len(buf) < 2:
                return
            cmd, ck = buf[0], buf[1]
            self.buf.clear()
            if ck != (cmd ^ 0xFF):
                self._nack()
                return
            self._dispatch_cmd(cmd)
            return

        if st == "addr":
            if len(buf) < 5:
                return
            a = (buf[0] << 24) | (buf[1] << 16) | (buf[2] << 8) | buf[3]
            ck_ok = buf[4] == (buf[0] ^ buf[1] ^ buf[2] ^ buf[3])
            self.buf.clear()
            if not ck_ok:
                self._nack()
                return
            self.pending_addr = a
            self._ack()
            self.state = "wdata" if self.pending_cmd == CMD_WRITE else \
                ("rdata" if self.pending_cmd == CMD_READ else "cmd")
            return

        if st == "erase":
            if len(buf) < 3:
                return
            ok = (buf[0], buf[1], buf[2]) == (0xFF, 0xFF, 0x00)
            self.buf.clear()
            if ok:
                self._ack()
                self.state = "cmd"
            else:
                self._nack()
            return

        if st == "wdata":
            n1 = buf[0]
            # 块帧之后允许任意新命令：完整命令帧(命令+取反校验)到达才处理
            if n1 in (CMD_GET, CMD_WRITE, CMD_READ, CMD_EE, CMD_GO):
                if len(buf) < 2:
                    return
                ok = buf[1] == (n1 ^ 0xFF)
                self.buf.clear()
                if not ok:
                    self._nack()
                    return
                self._dispatch_cmd(n1)
                return
            need = 1 + (n1 + 1) + 1
            if len(buf) < need:
                return
            frame = bytes(buf[:need])
            self.buf.clear()
            # AN3155: 校验 = 长度字节与数据逐字节异或
            if frame[-1] != isp.xor_bytes(bytes([n1]) + frame[1:-1]):
                self._nack()
                return
            data = frame[1:-1]
            for i, db in enumerate(data):
                self.flash[self.pending_addr + i] = db
            self._ack()
            return

        if st == "rdata":
            if len(buf) < 2:
                return
            n1, ck = buf[0], buf[1]
            self.buf.clear()
            if ck != (n1 ^ 0xFF):
                self._nack()
                return
            n = n1 + 1
            for i in range(n):
                self.rx.append(self.flash.get(self.pending_addr + i, 0xFF))
            self.state = "cmd"
            return

        self._nack()

    def _handle_cmd(self, cmd):
        self.pending_cmd = cmd
        self._ack()
        self.state = "addr"

    def _dispatch_cmd(self, cmd):
        if cmd == CMD_GET:
            # AN3155 序列: 命令确认 ACK -> N 字节(version+命令表) -> 结束 ACK
            table = bytes([CMD_GET, 0x02, CMD_WRITE, CMD_READ, CMD_EE, CMD_GO,
                           0, 0, 0, 0, 0, 0])
            body = bytes([0x31]) + table
            self._ack()
            self.rx.append(len(body))
            self.rx += body
            self._ack()
        elif cmd == CMD_WRITE:
            self._handle_cmd(cmd)
        elif cmd == CMD_READ:
            self._handle_cmd(cmd)
        elif cmd == CMD_EE:
            self._ack()
            self.state = "erase"
        elif cmd == CMD_GO:
            self._handle_cmd(cmd)
        else:
            self._nack()

    def flash_bytes(self, addr, n):
        return bytes(self.flash.get(addr + i, 0xFF) for i in range(n))


def main():
    fs = FakeSerial()
    bl = isp.Bootloader(fs)

    assert bl.sync() is True
    ver, cmds = bl.get_version()
    assert ver == 0x31 and len(cmds) == 12
    print("PASS sync/get  (boot v%d.%d, %d cmds)" % (ver >> 4, ver & 0xF, len(cmds)))

    bl.extended_erase_global()
    print("PASS extended_erase_global")

    spans = isp.parse_intel_hex(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "build", "f407.hex"))
    assert spans[0][0] == 0x08000000, "hex 首地址应为 FLASH 起点: 0x%08X" % spans[0][0]
    total = sum(len(d) for _, d in spans)
    print("PASS parse_hex  (start=0x%08X, spans=%d, %d B)" % (spans[0][0], len(spans), total))

    for addr, data in spans:
        bl.write_memory(addr, data)
    for addr, data in spans:  # mock flash 内容 == 解析内容
        assert fs.flash_bytes(addr, len(data)) == data, "0x%08X 写入不符" % addr
    print("PASS write_memory (校验和/分块/地址帧全部正确)")

    for addr, data in spans:
        got = b""
        for off in range(0, len(data), 256):
            got += bl.read_memory(addr + off, min(256, len(data) - off))
        assert got == data, "0x%08X 读回不符" % addr
    print("PASS read_memory (verify 路径)")

    bl.go(spans[0][0])
    print("PASS go")

    # 负例：坏校验的数据块帧应被 bootloader 拒绝(NACK)且状态复位到 cmd
    fs.rx.clear()
    fs.state = "wdata"
    fs.pending_addr = spans[0][0]
    fs.buf.clear()
    fs.write(b"\x07" + b"\xAA" * 8 + b"\x00")  # cksum 错
    assert fs.rx and fs.rx[-1] == NACK, "坏帧未被拒绝"
    assert fs.state == "cmd", "NACK 后未回到命令等待状态"
    print("PASS negative (坏校验帧被 bootloader 拒绝)")
    print("ALL 7 CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
