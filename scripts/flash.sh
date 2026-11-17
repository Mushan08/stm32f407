#!/usr/bin/env bash
# 命令行烧录：Git Bash 里 ./scripts/flash.sh，或 CLion External Tool 调用
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOL_ROOT="${F407_TOOLCHAIN:-$ROOT/toolchain}"
OPENOCD="$TOOL_ROOT/tools/openocd/xpack-openocd-0.12.0-7/bin/openocd.exe"
cd "$ROOT"
exec "$OPENOCD" -f openocd/f407vet6.cfg -c "adapter speed 300" -c "reset_config none" \
  -c "program build/f407.elf verify reset exit"
