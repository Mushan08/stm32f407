# -*- coding: utf-8 -*-
"""从 STMicroelectronics/STM32CubeF4 (raw.githubusercontent.com) 拉取 HAL/CMSIS 源码。
先下载到 _hal_cache 隔离目录，校验后归位到 Drivers/。404 的外围模块自动跳过并报告。
"""
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import concurrent.futures as cf

REPO = "STMicroelectronics/STM32CubeF4"
BRANCH = "master"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "_hal_cache")

# 多源轮询：gitee 国内镜像最稳（zhengqijun/STM32CubeF4）；raw 时通时断；jsDelivr 整库服务不了超大 repo
SOURCES = [
    "https://gitee.com/zhengqijun/STM32CubeF4/raw/master/",
    "https://raw.githubusercontent.com/%s/%s/" % (REPO, BRANCH),
    "https://gcore.jsdelivr.net/gh/%s@%s/" % (REPO, BRANCH),
]

# CMSIS core（core_cm4.h 只引用这四个）
CMSIS_INC = [
    "cmsis_version.h", "cmsis_compiler.h", "cmsis_gcc.h", "mpu_armv7.h", "core_cm4.h",
]
# HAL Inc / Src 基名（stm32f4xx_<base>.h / .c）
HAL_INC_BASES = [
    "hal", "hal_def", "hal_adc", "hal_adc_ex", "hal_can", "hal_cec", "hal_crc",
    "hal_cortex", "hal_cryp", "hal_cryp_ex", "hal_dac", "hal_dac_ex", "hal_dcmi",
    "hal_dsi", "hal_dma", "hal_dma_ex", "hal_dma2d", "hal_eth", "hal_flash",
    "hal_flash_ex", "hal_flash_ramfunc", "hal_fmpi2c", "hal_fmpi2c_ex", "hal_gpio",
    "hal_hash", "hal_hash_ex", "hal_hcd", "hal_i2c", "hal_i2c_ex", "hal_i2s",
    "hal_i2s_ex", "hal_irda", "hal_iwdg", "hal_lptim", "hal_ltdc", "hal_ltdc_ex",
    "hal_mmc", "hal_nand", "hal_nor", "hal_pccard", "hal_pcd", "hal_pcd_ex",
    "hal_pwr", "hal_pwr_ex", "hal_qspi", "hal_rcc", "hal_rcc_ex", "hal_rng",
    "hal_rtc", "hal_rtc_ex", "hal_sai", "hal_sai_ex", "hal_sd", "hal_sd_ex",
    "hal_sdram", "hal_smartcard", "hal_smbus", "hal_spdifrx", "hal_spi",
    "hal_sram", "hal_tim", "hal_tim_ex", "hal_uart", "hal_usart", "hal_wwdg",
]
HAL_SRC_BASES = [b for b in HAL_INC_BASES if b not in ("hal_def",)]

DEVICE_FILES = [
    "Drivers/CMSIS/Device/ST/STM32F4xx/Include/stm32f4xx.h",
    "Drivers/CMSIS/Device/ST/STM32F4xx/Include/stm32f407xx.h",
    "Drivers/CMSIS/Device/ST/STM32F4xx/Include/system_stm32f4xx.h",
    "Drivers/CMSIS/Device/ST/STM32F4xx/Source/system_stm32f4xx.c",
    "Drivers/CMSIS/Device/ST/STM32F4xx/Source/Templates/gcc/startup_stm32f407xx.s",
    "Drivers/STM32F4xx_HAL_Driver/Templates/stm32f4xx_hal_conf_template.h",
]

FILES = []
FILES += ["Drivers/CMSIS/Include/" + n for n in CMSIS_INC]
FILES += ["Drivers/STM32F4xx_HAL_Driver/Inc/stm32f4xx_%s.h" % b for b in HAL_INC_BASES]
FILES += ["Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_%s.c" % b for b in HAL_SRC_BASES]
FILES += DEVICE_FILES


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "f407-hal-setup/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def valid_content(data):
    if not data:
        return "empty"
    head = data[:64]
    if b"404: Not Found" in head:
        return "404-body"
    if b"<html" in head.lower() or b"<!DOCTYPE html" in head.lower():
        return "html-error"
    if len(data) < 20:
        return "too-small"
    return None


def fetch_one(rel):
    dst = os.path.join(CACHE, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    last_err = None
    for attempt in range(3):
        if attempt:
            time.sleep(0.5 * attempt)
        for base in SOURCES:
            try:
                data = http_get(base + rel)
                err = valid_content(data)
                if err:
                    last_err = err
                    continue
                with open(dst, "wb") as f:
                    f.write(data)
                return (rel, None)
            except urllib.error.HTTPError as e:
                last_err = "HTTP %d" % e.code
            except Exception as e:
                last_err = str(e)
    return (rel, last_err)


def main():
    if os.path.isdir(CACHE):
        shutil.rmtree(CACHE)
    os.makedirs(CACHE, exist_ok=True)

    print("[total] %d files" % len(FILES))
    results = []
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(fetch_one, FILES))

    ok = [r for r, e in results if e is None]
    missing = [(r, e) for r, e in results if e is not None]
    print("[done] ok=%d missing=%d" % (len(ok), len(missing)))
    for rel, err in missing:
        print("  MISS %-72s (%s)" % (rel, err))

    # 核心文件必须存在
    core = [
        "Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal.c",
        "Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_rcc.c",
        "Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_gpio.c",
        "Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_uart.c",
        "Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_cortex.c",
        "Drivers/CMSIS/Include/core_cm4.h",
        "Drivers/CMSIS/Device/ST/STM32F4xx/Include/stm32f407xx.h",
        "Drivers/CMSIS/Device/ST/STM32F4xx/Source/Templates/gcc/startup_stm32f407xx.s",
    ]
    missing_core = [c for c in core if c not in ok]
    if missing_core:
        print("[FATAL] 核心文件缺失:")
        for c in missing_core:
            print("  " + c)
        sys.exit(1)

    copied = 0
    for rel in ok:
        src = os.path.join(CACHE, rel.replace("/", os.sep))
        dst = os.path.join(ROOT, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    print("[install] copied %d files into Drivers/" % copied)
    print("[cache] kept at %s" % CACHE)


if __name__ == "__main__":
    main()
