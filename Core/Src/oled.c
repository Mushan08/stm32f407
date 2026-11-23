#include "oled.h"
#include "main.h"

#define OLED_SCL_PORT   GPIOB
#define OLED_SCL_PIN    GPIO_PIN_6
#define OLED_SDA_PORT   GPIOB
#define OLED_SDA_PIN    GPIO_PIN_7
#define OLED_I2C_ADDR   0x78    /* 0x3C << 1 */

static uint8_t fb[8][128];

/* ---------------- 软件 I2C ---------------- */
static void dly(void)
{
    for (volatile uint32_t i = 0; i < 40; i++)
    {
    }
}

static void scl(int v)
{
    HAL_GPIO_WritePin(OLED_SCL_PORT, OLED_SCL_PIN, v ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

static void sda(int v)
{
    HAL_GPIO_WritePin(OLED_SDA_PORT, OLED_SDA_PIN, v ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

static int sda_read(void)
{
    return HAL_GPIO_ReadPin(OLED_SDA_PORT, OLED_SDA_PIN) == GPIO_PIN_SET;
}

static void i2c_start(void)
{
    sda(1);
    scl(1);
    dly();
    sda(0);
    dly();
    scl(0);
    dly();
}

static void i2c_stop(void)
{
    sda(0);
    dly();
    scl(1);
    dly();
    sda(1);
    dly();
}

static void i2c_write(uint8_t b)
{
    for (uint8_t i = 0; i < 8; i++)
    {
        sda((b & 0x80) != 0);
        b <<= 1;
        dly();
        scl(1);
        dly();
        scl(0);
        dly();
    }
    sda(1);          /* 释放 SDA，收 ACK */
    dly();
    scl(1);
    dly();
    (void)sda_read();
    scl(0);
    dly();
}

/* ---------------- SSD1306 ---------------- */
static void oled_cmd(uint8_t cmd)
{
    i2c_start();
    i2c_write(OLED_I2C_ADDR);
    i2c_write(0x00);        /* 命令流 */
    i2c_write(cmd);
    i2c_stop();
}

static void oled_data(const uint8_t *data, uint16_t len)
{
    i2c_start();
    i2c_write(OLED_I2C_ADDR);
    i2c_write(0x40);        /* 数据流 */
    for (uint16_t i = 0; i < len; i++)
    {
        i2c_write(data[i]);
    }
    i2c_stop();
}

static void oled_gpio_init(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    __HAL_RCC_GPIOB_CLK_ENABLE();
    GPIO_InitStruct.Pin   = OLED_SCL_PIN | OLED_SDA_PIN;
    GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_OD;
    GPIO_InitStruct.Pull  = GPIO_PULLUP;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

    scl(1);
    sda(1);
}

void OLED_Init(void)
{
    static const uint8_t init_seq[] = {
        0xAE,               /* 关显示 */
        0x20, 0x02,         /* 页寻址模式 */
        0xB0, 0xC8, 0x00, 0x10, 0x40,
        0x81, 0xCF,         /* 对比度 */
        0xA1, 0xA6,         /* 左右方向 / 正常显示 */
        0xA8, 0x3F,         /* 复用率 1/64 */
        0xA4,               /* 按 RAM 显示 */
        0xD3, 0x00,         /* 偏移 0 */
        0xD5, 0x80,         /* 时钟分频 */
        0xD9, 0xF1,         /* 预充电 */
        0xDA, 0x12,         /* COM 引脚配置 */
        0xDB, 0x40,         /* VCOMH */
        0x8D, 0x14,         /* 打开电荷泵 */
        0xAF                /* 开显示 */
    };

    oled_gpio_init();
    for (uint16_t i = 0; i < sizeof(init_seq); i++)
    {
        oled_cmd(init_seq[i]);
    }
    OLED_Clear();
    OLED_Refresh();
}

void OLED_Clear(void)
{
    for (uint8_t p = 0; p < 8; p++)
    {
        for (uint8_t x = 0; x < 128; x++)
        {
            fb[p][x] = 0;
        }
    }
}

/* 5x7 字库（只收当前用到的字符，其余显示空格） */
static const uint8_t g_H[5] = {0x7F, 0x08, 0x08, 0x08, 0x7F};
static const uint8_t g_e[5] = {0x38, 0x54, 0x54, 0x54, 0x18};
static const uint8_t g_l[5] = {0x00, 0x41, 0x7F, 0x40, 0x00};
static const uint8_t g_o[5] = {0x38, 0x44, 0x44, 0x44, 0x38};
static const uint8_t g_W[5] = {0x7F, 0x20, 0x18, 0x20, 0x7F};
static const uint8_t g_r[5] = {0x7C, 0x08, 0x04, 0x04, 0x08};
static const uint8_t g_d[5] = {0x38, 0x44, 0x44, 0x48, 0x7F};
static const uint8_t g_sp[5] = {0x00, 0x00, 0x00, 0x00, 0x00};

static const uint8_t *oled_glyph(char c)
{
    switch (c)
    {
        case 'H': return g_H;
        case 'e': return g_e;
        case 'l': return g_l;
        case 'o': return g_o;
        case 'W': return g_W;
        case 'r': return g_r;
        case 'd': return g_d;
        default:  return g_sp;
    }
}

void OLED_ShowString(uint8_t x, uint8_t page, const char *s)
{
    if (page > 7)
    {
        return;
    }

    while (*s != '\0')
    {
        const uint8_t *g = oled_glyph(*s++);
        for (uint8_t i = 0; i < 5 && x < 128; i++)
        {
            fb[page][x++] = g[i];
        }
        if (x < 128)
        {
            fb[page][x++] = 0;   /* 字间距 */
        }
    }
}

void OLED_ClearPage(uint8_t page)
{
    if (page > 7)
    {
        return;
    }
    for (uint8_t x = 0; x < 128; x++)
    {
        fb[page][x] = 0;
    }
}

/* 支持负坐标：跑马灯滚出屏幕左侧时裁掉 */
void OLED_ShowStringAt(int16_t x, uint8_t page, const char *s)
{
    if (page > 7)
    {
        return;
    }

    while (*s != '\0')
    {
        const uint8_t *g = oled_glyph(*s++);
        for (uint8_t i = 0; i < 5; i++, x++)
        {
            if (x >= 0 && x < 128)
            {
                fb[page][x] = g[i];
            }
        }
        if (x >= 0 && x < 128)
        {
            fb[page][x] = 0;   /* 字间距 */
        }
        x++;
    }
}

void OLED_RefreshPage(uint8_t page)
{
    if (page > 7)
    {
        return;
    }
    oled_cmd(0xB0 | page);
    oled_cmd(0x00);
    oled_cmd(0x10);
    oled_data(fb[page], 128);
}

void OLED_Refresh(void)
{
    for (uint8_t p = 0; p < 8; p++)
    {
        OLED_RefreshPage(p);
    }
}

void OLED_DrawFrame(const uint8_t frame[8][64], uint8_t x)
{
    for (uint8_t p = 0; p < 8; p++)
    {
        for (uint8_t i = 0; i < 64; i++)
        {
            if ((uint16_t)x + i < 128)
            {
                fb[p][x + i] = frame[p][i];
            }
        }
    }
}

/* 只刷新 x 起 w 列（8 页），比整屏刷新快一半以上 */
void OLED_RefreshArea(uint8_t x, uint8_t w)
{
    if (x >= 128 || w == 0)
    {
        return;
    }
    if ((uint16_t)x + w > 128)
    {
        w = (uint8_t)(128 - x);
    }

    for (uint8_t p = 0; p < 8; p++)
    {
        oled_cmd(0xB0 | p);
        oled_cmd(0x00 | (x & 0x0F));
        oled_cmd(0x10 | (x >> 4));
        oled_data(&fb[p][x], w);
    }
}
