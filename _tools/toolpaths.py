# -*- coding: utf-8 -*-
"""统一解析工具链位置，优先级：环境变量 > 项目内 toolchain/ > 旧 dev-toolkit。

项目内布局（与 dev-toolkit 一致）：
    toolchain/tools/arm-none-eabi-gcc/xpack-arm-none-eabi-gcc-14.2.1-1.1/bin
    toolchain/tools/cmake/bin
    toolchain/tools/ninja
    toolchain/tools/openocd/xpack-openocd-0.12.0-7/bin

环境变量：
    F407_TOOLCHAIN  显式指定工具链根（其下有 tools/）
    F407_TOOLKIT    同义（兼容旧叫法）
    F407_ROOT       工程根（打包成 exe 时由 f407tool 设置）
"""
import os
import sys

GCC_VER = "xpack-arm-none-eabi-gcc-14.2.1-1.1"
OPENOCD_VER = "xpack-openocd-0.12.0-7"


def repo_root():
    env = os.environ.get("F407_ROOT")
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def roots():
    out = []
    for key in ("F407_TOOLCHAIN", "F407_TOOLKIT"):
        val = os.environ.get(key)
        if val:
            out.append(os.path.abspath(val))
    out.append(os.path.join(repo_root(), "toolchain"))
    out.append(r"E:\zwork\dev-toolkit")
    return out


def resolve(rel):
    """返回第一个存在的候选；都不存在时返回旧默认，便于报错时看到期望路径。"""
    candidates = [os.path.join(root, rel) for root in roots()]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[-1]


def gcc_bin():
    return resolve(os.path.join("tools", "arm-none-eabi-gcc", GCC_VER, "bin"))


def cmake():
    return resolve(os.path.join("tools", "cmake", "bin", "cmake.exe"))


def ninja():
    return resolve(os.path.join("tools", "ninja", "ninja.exe"))


def openocd():
    return resolve(os.path.join("tools", "openocd", OPENOCD_VER, "bin", "openocd.exe"))


def gdb():
    return os.path.join(gcc_bin(), "arm-none-eabi-gdb.exe")


def nm():
    return os.path.join(gcc_bin(), "arm-none-eabi-nm.exe")


def addr2line():
    return os.path.join(gcc_bin(), "arm-none-eabi-addr2line.exe")


def size():
    return os.path.join(gcc_bin(), "arm-none-eabi-size.exe")
