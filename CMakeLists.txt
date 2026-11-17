cmake_minimum_required(VERSION 3.20)

# 工具链必须在 project() 之前确定（命令行 -DCMAKE_TOOLCHAIN_FILE 或 presets 传入，此处兜底）
set(CMAKE_TOOLCHAIN_FILE "${CMAKE_CURRENT_SOURCE_DIR}/cmake/stm32f407.cmake" CACHE FILEPATH "")

project(f407 C ASM)

set(CPU_FLAGS -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

add_compile_options(${CPU_FLAGS}
    -ffunction-sections
    -fdata-sections
    -Wall
    -fno-strict-aliasing
)
add_compile_definitions(STM32F407xx)

add_compile_options($<$<CONFIG:Debug>:-O0>)
add_compile_options($<$<CONFIG:Debug>:-g3>)
add_compile_options($<$<CONFIG:Release>:-Os>)
add_compile_options($<$<CONFIG:Release>:-g3>)

add_link_options(${CPU_FLAGS}
    -Wl,--gc-sections
    -Wl,--no-warn-rwx-segments
    -Wl,--print-memory-usage
    -T${CMAKE_CURRENT_SOURCE_DIR}/linker/STM32F407VETX_FLASH.ld
    --specs=nano.specs
    --specs=nosys.specs
    -Wl,-Map=${PROJECT_NAME}.map,--cref
)

# 全量编译 HAL .c（每个文件都被 #ifdef HAL_xxx_MODULE_ENABLED 保护，
# 未启用的模块编译为空 TU，故以后在 stm32f4xx_hal_conf.h 开关模块无需改本文件）
file(GLOB HAL_SOURCES CONFIGURE_DEPENDS
    ${CMAKE_CURRENT_SOURCE_DIR}/Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal*.c)
# 排除 timebase 二选一模板（与 stm32f4xx_hal.c 的弱定义 HAL_InitTick 冲突；默认用 SysTick 方案）
list(FILTER HAL_SOURCES EXCLUDE REGEX "_template[.]c$")

set(PROJECT_SOURCES
    Core/Src/main.c
    Core/Src/stm32f4xx_it.c
    Core/Src/stm32f4xx_hal_msp.c
    Core/Src/syscalls.c
    Core/Src/sysmem.c
    Drivers/CMSIS/Device/ST/STM32F4xx/Source/system_stm32f4xx.c
    Drivers/CMSIS/Device/ST/STM32F4xx/Source/Templates/gcc/startup_stm32f407xx.s
)

add_executable(${PROJECT_NAME}.elf ${PROJECT_SOURCES} ${HAL_SOURCES})

target_include_directories(${PROJECT_NAME}.elf PRIVATE
    Core/Inc
    ${CMAKE_CURRENT_BINARY_DIR}   # build/build_info.h（构建身份）
    Drivers/STM32F4xx_HAL_Driver/Inc
    Drivers/CMSIS/Include
    Drivers/CMSIS/Device/ST/STM32F4xx/Include
)

# 构建身份（git 短哈希 -dirty + 时间戳）→ build/build_info.h，main.c 开机横幅打印。
# 夜间多会话接力的“板子上跑的是哪个构建”从此一眼可辨（串口/strings 都能看）。
find_package(Git QUIET)

# 配置阶段先生成一份：CLion/clangd 在“还没构建过”时也能解析 build_info.h，
# 否则 main.c 的 #include "build_info.h" 和 BUILD_ID/BUILD_TIME 会一直报红。
# 构建阶段再由下面的 build_info 目标刷新（哈希/时间戳保持最新）。
execute_process(
    COMMAND ${CMAKE_COMMAND}
            -DOUT=${CMAKE_CURRENT_BINARY_DIR}/build_info.h
            -DGIT_EXEC=${GIT_EXECUTABLE}
            -DSRC_DIR=${CMAKE_CURRENT_SOURCE_DIR}
            -P ${CMAKE_CURRENT_SOURCE_DIR}/cmake/gen_build_info.cmake
    RESULT_VARIABLE _build_info_rc)
if(NOT _build_info_rc EQUAL 0)
    message(WARNING "build_info.h 生成失败（rc=${_build_info_rc}）：CLion 里 BUILD_ID/BUILD_TIME 会报红")
endif()

add_custom_target(build_info
    BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/build_info.h"
    COMMAND ${CMAKE_COMMAND}
            -DOUT=${CMAKE_CURRENT_BINARY_DIR}/build_info.h
            -DGIT_EXEC=${GIT_EXECUTABLE}
            -DSRC_DIR=${CMAKE_CURRENT_SOURCE_DIR}
            -P ${CMAKE_CURRENT_SOURCE_DIR}/cmake/gen_build_info.cmake
    COMMENT "生成构建身份 build_info.h"
    VERBATIM)
add_dependencies(${PROJECT_NAME}.elf build_info)

# 产物：.hex / .bin + 尺寸报告
add_custom_command(TARGET ${PROJECT_NAME}.elf POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -Oihex    ${PROJECT_NAME}.elf ${PROJECT_NAME}.hex
    COMMAND ${CMAKE_OBJCOPY} -Obinary  ${PROJECT_NAME}.elf ${PROJECT_NAME}.bin
    COMMAND ${CMAKE_SIZE}    ${PROJECT_NAME}.elf
    WORKING_DIRECTORY $<TARGET_FILE_DIR:${PROJECT_NAME}.elf>
    VERBATIM
)
