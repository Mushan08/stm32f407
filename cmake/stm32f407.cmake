# STM32F407VET6 交叉编译工具链（xpack arm-none-eabi-gcc 14.2.1，不依赖系统 PATH）
set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)

# 工具链根优先级：环境变量 F407_TOOLCHAIN > 项目内 toolchain/ > 旧 dev-toolkit
set(_repo_root "${CMAKE_CURRENT_LIST_DIR}/..")
if(DEFINED ENV{F407_TOOLCHAIN} AND EXISTS "$ENV{F407_TOOLCHAIN}/tools/arm-none-eabi-gcc")
  set(_tool_root "$ENV{F407_TOOLCHAIN}")
elseif(EXISTS "${_repo_root}/toolchain/tools/arm-none-eabi-gcc/xpack-arm-none-eabi-gcc-14.2.1-1.1/bin/arm-none-eabi-gcc.exe")
  set(_tool_root "${_repo_root}/toolchain")
else()
  set(_tool_root "E:/zwork/dev-toolkit")
  message(WARNING "未找到项目内 toolchain/，回退到 E:/zwork/dev-toolkit；可用 F407_TOOLCHAIN 指定")
endif()

set(TOOLCHAIN_BIN "${_tool_root}/tools/arm-none-eabi-gcc/xpack-arm-none-eabi-gcc-14.2.1-1.1/bin")

set(CMAKE_C_COMPILER   "${TOOLCHAIN_BIN}/arm-none-eabi-gcc.exe")
set(CMAKE_CXX_COMPILER "${TOOLCHAIN_BIN}/arm-none-eabi-g++.exe")
set(CMAKE_ASM_COMPILER "${TOOLCHAIN_BIN}/arm-none-eabi-gcc.exe")
set(CMAKE_AR           "${TOOLCHAIN_BIN}/arm-none-eabi-ar.exe")
set(CMAKE_RANLIB       "${TOOLCHAIN_BIN}/arm-none-eabi-ranlib.exe")
set(CMAKE_OBJCOPY      "${TOOLCHAIN_BIN}/arm-none-eabi-objcopy.exe" CACHE FILEPATH "")
set(CMAKE_OBJDUMP      "${TOOLCHAIN_BIN}/arm-none-eabi-objdump.exe" CACHE FILEPATH "")
set(CMAKE_SIZE         "${TOOLCHAIN_BIN}/arm-none-eabi-size.exe"    CACHE FILEPATH "")

# 调试器（CLion OpenOCD 运行配置 / 命令行 gdb 用）
set(ARM_GDB "${TOOLCHAIN_BIN}/arm-none-eabi-gdb.exe" CACHE FILEPATH "")

set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)
