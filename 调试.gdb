# F407 调试快捷脚本：arm-none-eabi-gdb build/f407.elf -x 调试.gdb -ex "target remote localhost:3333" ...
# GDB调试服务.bat 起服务后，把上面整行贴进另一终端即可；faultinfo/reload 是本文件定义的快捷命令。

set pagination off
set print pretty on

# 读 HardFault 捕获现场并定位源码行（等价 故障定位.bat，但走 gdb）
define faultinfo
  set $f = g_fault_capture
  printf "magic=0x%x  r0=0x%x r1=0x%x r2=0x%x r3=0x%x r12=0x%x sp=0x%x\n", $f[0], $f[1], $f[2], $f[3], $f[4], $f[5], $f[9]
  set $fpc = (unsigned long)$f[7]
  set $flr = (unsigned long)$f[6]
  printf "PC(出错指令) 0x%x -> ", $fpc
  info line *$fpc
  printf "LR(返回地址) 0x%x -> ", $flr
  info line *$flr
end
document faultinfo
读 g_fault_capture 捕获的 HardFault 现场 + addr2line 定位崩溃源码行
end

# 重编译后在线更新固件：load 写入 + 软复位跑起来
define reload
  load
  monitor reset
end
document reload
load 最新 elf 并软复位运行（gdb 会话不断开）
end
