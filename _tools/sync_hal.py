# -*- coding: utf-8 -*-
"""对齐 gitee 镜像的 HAL Inc/Src 完整文件清单，补齐本地缺的 .c/.h（不覆盖已有）。"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import concurrent.futures as cf

GITEE_API = "https://gitee.com/api/v5/repos/zhengqijun/STM32CubeF4/contents/"
GITEE_RAW = "https://gitee.com/zhengqijun/STM32CubeF4/raw/master/"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCAN_DIRS = [
    "Drivers/STM32F4xx_HAL_Driver/Inc",
    "Drivers/STM32F4xx_HAL_Driver/Inc/Legacy",
    "Drivers/STM32F4xx_HAL_Driver/Src",
]


def list_dir(path):
    names, page = [], 1
    while True:
        url = "%s%s?per_page=100&page=%d" % (GITEE_API, path, page)
        req = urllib.request.Request(url, headers={"User-Agent": "f407-hal-setup/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        if not isinstance(data, list):
            raise RuntimeError("API 返回异常: %s" % str(data)[:200])
        names += [f["path"] for f in data if f.get("type") == "file"]
        if len(data) < 100:
            break
        page += 1
    return names


def fetch_one(rel):
    dst = os.path.join(ROOT, rel.replace("/", os.sep))
    if os.path.exists(dst) and os.path.getsize(dst) > 20:
        return (rel, None)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        req = urllib.request.Request(GITEE_RAW + rel, headers={"User-Agent": "f407-hal-setup/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        if not data or b"404: Not Found" in data[:64] or b"<html" in data[:64].lower():
            return (rel, "bad content")
        with open(dst, "wb") as f:
            f.write(data)
        return (rel, None)
    except Exception as e:
        return (rel, str(e))


def main():
    remote = []
    for d in SCAN_DIRS:
        items = list_dir(d)
        srcs = [p for p in items if p.endswith((".h", ".c"))]
        print("[api] %s: %d" % (d, len(srcs)))
        remote += srcs

    local = set()
    for d in SCAN_DIRS:
        p = os.path.join(ROOT, d.replace("/", os.sep))
        if os.path.isdir(p):
            local |= {d + "/" + n for n in os.listdir(p) if n.endswith((".h", ".c"))}

    todo = [p for p in remote if p not in local]
    print("[plan] remote=%d local=%d to-fetch=%d" % (len(remote), len(local), len(todo)))
    if not todo:
        print("nothing to do")
        return

    failed = []
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        for rel, err in pool.map(fetch_one, todo):
            if err:
                failed.append((rel, err))
    print("[done] fetched %d, failed %d" % (len(todo) - len(failed), len(failed)))
    for rel, err in failed:
        print("  FAIL %s: %s" % (rel, err))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
