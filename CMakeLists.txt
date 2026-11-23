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
    Core/Src/oled.c
    Core/Src/cat_gif.c
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

# 产物：.hex / .bin + 尺寸报告；并按 51 工程惯例收纳进工程根 hex/ 文件夹
# （主固件归 hex/f407/，实验归 hex/exp/<源目录>/，一程序一文件夹，stflash 递归扫描）
set(F407_HEX_DIR ${CMAKE_CURRENT_SOURCE_DIR}/hex)
set(F407_MAIN_HEX_DIR ${F407_HEX_DIR}/f407)
file(MAKE_DIRECTORY ${F407_MAIN_HEX_DIR})
add_custom_command(TARGET ${PROJECT_NAME}.elf POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -Oihex    ${PROJECT_NAME}.elf ${PROJECT_NAME}.hex
    COMMAND ${CMAKE_OBJCOPY} -Obinary  ${PROJECT_NAME}.elf ${PROJECT_NAME}.bin
    COMMAND ${CMAKE_SIZE}    ${PROJECT_NAME}.elf
    COMMAND ${CMAKE_COMMAND} -E copy_if_different ${PROJECT_NAME}.elf ${F407_MAIN_HEX_DIR}
    COMMAND ${CMAKE_COMMAND} -E copy_if_different ${PROJECT_NAME}.hex ${F407_MAIN_HEX_DIR}
    COMMAND ${CMAKE_COMMAND} -E copy_if_different ${PROJECT_NAME}.bin ${F407_MAIN_HEX_DIR}
    WORKING_DIRECTORY $<TARGET_FILE_DIR:${PROJECT_NAME}.elf>
    VERBATIM
)

# ---------------------------------------------------------------- exp 实验区
# 51 工程惯例移植：exp/ 下新建 .c 就自动出固件，完全不用改本文件。
#
#   exp/led.c（带 main）    = 程序  -> hex/exp/led.hex（路径跟随源目录结构）
#   exp/timer.c（不带 main）= 私有模块 -> 只链给同目录的程序
#   exp/lib/*.c             = 共享模块 -> 链进每一个程序（51 的 lib\ 架构）
#   HAL 库全部源文件都挂进每个程序，没被调用的函数由 --gc-sections 自动剪掉，
#   所以"裸寄存器实验"和"HAL 实验"各得其所（led.c 仅 740B 的原因）。
#
# 和 51 版的差异只有一处：Keil 要手工区分共享模块防止向量冲突（L104），
# gcc+gc-sections 不存在这个问题——链接器按引用链裁剪，lib 没被调用就剪光，
# 同一个 lib 模块被多个程序各链各的副本，互不干扰。
file(GLOB_RECURSE EXP_ALL_C CONFIGURE_DEPENDS
    ${CMAKE_CURRENT_SOURCE_DIR}/exp/*.c)
# CONFIGURE_DEPENDS 只管"文件增删"；把每个 .c 登记成配置依赖，
# 文件内容变了（比如后来才把 main 写上去）也会触发重新分类。
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${EXP_ALL_C})

# 共享模块：exp/lib/*.c 链进每一个程序（51 的 lib\ 语义）
file(GLOB EXP_SHARED_MODULES CONFIGURE_DEPENDS
    ${CMAKE_CURRENT_SOURCE_DIR}/exp/lib/*.c)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${EXP_SHARED_MODULES})

# lib 里不能放带 main() 的文件——它会被链进每一个程序，main 冲突
foreach(mod IN LISTS EXP_SHARED_MODULES)
    file(READ "${mod}" _text)
    if(_text MATCHES "(^|\n)[ \t]*(int|void|char)[ \t]+main[ \t]*\\(")
        message(FATAL_ERROR "${mod} 里带 main()。lib\\ 只放共享模块，程序请放到 exp/ 下。")
    endif()
endforeach()

set(EXP_PROGRAMS "")
set(EXP_PRIVATE_MODULES "")
foreach(f IN LISTS EXP_ALL_C)
    # hex/ 是产物目录永远不算源码；exp/lib/ 已由共享 GLOB 单独管理
    if(f MATCHES "/hex/" OR f MATCHES "/lib/")
        continue()
    endif()
    # 0 字节的 .c（新建了还没写内容）什么都不算
    file(SIZE "${f}" _fsize)
    if(_fsize EQUAL 0)
        message(STATUS "跳过空文件（0 字节）：${f}")
        continue()
    endif()
    file(READ "${f}" _text)
    if(_text MATCHES "(^|\n)[ \t]*(int|void|char)[ \t]+main[ \t]*\\(")
        list(APPEND EXP_PROGRAMS "${f}")
    else()
        list(APPEND EXP_PRIVATE_MODULES "${f}")
    endif()
endforeach()

# 私有模块必须和带 main 的程序同目录，否则永远编不到——直接报错说清楚
foreach(mod IN LISTS EXP_PRIVATE_MODULES)
    get_filename_component(_mdir "${mod}" DIRECTORY)
    set(_found FALSE)
    foreach(pr IN LISTS EXP_PROGRAMS)
        get_filename_component(_pdir "${pr}" DIRECTORY)
        if(_pdir STREQUAL _mdir)
            set(_found TRUE)
        endif()
    endforeach()
    if(NOT _found)
        get_filename_component(_mn "${mod}" NAME)
        message(FATAL_ERROR
            "${_mdir}/${_mn} 里没有 main()，且所在目录没有任何带 main() 的程序。"
            "请在同目录放一个程序，或给它写上 main。")
    endif()
endforeach()

# 两个程序不能同名，否则 hex 互相覆盖
set(_seen_names "")
foreach(src IN LISTS EXP_PROGRAMS)
    get_filename_component(_n "${src}" NAME_WE)
    if(_n IN_LIST _seen_names)
        message(FATAL_ERROR "有两个程序都叫 ${_n}.c（在不同目录），hex 会互相覆盖，请改名。")
    endif()
    list(APPEND _seen_names "${_n}")
endforeach()

foreach(src IN LISTS EXP_PROGRAMS)
    get_filename_component(name "${src}" NAME_WE)
    # hex 目录结构 = 源文件目录结构：exp/led.c -> hex/exp/led.hex
    file(RELATIVE_PATH _rel "${CMAKE_CURRENT_SOURCE_DIR}" "${src}")
    get_filename_component(_reldir "${_rel}" DIRECTORY)
    if(_reldir)
        set(_hexdir "${F407_HEX_DIR}/${_reldir}")
    else()
        set(_hexdir "${F407_HEX_DIR}")
    endif()
    file(MAKE_DIRECTORY "${_hexdir}")

    # 程序 = 它自己 + 同目录私有模块 + exp/lib/ 共享模块 + HAL 全家（gc 自动剪）
    #      + 启动文件 + 系统初始化
    get_filename_component(_dir "${src}" DIRECTORY)
    set(_tgt "exp_${name}")
    set(_units "${src}" ${EXP_SHARED_MODULES})
    foreach(mod IN LISTS EXP_PRIVATE_MODULES)
        get_filename_component(_mdir "${mod}" DIRECTORY)
        if(_mdir STREQUAL _dir)
            list(APPEND _units "${mod}")
        endif()
    endforeach()

    add_executable(${_tgt}.elf ${_units} ${HAL_SOURCES}
        Drivers/CMSIS/Device/ST/STM32F4xx/Source/Templates/gcc/startup_stm32f407xx.s
        Drivers/CMSIS/Device/ST/STM32F4xx/Source/system_stm32f4xx.c)
    target_include_directories(${_tgt}.elf PRIVATE
        Core/Inc
        ${CMAKE_CURRENT_SOURCE_DIR}/exp/lib   # 共享头文件（#include "delay.h" 直接写）
        ${CMAKE_CURRENT_BINARY_DIR}   # build/build_info.h（构建身份）
        Drivers/STM32F4xx_HAL_Driver/Inc
        Drivers/CMSIS/Include
        Drivers/CMSIS/Device/ST/STM32F4xx/Include)
    add_dependencies(${_tgt}.elf build_info)

    add_custom_command(TARGET ${_tgt}.elf POST_BUILD
        COMMAND ${CMAKE_OBJCOPY} -Oihex    ${_tgt}.elf ${name}.hex
        COMMAND ${CMAKE_OBJCOPY} -Obinary  ${_tgt}.elf ${name}.bin
        COMMAND ${CMAKE_SIZE}    ${_tgt}.elf
        COMMAND ${CMAKE_COMMAND} -E copy_if_different ${_tgt}.elf ${_hexdir}/${name}.elf
        COMMAND ${CMAKE_COMMAND} -E copy_if_different ${name}.hex ${_hexdir}
        COMMAND ${CMAKE_COMMAND} -E copy_if_different ${name}.bin ${_hexdir}
        WORKING_DIRECTORY $<TARGET_FILE_DIR:${_tgt}.elf>
        VERBATIM)
endforeach()
