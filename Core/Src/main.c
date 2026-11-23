#include "main.h"
#include "oled.h"
#include "cat_gif.h"
#include <stdio.h>

/* 呼吸流水灯（软件 PWM，单灯轮转）：
 *   TIM6 每 50µs 中断一次（20kHz），内部计数 0~99 做 100 级软件 PWM，
 *   直接在 PE2~PE5 上推高低电平（低电平点亮）。
 *   同一时刻只有一盏灯在呼吸：亮度 0→100→0，其余三盏占空比 0（全黑）。
 *   每盏 32 步 × 25ms = 0.8s，四盏一轮 3.2s。
 */
#define BREATH_STEPS     64
#define SLOT_STEPS       32
#define PHASE_MASK       127
#define BREATH_PERIOD_MS 25
#define PWM_STEPS        100

/* 扩展板 8 路灯 D0~D7：默认接 PD0~PD7（网标 D0=PD0 ... D7=PD7）。
 * 实际接线若不同，只改这里的三行。 */
#define LED8_GPIO_CLK_ENABLE() __HAL_RCC_GPIOD_CLK_ENABLE()
#define LED8_GPIO_PORT         GPIOD
static const uint16_t led8_pins[8] = {
    GPIO_PIN_0, GPIO_PIN_1, GPIO_PIN_2, GPIO_PIN_3,
    GPIO_PIN_4, GPIO_PIN_5, GPIO_PIN_6, GPIO_PIN_7,
};

static void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_BUTTON_Init(void);
static void MX_LED8_Init(void);
static void MX_TIM6_Init(void);
static void MX_USART1_UART_Init(void);
static void report_status(uint8_t phase, uint16_t flow_phase, uint8_t flow_on, uint8_t btn);

TIM_HandleTypeDef htim6;
UART_HandleTypeDef huart1;

static volatile uint8_t pwm_tick;
static volatile uint8_t pwm_duty_e[4];   /* PE2~PE5 */
static volatile uint8_t pwm_duty_d[8];   /* PD0~PD7 */
static volatile uint8_t  g_breath_phase;  /* 由 TIM6 每 25ms 推进 */
static volatile uint16_t g_flow_phase;
static volatile uint8_t  g_flow_on = 1;
static uint16_t pwm_div;                  /* 50µs 计数，满 500 = 25ms */

/* 64 点余弦表：0 → 100 → 0，线性映射到 100 级占空比 */
static const uint8_t breath_tab[BREATH_STEPS] = {
      0,   0,   1,   2,   4,   6,   8,  11,
     15,  18,  22,  26,  31,  35,  40,  45,
     50,  55,  60,  65,  69,  74,  78,  82,
     85,  89,  92,  94,  96,  98,  99, 100,
    100, 100,  99,  98,  96,  94,  92,  89,
     85,  82,  78,  74,  69,  65,  60,  55,
     50,  45,  40,  35,  31,  26,  22,  18,
     15,  11,   8,   6,   4,   2,   1,   0,
};

/* 当前相位只有一盏灯有占空比，其余归零 */
static void breath_step(uint8_t phase)
{
    uint8_t slot  = (phase >> 5) & 3;      /* 32 步一盏 */
    uint8_t local = phase & (SLOT_STEPS - 1);

    for (uint8_t i = 0; i < 4; i++)
    {
        pwm_duty_e[i] = (i == slot) ? breath_tab[(local << 1) & (BREATH_STEPS - 1)] : 0;
    }
}

/* D0~D7 单灯呼吸轮转：当前这一盏 0→100→0，其余全 0 */
static void flow_step(uint16_t phase)
{
    uint8_t slot  = (phase >> 5) & 7;      /* 32 步一盏 */
    uint8_t local = phase & (SLOT_STEPS - 1);

    for (uint8_t i = 0; i < 8; i++)
    {
        pwm_duty_d[i] = (i == slot) ? breath_tab[(local << 1) & (BREATH_STEPS - 1)] : 0;
    }
}

int main(void)
{
    uint8_t btn_last = 0;
    uint32_t last_toggle = 0;
    uint32_t last_report = 0;
    uint8_t anim_idx = 0;
    uint32_t last_anim = 0;

    HAL_Init();
    SystemClock_Config();
    MX_USART1_UART_Init();
    MX_GPIO_Init();
    MX_BUTTON_Init();
    MX_LED8_Init();
    MX_TIM6_Init();

    OLED_Init();
    OLED_DrawFrame(cat_frames[0], 32);     /* 64×64 居中 */
    OLED_RefreshArea(32, 64);

    flow_step(0);                 /* 上电从 D0 开始呼吸 */
    printf("\r\n[boot] F407 breathing flow\r\n");

    while (1)
    {
        uint32_t now = HAL_GetTick();
        uint8_t btn = (HAL_GPIO_ReadPin(BUTTON_GPIO_PORT, BUTTON_PIN) == GPIO_PIN_SET);

        /* 按下沿 + 200ms 锁存：SW3 只管 D0~D7，默认开 */
        if (btn && !btn_last && (now - last_toggle) > 200U)
        {
            g_flow_on = !g_flow_on;
            last_toggle = now;
            printf("[btn] D0-D7 %s\r\n", g_flow_on ? "ON" : "OFF");
        }
        btn_last = btn;

        /* OLED 动画：21 帧，60ms/帧，循环播放 */
        if (now - last_anim >= cat_frame_ms)
        {
            last_anim = now;
            OLED_DrawFrame(cat_frames[anim_idx], 32);
            OLED_RefreshArea(32, 64);
            anim_idx++;
            if (anim_idx >= cat_frame_count)
            {
                anim_idx = 0;
            }
        }

        /* 每秒上报一次状态 */
        if (now - last_report >= 1000U)
        {
            last_report = now;
            report_status(g_breath_phase, g_flow_phase, g_flow_on, btn);
        }

        HAL_Delay(1);   /* LED 节拍由 TIM6 驱动，这里只让出 CPU */
    }
}

static void SystemClock_Config(void)
{
    RCC_OscInitTypeDef RCC_OscInitStruct = {0};
    RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

    __HAL_RCC_PWR_CLK_ENABLE();
    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

    /* 先试 HSE 8MHz（X2 晶振，2026-11-17 修复后实测起振）：8/8=1M -> N336 -> P2 = 168MHz */
    RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
    RCC_OscInitStruct.HSEState = RCC_HSE_ON;
    RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
    RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
    RCC_OscInitStruct.PLL.PLLM = 8;
    RCC_OscInitStruct.PLL.PLLN = 336;
    RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
    RCC_OscInitStruct.PLL.PLLQ = 7;

    if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
    {
        /* 晶振起振失败（焊点回退保险丝）：回退 HSI 16MHz，16/16=1M -> 同样 168MHz */
        RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
        RCC_OscInitStruct.HSEState = RCC_HSE_OFF;
        RCC_OscInitStruct.HSIState = RCC_HSI_ON;
        RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
        RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
        RCC_OscInitStruct.PLL.PLLM = 16;
        if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
        {
            Error_Handler();
        }
    }

    RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK
                                | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
    RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
    RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;  /* 42MHz */
    RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;  /* 84MHz */
    if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK)
    {
        Error_Handler();
    }
}

static void MX_GPIO_Init(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    LED_GPIO_CLK_ENABLE();

    /* 初始全灭：低电平点亮，输出高即灭 */
    HAL_GPIO_WritePin(LED_GPIO_PORT, LED_ALL_PINS, GPIO_PIN_SET);
    GPIO_InitStruct.Pin   = LED_ALL_PINS;
    GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull  = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(LED_GPIO_PORT, &GPIO_InitStruct);
}

static void MX_BUTTON_Init(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    BUTTON_GPIO_CLK_ENABLE();
    GPIO_InitStruct.Pin  = BUTTON_PIN;
    GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
    GPIO_InitStruct.Pull = GPIO_NOPULL;   /* SW3 已带 10k 下拉 */
    HAL_GPIO_Init(BUTTON_GPIO_PORT, &GPIO_InitStruct);
}

static void MX_LED8_Init(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    LED8_GPIO_CLK_ENABLE();
    for (uint8_t i = 0; i < 8; i++)
    {
        pwm_duty_d[i] = 0;                /* 先全灭，避免上电闪一下 */
    }
    GPIO_InitStruct.Pin   = GPIO_PIN_0 | GPIO_PIN_1 | GPIO_PIN_2 | GPIO_PIN_3
                          | GPIO_PIN_4 | GPIO_PIN_5 | GPIO_PIN_6 | GPIO_PIN_7;
    GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull  = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(LED8_GPIO_PORT, &GPIO_InitStruct);
}

static void MX_TIM6_Init(void)
{
    htim6.Instance = TIM6;
    htim6.Init.Prescaler         = 41;   /* 84MHz / 42 = 2MHz */
    htim6.Init.CounterMode       = TIM_COUNTERMODE_UP;
    htim6.Init.Period            = 99;   /* 2MHz / 100 = 20kHz 中断 */
    htim6.Init.ClockDivision     = TIM_CLOCKDIVISION_DIV1;
    htim6.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
    if (HAL_TIM_Base_Init(&htim6) != HAL_OK)
    {
        Error_Handler();
    }
    if (HAL_TIM_Base_Start_IT(&htim6) != HAL_OK)
    {
        Error_Handler();
    }
}

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

/* 串口状态行：秒数 | PE2~PE5 当前灯与占空比 | D0~D7 开关/当前灯/占空比 | PA0 */
static void report_status(uint8_t phase, uint16_t flow_phase, uint8_t flow_on, uint8_t btn)
{
    uint8_t bslot = (phase >> 5) & 3;
    uint8_t dslot = (flow_phase >> 5) & 7;

    printf("[%lu s] PE%d %u%% | D0-D7 %s",
           (unsigned long)(HAL_GetTick() / 1000U),
           (unsigned)(bslot + 1),
           (unsigned)pwm_duty_e[bslot],
           flow_on ? "ON" : "OFF");

    if (flow_on)
    {
        printf(" D%u %u%%", (unsigned)dslot, (unsigned)pwm_duty_d[dslot]);
    }

    printf(" | PA0=%u\r\n", (unsigned)btn);
}

/* 20kHz 软件 PWM：每 50µs 刷新 4 + 8 路灯脚，100 级 → 200Hz 视觉刷新 */
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
    if (htim->Instance == TIM6)
    {
        static const uint16_t pins_e[4] = {LED_PIN_1, LED_PIN_2, LED_PIN_3, LED_PIN_4};
        uint32_t bsrr_e = 0;
        uint32_t bsrr_d = 0;
        uint8_t t = pwm_tick + 1;

        if (t >= PWM_STEPS)
        {
            t = 0;
        }
        pwm_tick = t;

        for (uint8_t i = 0; i < 4; i++)
        {
            if (t < pwm_duty_e[i])
            {
                bsrr_e |= (uint32_t)pins_e[i] << 16;  /* 低电平点亮 */
            }
            else
            {
                bsrr_e |= pins_e[i];                  /* 高电平熄灭 */
            }
        }
        LED_GPIO_PORT->BSRR = bsrr_e;

        for (uint8_t i = 0; i < 8; i++)
        {
            if (t < pwm_duty_d[i])
            {
                bsrr_d |= (uint32_t)led8_pins[i] << 16;
            }
            else
            {
                bsrr_d |= led8_pins[i];
            }
        }
        LED8_GPIO_PORT->BSRR = bsrr_d;

        /* 每 500 拍（25ms）推进一次呼吸/流水相位，与主循环负载无关 */
        pwm_div++;
        if (pwm_div >= (BREATH_PERIOD_MS * 20U))
        {
            pwm_div = 0;
            breath_step(g_breath_phase);
            g_breath_phase = (g_breath_phase + 1) & PHASE_MASK;

            if (g_flow_on)
            {
                flow_step(g_flow_phase);
                g_flow_phase = (g_flow_phase + 1) & 255;
            }
            else
            {
                for (uint8_t i = 0; i < 8; i++)
                {
                    pwm_duty_d[i] = 0;
                }
            }
        }
    }
}

/* 出错时把灯脚从 PWM 复用抢回普通输出，保证还能看见"全亮" */
static void leds_force_output(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    __HAL_RCC_GPIOE_CLK_ENABLE();
    GPIO_InitStruct.Pin   = LED_ALL_PINS;
    GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull  = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(LED_GPIO_PORT, &GPIO_InitStruct);
}

void Error_Handler(void)
{
    __disable_irq();
    leds_force_output();
    /* 卡死指示：四灯全亮 */
    HAL_GPIO_WritePin(LED_GPIO_PORT, LED_ALL_PINS, GPIO_PIN_RESET);
    while (1)
    {
    }
}
