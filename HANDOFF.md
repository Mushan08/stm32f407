# 罗彬_F407VET6 核心板 —— 软件调试与嵌入式开发交付文档

> 写给新对话/新接手者。先读完本文档再动手。
> 硬件板卡丝印：罗彬_F407（自绘核心板，2026-11-09 评审，11-15 到手，11-16~17 调试至全速运行）。
> 详细记忆版在 ZCode 记忆库 `f407-hal-project.md`；本文是面向软件调试与后续开发的完整交接版。

---

## 0. 30 秒速览

- **主开发工程**：`C:\Users\MushanLuo\CLionProjects\stm32f407`（git main `0e704f5`，**最新官方 HAL**，本仓库）
- **旧工程（历史参考）**：`E:\zwork\f407-hal`（git main `9664d50`，2017 gitee 镜像 HAL，包含大量调试记忆）
- **工具链**：`E:\zwork\dev-toolkit`（xpack arm-gcc 14.2.1 / ninja / cmake / openocd 0.12，**全部绝对路径，不依赖 PATH**）
- **当前固件**：流水灯 PE2→PE3→PE4→PE5，300ms/拍，低电平点亮；printf 走 USART1 115200
- **真机状态**：tick 1006~1016 拍/秒零冻结、四灯轮转已实证（2026-11-17 16:5x 重烧后 `f407.exe probe`：1011 拍/秒，IDR 采到 PE5/PE4/PE3/PE2 全相位）；HSE 晶振不起振（跑 HSI-PLL≈168.25MHz，无影响）
- **接手第一步**：双击根目录 `f407.exe`（菜单 5 = 板况检查；命令行 `f407.exe probe`），免 halt 采样，自动判定活着/冻结/欠压史，等于 §4.1+§4.4 的自动化
- **唯一入口**：`f407.exe`（菜单 + 子命令，取代原来的 12 个 .bat；旧 bat 已归档在 `_tools/legacy_bats/`）。exe 不入 git（7.7MB，可重建），新克隆先跑一次 `python _tools/build_exe.py`
- **看不懂工具在干嘛**：先读 `工具箱讲解.md`（大白话版：每个键干嘛、数字怎么读、故障怎么走、三件硬件怎么量）
- **要写代码/加外设**：读 `HAL入门.md`（五步套路 + TIM6 可编译实战）和 `本板开发注意事项.md`（引脚占用、时钟/供电/CCM 约束）
- **铁律三条**：①调试时拔 Type-C、只用 ST-Link 4 线供电（双电源共轨会弄死 SWD）②烧录用 `reset_config none`（SRST 复位在杜邦 NRST 线上会超时）③SWD 连不上先降速 300kHz、先查 GND 线

---

## 1. 工程与工具坐标表（全部可复制）

| 项 | 路径 |
|---|---|
| 主工程 | `C:\Users\MushanLuo\CLionProjects\stm32f407` |
| 旧工程（2017 HAL + 调试史） | `E:\zwork\f407-hal` |
| 工具链根 | `E:\zwork\dev-toolkit` |
| cmake | `E:/zwork/dev-toolkit/tools/cmake/bin/cmake.exe` |
| ninja | `E:/zwork/dev-toolkit/tools/ninja/ninja.exe` |
| arm-gcc bin | `E:/zwork/dev-toolkit/tools/arm-none-eabi-gcc/xpack-arm-none-eabi-gcc-14.2.1-1.1/bin`（含 gdb/addr2line/nm/objdump） |
| openocd | `E:/zwork/dev-toolkit/tools/openocd/xpack-openocd-0.12.0-7/bin/openocd.exe` |
| ST-Link | V2 克隆，固件 V2J27S6，序列 `B55B5AAE00000000CB020500`，**驱动已换 WinUSB（Zadig）** |
| HAL 拉取暂存区 | `E:\zwork\_hal_latest`（~130MB，含三个官方源仓库的 clone，可删可留作升级参考） |

### 构建（Git Bash，逐字可复制）

```bash
cd /c/Users/MushanLuo/CLionProjects/stm32f407
C="E:/zwork/dev-toolkit/tools/cmake/bin/cmake.exe"
"$C" -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_MAKE_PROGRAM="E:/zwork/dev-toolkit/tools/ninja/ninja.exe"
"$C" --build build
```

或直接 `f407.exe build`（根目录 `f407.exe`，双击出菜单选 1）。产物：`build/f407.elf`（+ .bin/.hex/.map）。

### 烧录（SWD，当前唯一可靠通道）

```bash
cd /c/Users/MushanLuo/CLionProjects/stm32f407
"E:/zwork/dev-toolkit/tools/openocd/xpack-openocd-0.12.0-7/bin/openocd.exe" \
  -f openocd/f407vet6.cfg -c "adapter speed 300" -c "reset_config none" \
  -c "program build/f407.elf verify reset exit"
```

或 `f407.exe flash`（已内置 300kHz + reset_config none，不用记命令）。成功标志：`** Programming Finished **` → `** Verified OK **` → `** Resetting Target **`。

### 工具箱子命令速查（f407.exe）

| 命令 | 对应旧 bat |
|---|---|
| `f407.exe` | 主菜单.bat |
| `f407.exe build [--relink]` | 构建.bat |
| `f407.exe flash [--no-build]` | 烧录.bat |
| `f407.exe` 菜单 3 | 烧录并监视.bat |
| `f407.exe typec` | typec烧录.bat |
| `f407.exe probe` | 板况检查.bat |
| `f407.exe watch [-i 200]` | （新增）实时看板：单会话连续采样，tick 速率 + 灯位一行刷新 |
| `f407.exe clock` | （新增）HSE 起振/PLL/系统时钟源/复位标志，免 halt 一次读完 |
| `f407.exe fault` | 故障定位.bat |
| `f407.exe gdb [--client]` | GDB调试服务.bat |
| `f407.exe monitor [COMx]` | 串口监视.bat |
| `f407.exe ports` | 查看串口.bat |
| `f407.exe open` | 打开工程.bat |
| `f407.exe clean -y` | 清理构建.bat |
| `f407.exe doctor` | （新增）环境自检 |
| `f407.exe size` | （新增）FLASH/RAM 占用条 |
| `f407.exe kill-stlink` | （新增）结束残留 openocd/f407，释放 ST-Link |
| `f407.exe usbreset` | （新增）软重启 ST-Link（枚举成 `API v0` 时）；无管理员权限会提示拔插 |

改了 `_tools/f407tool.py` 后重打包：`python _tools/build_exe.py`。exe 自带 Python 运行时 + pyserial，可脱离本机 venv。

### SWD 接线（杜邦 4 根 + 可选 NRST）

| ST-Link | 板排针（看丝印） |
|---|---|
| SWDIO | PA13 |
| SWCLK | PA14 |
| GND | GND |
| 3.3V | 3V3（**调试/烧录时的唯一电源，此时必须拔掉 Type-C**） |
| NRST（第 5 脚，可选但强烈建议） | NRST |

`openocd/f407vet6.cfg` 当前 = `reset_config none` + **300kHz**（杜邦线实证稳定值已固化进 cfg，所有入口——bat/flash.sh/CLion——自动继承；想提速命令行 `-c "adapter speed 4000"` 覆盖）。

### GDB 调试

```bash
# 终端 A：起 gdb server（保持运行）
"E:/zwork/dev-toolkit/tools/openocd/xpack-openocd-0.12.0-7/bin/openocd.exe" \
  -f openocd/f407vet6.cfg -c "adapter speed 300" -c "reset_config none"
# 终端 B：
"E:/zwork/dev-toolkit/tools/arm-none-eabi-gcc/xpack-arm-none-eabi-gcc-14.2.1-1.1/bin/arm-none-eabi-gdb.exe" \
  build/f407.elf -ex "target remote localhost:3333" -ex "monitor reset halt" -ex "break main" -ex "c"
```

或 `f407.exe gdb`（`--client` 会自动再拉起 gdb 客户端）。注意：gdb server 与烧录命令互斥（都占 ST-Link），别同时跑。

---

## 2. 硬件事实清单（软件视角必读）

| 项 | 事实 |
|---|---|
| MCU | STM32F407VET6：512K Flash / 128K SRAM1+16K SRAM2 / 64K CCMRAM（链接脚本含 CCM 段） |
| LED | PE2~PE5 = LED1~LED4，**3V3→LED→1k→引脚，低电平点亮**（宏在 `Core/Inc/main.h`） |
| 按键 | SW1=BOOT0（按下拉到 3V3）/ SW2=NRST（按下拉到 GND）/ SW3=PA0（拉到 3V3）；各配 10k 下拉/上拉 |
| 复位 | NRST：R10 10k 上拉 3V3 + C22 100nF + SW2 |
| 时钟 | **X2 8MHz(HSE) 实测不起振（HSERDY 恒 0）→ 系统实际跑 HSI-PLL≈168.25MHz**；名义值 SystemCoreClock=168MHz（差 ~1.5‰，UART 可忽略）。X1 32.768kHz(LSE) 实测**正常起振**（LSIRDY 2.5s 置位）。两晶振默认都没启用，固件里按需开 |
| UART | USART1：PA9=TX / PA10=RX → 板载 CH340N。**CH340 的 USB 线网只在 H1 排针（1=GND,2=USB_D-,3=USB_D+），与 Type-C 完全无关** |
| USB 原生 | Type-C D± → PA11(DM)/PA12(DP)（OTG_FS）。**枚举有未决疑案，见 §6** |
| 电源 | Type-C → CH213K(0.5A 限流，**已飞线直通绕过**) → +5V → SY8089 → 3V3。调试时改由 ST-Link 3.3V 线供电（Type-C 必须拔） |
| SWD 引脚 | PA13=SWDIO / PA14=SWCLK（排针引出，**不是**专用座） |
| BOOT | BOOT0 10k 下拉 → 默认 Flash 启动；进 ROM DFU：**拔线→按住 SW1→插线→1 秒后松开**（BOOT0 在上电瞬间采样） |

---

## 3. 这块板子踩过的三大坑（为什么它曾经"全黑"）

新对话**不要重新怀疑**这些已定案的结论，也不要回头改：

1. **`sysmem.c:21` 把 `_estack` 当值用**（应为 `&_estack`）→ 首句 printf 的堆分配读 `0x20020000`（RAM 顶外一字节）→ BusFault 升级 HardFault → **固件每次死于开机第 101ms**，死在 LED 初始化之后、点灯之前 → 症状=全黑。已修复（commit `9664d50`）。教训：链接脚本符号要取地址。
2. **堆/栈抠太小**（512B/1K）→ 已改 4K/4K（`linker/STM32F407VETX_FLASH.ld`）。
3. **CH213K 0.5A 限流 vs 上电浪涌**：限流触发→+5V 塌→buck 欠压→死循环（VO=0.3V、芯片烫）。**已飞线直通绕过**（整板 ~150mA ≪ USB 500mA，安全）。虚焊/短路判决均已作废，**禁再提补焊 CH213K**。
4. （新 HAL 特有）官方仓库自带 `*_template.c` 与工程实现重复定义 → CMake GLOB 已排除（`_template[.]c$`），别删这条过滤。

**供电与 SWD 的强关联**（多次"连不上/冻结"的真因）：
- **双电源共轨**（Type-C + ST-Link 3.3V 同时接）→ 地环路噪声 → SWD 哑掉。调试期只留一个电源。
- 杜邦线供电曾塌陷（RCC_CSR 的 **BORRSTF=1** 欠压实锤）→ 症状=运行十几秒后整机冻结、uwTick 卡死、CPU 停在 HAL_Delay 等一个永不前进的 tick。线松/接触抖 = 一切间歇性怪象的第一嫌疑。

---

## 4. 软件调试军火库（今晚全部实战验证过的套路）

### 4.1 免 halt 内存采样（最稳的观测方式）

**日常直接用 `f407.exe probe`（核心在 `_tools/probe.py`）**：自动 nm 解析 uwTick 地址 → read_memory 采样 uwTick+GPIOE IDR×6 → 输出 tick 速率/灯位轮转/RCC_CSR 复位标志/判定（2026-11-17 真机验证：1012 拍/秒+四灯轮转+BOR 史全报对）。想看连续行为用 \407.exe watch\（同一 openocd 会话每 200ms 采样，一行刷新 tick 速率与 ●/○ 灯位，Ctrl+C 出统计）。手敲命令是它的退化版，留作备用：

halt/resume 循环偶尔会弄断 SWD 会话；**纯 mem2array 采样不碰核**，稳定：

```tcl
# openocd 单会话采样任意变量/寄存器（示例：uwTick + GPIOE IDR，每秒一次×6）
openocd -f openocd/f407vet6.cfg -c "adapter speed 300" -c "init" -c "
proc mon {} { for {set i 0} {\$i < 6} {incr i} {
  mem2array t 32 0x200000d0 1; mem2array u 32 0x40021010 1
  echo \"t\$i=[format 0x%08X \$t(0)] idr\$i=[format 0x%08X \$u(0)]\"; sleep 1000 } }; mon" \
-c "shutdown"
```

- **IDR 解码**（GPIOE=0x40021010，低电平=灯亮）：`0x38`=PE2 亮、`0x34`=PE3、`0x2C`=PE4、`0x1C`=PE5
- **uwTick 地址随构建漂移**：探针前先 `arm-none-eabi-nm build/f407.elf | grep uwTick`（旧构建 0x200000cc，新构建 0x200000d0）

### 4.2 时钟/复位状态取证（判断"芯片为什么不跑"）

**自动化版：`f407.exe clock`**（免 halt 读 RCC_CR/CFGR/CSR，直接判定 HSE 是否起振、PLL 是否锁定、当前 SYSCLK 源、BOR/PIN/SFT 复位史）。下面手敲命令是它的退化版，留作没有 exe 时备用：

```bash
openocd ... -c "init" -c "halt" \
  -c "echo CR=[mdw 0x40023800]" \      # RCC_CR: bit16 HSEON bit17 HSERDY bit24 PLLON bit25 PLLRDY
  -c "echo CFGR=[mdw 0x40023808]" \    # SWS[3:2]: 2=PLL 在跑
  -c "echo CSR=[mdw 0x40023874]" \     # 复位标志: bit25 BORRST=欠压史! bit26 PINRST bit28 SFTRST
  -c "echo ST=[mdw 0xE000E010]" \      # SysTick CTRL: 0x7=使能+中断+核时钟
  -c "shutdown"
```

- **uwTick 冻结 + SysTick CTRL=0x7 + CPU 在 HAL_GetTick** = 停表了（电源塌陷签名，查线）
- HAL_Delay 里 tickstart/wait 都正常却永不退出 = tick 停表

### 4.3 HardFault 现场取证

```bash
# halt 后：reg msp → 基本帧在 [msp+0x18]=出错PC、[msp+0x14]=LR（注意：若用过 FPU 是扩展帧，偏移会移）
# 再 addr2line：
"E:/zwork/.../arm-none-eabi-addr2line.exe" -e build/f407.elf -f <出错PC>
```

实战案例：死在 `_sbrk_r`（`_sbrk` 的判堆语句）= 堆问题；死在 `Reset_Handler` = 可能只是自己 reset halt 按停的伪象，**不能当"固件卡在启动"的证据**。

### 4.4 排查分诊树（固件"不跑/卡住"标准流程）

1. 3V3 电压？（C8 电容上，≈3.3V）→ 供电问题先排除
2. NRST ≈3.3V？（C22 上）→ 0V = 被摁死在复位
3. BOOT0 按住时 = 3.3V？（SW1 焊盘）→ 0V = BOOT0 链断，进不了 DFU
4. 断电量目标引脚对地电阻（≈0Ω=短路/引脚伤）
5. 以上全过仍不动 → halt（**不按复位**）读真 PC + addr2line，看卡在哪一行
6. openocd 报 `STLINK V0J8S0 (API v0)` / `init mode failed` → ST-Link 被强杀打哑了，**拔插 USB**（或 `f407.exe usbreset`）；先 `f407.exe kill-stlink` 确认没有残留 openocd

### 4.5 探针三纪律

- `echo a=[mdw ...]` 一次只能带**一个** mdw（多值炸 usage）；跑着的核用 `mem2array` 采样
- openocd 没有 `reg ipsr`（IPSR 从 xpsr 低 9 位解）；halt 一个"睡眠/未知态"的核会报 `target was in unknown state`
- **halt 冻结中的核读到的是尸体状态**——别把"halt 瞬间的 PC"当"程序卡在那一行"的证据

---

## 5. 当前固件行为与 printf 可见性

- `main.c`：HAL_Init → SystemClock_Config（**先试 HSE 8MHz→168MHz，失败自动回退 HSI-PLL 168MHz**；当前 X2 坏，实跑 HSI，`f407.exe clock` 可见 HSERDY=0 / PLLSRC=HSI）→ GPIO → UART1 → 打印 boot 横幅（含 build id）→ 流水灯循环（每步 `printf("[flow] LED%u (PE%u)\r\n")`）
- printf 已 retarget 到 USART1 @115200 8N1（PA9），物理出口 = CH340N → **H1 排针**。想让电脑看到打印：拿一根 USB 线改接 H1（D+/D-/GND 三根）→ 电脑出 CH340 COM 口 → `f407.exe ports`（列 COM）/ `f407.exe monitor`（miniterm）。**不接 H1 时 printf 照常执行（每步 ~1.7ms），只是没人能听见**
- 想换时间基准/ clocks：`SystemClock_Config` 的顺序是「OscConfig(HSE) 失败 → OscConfig(HSI) → ClockConfig(PLL)」。这个顺序本身是安全的（切换 SYSCLK 之前完成），HSE 修好后会自动升级到 168.000MHz。**危险的是在 PLL 已当系统时钟时再做 OscConfig**（旧版 HardFault 的真因），别把回退逻辑挪到 ClockConfig 之后

---

## 6. 未决事项（按优先级）

| # | 事项 | 状态 | 下一步 |
|---|---|---|---|
| 1 | **LED1(PE2) 不亮** | 固件已实证驱动 PE2（IDR=0）；2026-11-17 重烧后探针再次采到 PE2 相位（IDR=0x38）→ 固件侧无责，断点在硬件段 | 断电电阻档量 **R11 两端**（≈1kΩ 好 / OL 补焊换件）。注意：表笔点亮 LED 的测试**绕过 R11**，别拿它当 R11 的通行证 |
| 2 | **Type-C USB 枚举疑案** | 设备侧就绪（DFU 曾枚出），症状随插头方向变 → 嫁疑=A面 D± 互换 + B面(B6/B7)未接 | 终审=断电通断档：A6↔PA12、B6↔PA12、A7↔PA11、B7↔PA11 应全通，A6↔A7 应不通；互换/半接→座侧四飞线理正（A6→PA12/A7→PA11/B6→PA12/B7→PA11）。修好后 Type-C DFU 烧录可用（`f407.exe typec`，进 DFU=拔线按 SW1 插线） |
| 3 | X2 8MHz 晶振不起振 | 不阻塞任何现有功能（固件已做 HSE→HSI 自动回退，`f407.exe clock` 实证 HSERDY=0） | ①烙铁润 X2+C3/C4 焊点 → 跑 `f407.exe clock` 看 HSERDY ②不行换同封装 8MHz 晶振→再测。**想认真玩 USB 才需要修**（FS USB 时钟精度 ±0.25%，HSI ±1% 超差） |
| 4 | 供电长期可靠性 | 历史 BOR 来自 11-16 杜邦线供电；2026-11-17 17:0x 用 `f407.exe clock --clear` 清零后，ST-Link 3.3V 供电连跑 2 分钟+，RCC_CSR 保持 0、tick 1014/秒 → 当前这条电源路径没有再掉压 | 日常运行建议 Type-C 直通供电；调试才换 ST-Link 供电。换电源路径后用同一招复测：`clock --clear` → 跑一段 → `probe` 看 BORRST 是否回来 |

---

## 7. 后续嵌入式开发指引

### 7.1 加新外设的标准流程（例：加 TIM2 PWM）

1. `Core/Inc/stm32f4xx_hal_conf.h`：取消注释/确认 `#define HAL_TIM_MODULE_ENABLED`（当前 48 模块**全启用**，通常不用动；GLOB 会自动编译新启用的模块）
2. `Core/Inc/main.h` + `Core/Src/main.c`：加 `MX_TIM2_Init()` 并在 main 调用；MSP 回调加时钟使能
3. 构建 → 烧录 → 灯/示波验证。**换 HAL/链接脚本后必须 `rm build/f407.elf` 强制重链**（ninja 不追踪 .ld 改动）

### 7.2 时钟使用须知（这板子特有）

- **真实主频 ≈168.25MHz**（HSI 实际 16.09MHz × PLL），`SystemCoreClock` 变量=168000000 名义值 → HAL_Delay/UART 波特率误差 ~1.5‰，115200 下无感
- **HSE 当前起不来**（X2 坏）：不能在应用层写 `while(!HSERDY)` 死等（会挂死）。允许在 `SystemClock_Config` 里「先试 HSE、失败回退 HSI」，但必须整体在 `HAL_RCC_ClockConfig(SYSCLK=PLL)` **之前**完成；在 PLL 已当系统时钟后再 OscConfig 就是旧版 HardFault 的原样复现。改频率时 HSE/HSI 两条分支的 PLLM/PLLN/PLLP 要一起对上（当前 HSE=8/336/2、HSI=16/336/2，都是 168MHz）
- USB 需要精确 48MHz：修好 X2 后 PLLSRC=HSE 才合规

### 7.3 UART/串口调试

- 物理出口三选一：①H1 飞线 USB（CH340 出 COM）②ST-Link 克隆的 VCP？**本板没有**（SWD 未引出 VCP）③SWD 半托管 + 停点打印（gdb 里看）
- 当前 miniterm 参数：115200 8N1（`f407.exe monitor`，pyserial 已打包进 exe）

### 7.4 HAL 升级/更换

三个官方源仓库（均 depth-1 克隆即可，校园网直连 GitHub 实测可用，失败重试 + `--connect-timeout 15`）：
1. `STMicroelectronics/STM32F4xx_HAL_Driver`（Inc/Src）
2. `STMicroelectronics/cmsis_device_f4`（Device F4：stm32f407xx.h、system、gcc startup）
3. `STMicroelectronics/STM32CubeF4`（只要 `Drivers/CMSIS/Include`；注意其 HAL_Driver/CMSIS-Device 是 gitlink 子模块，主仓库里没有源码）

更新后必查：conf 模板差异、`*_template.c` 排除规则仍生效、`HSE_VALUE=8M` 仍在、GLOB 文件集。

### 7.5 工程纪律（本仓库约定）

- bat 工具箱由 `_tools/gen_bats.py` 生成（GBK+CRLF），**改 bat 必须重跑脚本**，别直接编辑；Git Bash 里中文乱码 = 显示问题，非文件损坏
- 交付物/文档用 UTF-8（本文件）；`.cmd/.bat` 用 GBK。日常入口是根目录 `f407.exe`，`_tools/gen_bats.py` 现在生成到 `_tools/legacy_bats/`（不再往根目录堆文件）
- `CMakeLists.txt.clion-stub.bak` = CLion 原生成壳，留作纪念可删
- git：改完就 commit（夜间多会话接力，commit 是唯一可靠的时间线）

---

## 8. 新对话接手指南（给 AI 看）

1. 先读本文件；细节史在 ZCode 记忆库 `f407-hal-project.md`
2. 动手前跑一遍"分诊树"（§4.4）确认板子活着：LED 在流水 = 一切正常
3. 不要重新审判已定案件：CH213K 虚焊论（三换片恒定症状否决）、"晶振两颗都坏"（X1 实测正常）、"固件卡在 Reset_Handler"（reset halt 伪象）、"Type-C 插上就该有 CH340 串口"（CH340 与 Type-C 无关）
4. 一切现场结论用仪器读数闭环（IDR/CR/CSR/栈帧），不猜
