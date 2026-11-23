#ifndef MAIN_H
#define MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32f4xx_hal.h"

/* 板载 LED（原理图 罗彬_F407 P1，2026-11-15 版确认）：
 * LED1~LED4 = PE2~PE5，接法 3V3 -> LED -> 1k -> 引脚，低电平点亮 */
#define LED_GPIO_CLK_ENABLE() __HAL_RCC_GPIOE_CLK_ENABLE()
#define LED_GPIO_PORT         GPIOE
#define LED_PIN_1             GPIO_PIN_2
#define LED_PIN_2             GPIO_PIN_3
#define LED_PIN_3             GPIO_PIN_4
#define LED_PIN_4             GPIO_PIN_5
#define LED_ALL_PINS          (LED_PIN_1 | LED_PIN_2 | LED_PIN_3 | LED_PIN_4)
#define LED_ON(pin)           HAL_GPIO_WritePin(LED_GPIO_PORT, (pin), GPIO_PIN_RESET)
#define LED_OFF(pin)          HAL_GPIO_WritePin(LED_GPIO_PORT, (pin), GPIO_PIN_SET)

/* 板载按键 SW3 = PA0：外部 10k 下拉，按下接 3V3（读 1） */
#define BUTTON_GPIO_CLK_ENABLE() __HAL_RCC_GPIOA_CLK_ENABLE()
#define BUTTON_GPIO_PORT         GPIOA
#define BUTTON_PIN               GPIO_PIN_0

void Error_Handler(void);

#ifdef __cplusplus
}
#endif

#endif /* MAIN_H */
