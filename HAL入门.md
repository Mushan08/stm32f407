# STM32 HAL 库入门（对着本工程讲）

> 目标：看完能自己在这个工程里加一个外设，知道每一步在干嘛、错了去哪查。
> 不抄手册，所有例子都能在本仓库里找到对应代码。

---

## 0. HAL 到底是什么

STM32 的每个外设（串口、定时器、GPIO…）本质上是一堆**寄存器**。直接写寄存器要记几百个地址和位定义。

HAL（Hardware Abstraction Layer）是 ST 官方写的一层函数库，把这些寄存器操作包成：

```c
HAL_GPIO_WritePin(GPIOE, GPIO_PIN_2, GPIO_PIN_RESET);   // 点灯
HAL_UART_Transmit(&huart1, buf, len, timeout);          // 发串口
HAL_Delay(300);                                          // 延时 300ms
```

**代价**：比直接写寄存器慢、代码大一点。
**好处**：不用背寄存器、换芯片系列时改动小、出错有统一返回值。

一句话：**HAL 是扳手，不是螺丝。** 你还是要懂“拧哪颗螺丝”（引脚、时钟、模式），只是不用自己造扳手。

---

## 1. 本工程里 HAL 在哪

```
stm32f407/
├── Drivers/
│   ├── STM32F4xx_HAL_Driver/
│   │   ├── Inc/                 ← 所有 HAL 头文件（函数声明、结构体、宏）
│   │   └── Src/                 ← 所有 HAL 实现（想看内部就翻这里）
│   └── CMSIS/
│       ├── Include/             ← 内核相关（NVIC、SysTick、__disable_irq 等）
│       └── Device/ST/STM32F4xx/ ← 芯片寄存器定义（GPIOE、RCC 这些名字从这来）
├── Core/
│   ├── Inc/
│   │   ├── main.h
│   │   ├── stm32f4xx_hal_conf.h ← HAL 的“开关面板”
│   │   └── stm32f4xx_it.h
│   └── Src/
│       ├── main.c               ← 你的业务代码 + MX_xxx_Init()
│       ├── stm32f4xx_hal_msp.c  ← 外设的底层初始化（时钟、引脚、中断）
│       ├── stm32f4xx_it.c       ← 中断服务函数
│       └── syscalls.c           ← printf 重定向
└── CMakeLists.txt               ← 用 GLOB 把所有 HAL .c 自动编进来
```

### 开关面板：stm32f4xx_hal_conf.h

里面是一排这样的宏：

```c
#define HAL_GPIO_MODULE_ENABLED
#define HAL_UART_MODULE_ENABLED
...
```

本工程 **48 个模块全部打开**（HANDOFF §7.1 有说明），所以加外设时通常**不用动这个文件**。
只有极少数情况（比如官方新加的模块）才需要确认对应 `#define` 在不在。

> 如果关掉某个模块，对应 `HAL_xxx_Init` 会变成未定义 → 链接报错。这是“模块开关没开”的典型症状。

### 编译方式：GLOB + 排除模板

`CMakeLists.txt` 里：

```cmake
file(GLOB HAL_SOURCES CONFIGURE_DEPENDS Drivers/STM32F4xx_HAL_Driver/Src/*.c)
list(FILTER HAL_SOURCES EXCLUDE REGEX "_template[.]c$")
```

- `GLOB`：把 HAL 源码目录下所有 `.c` 都编进来，不用一个个写
- `CONFIGURE_DEPENDS`：新增/删除文件时 cmake 会自动重新扫描
- 排除 `*_template.c`：官方仓库里这些模板和正式实现重复定义，不排会报 multiple definition

**这条排除规则别删**（HANDOFF §3.4）。

### 本工程不用 CubeMX

没有 `.ioc` 文件。`MX_GPIO_Init()` 这些函数是**手写的**，只是照着 CubeMX 的风格命名。
所以你改外设时不用“回 CubeMX 重新生成”，直接改 `main.c` / `stm32f4xx_hal_msp.c` 就行。

---

## 2. 一个外设的标准五步

不管 GPIO、UART、TIM、ADC，套路都是这五步。拿本工程的 **USART1** 当例子：

### 第 1 步：开时钟（在 MSP 里）

芯片上每个外设默认是断电的，用之前要开时钟：

```c
__HAL_RCC_USART1_CLK_ENABLE();
__HAL_RCC_GPIOA_CLK_ENABLE();   // 用到的 GPIO 端口也要开
```

> 忘了这一步的症状：初始化返回 `HAL_ERROR`，或者寄存器读出来全是 0。

### 第 2 步：填 Init 结构体（在 main.c）

```c
static void MX_USART1_UART_Init(void)
{
    huart1.Instance          = USART1;
    huart1.Init.BaudRate     = 115200;
    huart1.Init.WordLength   = UART_WORDLENGTH_8B;
    huart1.Init.StopBits     = UART_STOPBITS_1;
    huart1.Init.Parity       = UART_PARITY_NONE;
    huart1.Init.Mode         = UART_MODE_TX_RX;
    huart1.Init.HwFlowCtl    = UART_HWCONTROL_NONE;
    huart1.Init.OverSampling = UART_OVERSAMPLING_16;
    if (HAL_UART_Init(&huart1) != HAL_OK)
    {
        Error_Handler();
    }
}
```

`huart1` 是全局的“句柄”（handle）：里面存着外设寄存器地址、配置、当前状态。
**一个外设一个句柄**，别在函数里定义成局部变量。

### 第 3 步：HAL_xxx_Init 内部会回调 MSP

`HAL_UART_Init()` 做两件事：

1. 按结构体配置寄存器
2. 调用 `HAL_UART_MspInit(&huart1)` —— 这个函数在 `stm32f4xx_hal_msp.c`，由**你**实现

本工程的 MSP 长这样：

```c
void HAL_UART_MspInit(UART_HandleTypeDef *huart)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    if (huart->Instance == USART1)
    {
        __HAL_RCC_USART1_CLK_ENABLE();
        __HAL_RCC_GPIOA_CLK_ENABLE();

        /* PA9 = TX, PA10 = RX（AF7），板载 CH340N 直连 */
        GPIO_InitStruct.Pin       = GPIO_PIN_9 | GPIO_PIN_10;
        GPIO_InitStruct.Mode      = GPIO_MODE_AF_PP;
        GPIO_InitStruct.Pull      = GPIO_PULLUP;
        GPIO_InitStruct.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
        GPIO_InitStruct.Alternate = GPIO_AF7_USART1;
        HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);
    }
}
```

**MSP = MCU Support Package**，就是“这个外设在这个板子上具体接哪、用什么时钟”。
它是弱函数（`__weak`），你不写也能编译，但引脚不会初始化 → 外设当然不工作。

### 第 4 步：调用 API 干活

```c
HAL_UART_Transmit(&huart1, (uint8_t *)"hello\r\n", 7, 0xFFFF);  // 阻塞发送
HAL_GPIO_WritePin(GPIOE, GPIO_PIN_2, GPIO_PIN_RESET);           // 点灯
HAL_Delay(300);                                                  // 延时
```

### 第 5 步：检查返回值

```c
if (HAL_UART_Transmit(&huart1, buf, len, 100) != HAL_OK) {
    // 超时 / 忙 / 参数错
}
```

返回值只有四种：`HAL_OK` / `HAL_ERROR` / `HAL_BUSY` / `HAL_TIMEOUT`。
具体错因看 `huart1.ErrorCode`。

---

## 3. 三个必须懂的机制

### 3.1 SysTick 与 HAL_Delay（为什么 Delay 会被“停表”卡死）

`HAL_Init()` 里会配置 SysTick 每 1ms 中断一次，中断里只做一件事：

```c
// stm32f4xx_it.c
void SysTick_Handler(void)
{
    HAL_IncTick();          // uwTick++
}
```

`HAL_Delay(300)` 本质是：

```c
uint32_t start = HAL_GetTick();          // 读 uwTick
while (HAL_GetTick() - start < 300) { }  // 等 tick 涨 300
```

**所以：**

- 如果 SysTick 中断被关掉（`__disable_irq()`）→ tick 不涨 → `HAL_Delay` 永远不返回
- 如果供电塌了、芯片停表 → 同样卡死
- 本工程的 `Error_Handler()` 里先 `__disable_irq()`，所以里面**只能用忙等循环**，不能用 `HAL_Delay`

这就是为什么板子“灯不转、tick=0”时，第一嫌疑是供电（HANDOFF §3）。

### 3.2 回调函数（弱函数）

HAL 里大量函数是 `__weak` 的空实现，比如：

```c
__weak void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart) { }
```

你在自己代码里写一个**同名函数**，链接器就会用你的版本：

```c
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1) {
        // 收到一个字节了
    }
}
```

常见回调：

| 回调 | 什么时候进 |
|---|---|
| `HAL_UART_TxCpltCallback` | 中断/DMA 发送完成 |
| `HAL_UART_RxCpltCallback` | 收到指定长度 |
| `HAL_TIM_PeriodElapsedCallback` | 定时器更新（溢出） |
| `HAL_GPIO_EXTI_Callback` | 外部中断 |
| `HAL_ADC_ConvCpltCallback` | ADC 转换完成 |

**注意**：回调是在中断上下文里执行的，里面别 `HAL_Delay`、别做长事、别打印一大串。

### 3.3 中断怎么写（以定时器为例）

三件套：

1. 外设里允许中断：`HAL_TIM_Base_Start_IT(&htim6);`
2. NVIC 打开：`HAL_NVIC_EnableIRQ(TIM6_DAC_IRQn);`（MSP 里做）
3. `stm32f4xx_it.c` 里写中断入口，转给 HAL：

```c
void TIM6_DAC_IRQHandler(void)
{
    HAL_TIM_IRQHandler(&htim6);
}
```

然后 HAL 会清标志、调你的 `HAL_TIM_PeriodElapsedCallback`。

**别忘了第 3 步**：只开中断不写入口，程序会跑到默认的死循环 `Default_Handler`。

---

## 4. 实战：加一个 1Hz 定时器（完整可编译）

选 **TIM6**：基本定时器，没有输出引脚，不会和板子上任何东西冲突，最适合练手。

### 4.1 目标

每 1 秒进一次中断，在回调里翻转 LED1（PE2）。

### 4.2 main.c 里加句柄和初始化

```c
/* 文件顶部，和 huart1 放一起 */
TIM_HandleTypeDef htim6;

static void MX_TIM6_Init(void)
{
    TIM_ClockConfigTypeDef sClockSourceConfig = {0};
    TIM_MasterConfigTypeDef sMasterConfig = {0};

    htim6.Instance = TIM6;
    htim6.Init.Prescaler         = 8400 - 1;   /* 84MHz / 8400 = 10kHz */
    htim6.Init.CounterMode       = TIM_COUNTERMODE_UP;
    htim6.Init.Period            = 10000 - 1;  /* 10kHz / 10000 = 1Hz */
    htim6.Init.ClockDivision     = TIM_CLOCKDIVISION_DIV1;
    htim6.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    if (HAL_TIM_Base_Init(&htim6) != HAL_OK)
    {
        Error_Handler();
    }

    sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
    if (HAL_TIM_ConfigClockSource(&htim6, &sClockSourceConfig) != HAL_OK)
    {
        Error_Handler();
    }

    sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
    sMasterConfig.MasterSlaveMode     = TIM_MASTERSLAVEMODE_DISABLE;
    if (HAL_TIMEx_MasterConfigSynchronization(&htim6, &sMasterConfig) != HAL_OK)
    {
        Error_Handler();
    }
}
```

在 `main()` 里、`MX_GPIO_Init()` 之后调用：

```c
MX_TIM6_Init();
HAL_TIM_Base_Start_IT(&htim6);   /* 启动并允许更新中断 */
```

### 4.3 MSP 里开时钟和中断

`stm32f4xx_hal_msp.c` 追加：

```c
void HAL_TIM_Base_MspInit(TIM_HandleTypeDef *htim)
{
    if (htim->Instance == TIM6)
    {
        __HAL_RCC_TIM6_CLK_ENABLE();
        HAL_NVIC_SetPriority(TIM6_DAC_IRQn, 5, 0);
        HAL_NVIC_EnableIRQ(TIM6_DAC_IRQn);
    }
}
```

> 优先级数字越小越高。SysTick 是 15（最低），所以 5 的定时器能打断 `HAL_Delay`。

### 4.4 中断入口 + 回调

`stm32f4xx_it.c`：

```c
extern TIM_HandleTypeDef htim6;

void TIM6_DAC_IRQHandler(void)
{
    HAL_TIM_IRQHandler(&htim6);
}
```

`main.c` 里写回调：

```c
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
    if (htim->Instance == TIM6)
    {
        HAL_GPIO_TogglePin(GPIOE, GPIO_PIN_2);
    }
}
```

### 4.5 编译、烧录、验证

```powershell
cd C:\Users\MushanLuo\CLionProjects\stm32f407
.\f407.exe flash        # 编译 + 烧录
.\f407.exe watch        # 看 LED1 每 2 秒亮灭一次（翻转 1Hz = 周期 2 秒）
```

看到 `●1` 和 `○1` 交替、其他灯不动，就成功了。

### 4.6 想改成 PWM？（选引脚前先查原理图）

PWM 的套路一样，只是多两件事：

- 引脚要配成复用功能（`GPIO_MODE_AF_PP` + `GPIO_AFx_TIMx`）
- 在 MSP 里调 `HAL_TIM_PWM_ConfigChannel()` / `HAL_TIM_PWM_Start()`

**本板已知被占用的脚**（HANDOFF §2）：PA9/PA10（串口）、PA11/PA12（USB）、PA13/PA14（SWD）、PA0（按键）、PE2~PE5（LED）、NRST/BOOT0。
选 PWM 脚之前先看原理图，别和这些撞。

---

## 5. 常见坑（按出现频率排）

| 症状 | 大概率原因 | 处理 |
|---|---|---|
| 编译报 `undefined reference to HAL_xxx_Init` | `hal_conf.h` 里模块没开 | 打开对应 `#define HAL_XXX_MODULE_ENABLED` |
| 初始化返回 `HAL_ERROR` | 忘了开外设时钟 | MSP 里补 `__HAL_RCC_xxx_CLK_ENABLE()` |
| 初始化成功但引脚没反应 | MSP 没写 / 引脚配错 | 检查 `Mode`、`Alternate`、端口时钟 |
| 中断不进 | 没 `EnableIRQ` / 没写 IRQHandler | 补 NVIC 和 `it.c` 入口 |
| 程序卡在 `HAL_Delay` | 中断被关 / tick 停了 | 查 `__disable_irq`、供电、SysTick |
| `HAL_BUSY` | 上一次传输还没完 | 等回调或加状态机，别硬重发 |
| printf 没输出 | CH340 没接 / 没初始化 UART | `f407.exe ports` + `monitor`，见本板文档 |
| printf 打 `%f` 是空白 | newlib-nano 默认不带浮点 | 链接加 `-u _printf_float`，或自己格式化 |
| 一进中断就 HardFault | 栈溢出 / 回调里干了重活 | 加大栈、把活挪回主循环 |
| 改了 `.ld` 没生效 | ninja 不追踪链接脚本 | `f407.exe build --relink` |

---

## 6. 怎么查 HAL（比问人快）

1. **看头文件注释**：`Drivers/STM32F4xx_HAL_Driver/Inc/stm32f4xx_hal_uart.h`
   每个函数上面都有参数说明和“怎么用”的注释。
2. **看实现**：`Src/stm32f4xx_hal_uart.c`，比如想知道 `HAL_UART_Transmit` 超时怎么算的，直接搜函数名。
3. **看结构体定义**：`UART_InitTypeDef` 有哪些字段，头文件里列得清清楚楚。
4. **看参考手册**：RM0090（F407 参考手册），寄存器级细节。
5. **看数据手册**：引脚复用表（哪个脚能当 USART1_TX）、电气参数。
6. **对照 CubeMX 生成的工程**：网上随便生成一个同芯片工程，看它怎么写 MSP/Init，抄结构不抄内容。

---

## 7. 本工程的 printf 是怎么通的

`syscalls.c` 里重定向了 `_write`：

```c
static int __io_putchar(int ch)
{
    uint8_t c = (uint8_t)ch;
    HAL_UART_Transmit(&huart1, &c, 1, 0xFFFF);
    return ch;
}

ssize_t _write(int fd, const void *buf, size_t len)
{
    for (size_t i = 0; i < len; i++) {
        __io_putchar(((const char *)buf)[i]);
    }
    return (ssize_t)len;
}
```

所以 `printf` 的每个字符都会**阻塞**发一次串口（115200 下约 87µs/字节）。
一行 30 字符 ≈ 2.6ms。这也是为什么流水灯每步只打一行还能保持 300ms 节奏，但**别在高频循环里 printf**。

另外，`printf` 第一次调用会向堆要缓冲区，本工程堆给了 4KB（`_Min_Heap_Size`）。
早期堆只有 512B 时，第一句 printf 就把栈顶写穿 → HardFault（HANDOFF §3.1 的著名案件）。

---

## 8. 练习清单（由易到难）

1. **改流水灯节奏**：把 `HAL_Delay(300)` 改成 100，`watch` 看速率变化。
2. **加一个 1Hz 定时器**：照第 4 节做，`watch` 验证 LED1 独立闪烁。
3. **串口回显**：开 `HAL_UART_Receive_IT`，在 `HAL_UART_RxCpltCallback` 里把收到的字符原样发回去。
4. **按键控制**：PA0（SW3）配成输入，按下时切流水灯方向。
5. **PWM 呼吸灯**：选一个空闲脚 + 定时器通道，`HAL_TIM_PWM_Start`，改占空比。

每做完一个，先 `f407.exe build` 确认没警告，再 `flash` + `watch`/`monitor` 验证，别攒着。

---

## 9. 一句话总结

**HAL 的套路永远是：开时钟 → 填结构体 → Init → MSP 配引脚 → 调 API → 查返回值。**
中断再多两步：NVIC 打开、`it.c` 写入口。
剩下的都是查头文件。
