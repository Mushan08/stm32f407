#ifndef OLED_H
#define OLED_H

#include <stdint.h>

/* 0.96" SSD1306 128x64，4 针 I2C：
 *   SCL = PB6, SDA = PB7, 地址 0x3C（写地址 0x78）
 * 软件 I2C，不占用硬件 I2C 外设。 */
void OLED_Init(void);
void OLED_Clear(void);
void OLED_ShowString(uint8_t x, uint8_t page, const char *s);
void OLED_Refresh(void);

/* 跑马灯用：支持负坐标裁剪，单页刷新 */
void OLED_ClearPage(uint8_t page);
void OLED_ShowStringAt(int16_t x, uint8_t page, const char *s);
void OLED_RefreshPage(uint8_t page);

/* 位图动画：frame 为 8 页 × 64 列的 1bpp 数据，画到 x 处并只刷新该区域 */
void OLED_DrawFrame(const uint8_t frame[8][64], uint8_t x);
void OLED_RefreshArea(uint8_t x, uint8_t w);

#endif /* OLED_H */
