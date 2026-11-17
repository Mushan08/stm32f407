#include "main.h"
static void SystemClock_Config(void);
static void MX_GPIO_Init(void);

/* 流水灯：LED1(PE2) -> LED2(PE3) -> LED3(PE4) -> LED4(PE5)，300ms 一拍，低电平点亮 */
static void led_flow_step(uint8_t idx)
{
    static const uint16_t pins[4] = {LED_PIN_1, LED_PIN_2, LED_PIN_3, LED_PIN_4};

    HAL_GPIO_WritePin(LED_GPIO_PORT, LED_ALL_PINS, GPIO_PIN_SET); /* 全灭（高） */
    HAL_GPIO_WritePin(LED_GPIO_PORT, pins[idx], GPIO_PIN_RESET);  /* 当前亮（低） */
}

int main(void)
{
    uint8_t idx = 0;

    HAL_Init();
    SystemClock_Config();
    MX_GPIO_Init();

    while (1)
    {
        led_flow_step(idx);
        idx = (idx + 1) & 3;
        HAL_Delay(300);
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
    GPIO_InitStruct.Pin = LED_ALL_PINS;
    GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(LED_GPIO_PORT, &GPIO_InitStruct);
}

void Error_Handler(void)
{
    __disable_irq();
    /* 卡死指示：四灯全亮 */
    HAL_GPIO_WritePin(LED_GPIO_PORT, LED_ALL_PINS, GPIO_PIN_RESET);
    while (1)
    {
    }
}
