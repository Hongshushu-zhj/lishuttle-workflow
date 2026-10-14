#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
修改工参 CSV（工程参数表）。

工参表是两行表头：第 1 行中文名，第 2 行英文名。本脚本按列名定位，
中英文都可以，所以不用去数第几列。

用法：
    # 先看看有哪些列可以改
    python scripts/patch_gongcan.py jobs\xxx.csv --list

    # 改几个值，写出新文件（默认不动原文件）
    python scripts/patch_gongcan.py 原文件.csv \
        --set "Physical Cell ID=88" \
        --set "Azimuth (°)=120" \
        --out 新文件.csv

    # 覆盖原文件（会先备份 .bak）
    python scripts/patch_gongcan.py 文件.csv --set "Height (m)=30" --in-place

本脚本是跨平台纯标准库实现，Windows 和 Linux 用的是同一个文件。
"""

import argparse
import csv
import io
import os
import shutil
import sys

# 编码按顺序试：服务器下发的工参表是带 BOM 的 UTF-8，
# 本机的一些表是 GBK。中文最常见的两种都覆盖到了。
ENCODINGS = ("utf-8-sig", "gb18030", "gbk")

# 表头行数：第 1 行中文，第 2 行英文
HEADER_ROWS = 2


def sniff_encoding(path):
    raw = open(path, "rb").read()
    for enc in ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    sys.exit(f"[错误] 无法识别文件编码，试过：{', '.join(ENCODINGS)}\n"
             f"        文件：{path}")


def load(path):
    enc = sniff_encoding(path)
    with open(path, "r", encoding=enc, newline="") as fh:
        text = fh.read()
    # 保留原来的换行风格
    newline = "\r\n" if "\r\n" in text else "\n"
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if len(rows) < HEADER_ROWS:
        sys.exit(f"[错误] 表头不足 {HEADER_ROWS} 行，这看起来不是工参表：{path}")
    return enc, newline, rows


def build_column_map(rows):
    """把中英文列名都映射到列序号，大小写和首尾空格不敏感。"""
    mapping = {}
    for row_idx in range(HEADER_ROWS):
        for col_idx, name in enumerate(rows[row_idx]):
            key = name.strip().lower()
            if key and key not in mapping:
                mapping[key] = col_idx
    return mapping


def find_column(mapping, rows, name):
    key = name.strip().lower()
    if key in mapping:
        return mapping[key]
    # 没找到就给个近似提示，省得来回猜
    close = [n for n in mapping if key and (key in n or n in key)]
    hint = ""
    if close:
        sample = "、".join(sorted(close)[:6])
        hint = f"\n        你是不是想写：{sample}"
    sys.exit(f"[错误] 找不到列名：{name}{hint}\n"
             f"        用 --list 看所有可用列名")


def main():
    ap = argparse.ArgumentParser(
        description="按列名修改工参 CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csvfile", help="工参 CSV 路径")
    ap.add_argument("--list", action="store_true", help="只列出所有列名，不修改")
    ap.add_argument("--set", action="append", default=[], metavar="列名=值",
                    help="要修改的列和值，可以重复多次")
    ap.add_argument("--out", help="输出到新文件（默认行为）")
    ap.add_argument("--in-place", action="store_true",
                    help="覆盖原文件，会先备份为 .bak")
    args = ap.parse_args()

    if not os.path.isfile(args.csvfile):
        sys.exit(f"[错误] 找不到文件：{args.csvfile}")
    if not args.list and not args.set:
        ap.print_help()
        sys.exit("\n[提示] 没指定 --set 也没指定 --list，什么也没做")

    enc, newline, rows = load(args.csvfile)
    mapping = build_column_map(rows)

    if args.list:
        print(f"文件      : {args.csvfile}")
        print(f"编码      : {enc}")
        print(f"总行数    : {len(rows)}（含 {HEADER_ROWS} 行表头）")
        print(f"列数      : {len(rows[0])}")
        print()
        print("可用列名（中文 / 英文）：")
        for i in range(len(rows[0])):
            zh = rows[0][i].strip() if i < len(rows[0]) else ""
            en = rows[1][i].strip() if i < len(rows[1]) else ""
            if zh or en:
                print(f"  [{i:>2}] {zh}  |  {en}")
        return 0

    # ---- 应用修改 ----
    print(f"文件   : {args.csvfile}")
    print(f"编码   : {enc}")
    print(f"数据行 : {len(rows) - HEADER_ROWS}")
    print()
    print("修改内容：")
    for item in args.set:
        if "=" not in item:
            sys.exit(f"[错误] --set 的格式是 列名=值，你给的是：{item}")
        name, value = item.split("=", 1)
        col = find_column(mapping, rows, name)
        changed = 0
        for row_idx in range(HEADER_ROWS, len(rows)):
            row = rows[row_idx]
            if col < len(row) and row[col] != value:
                row[col] = value
                changed += 1
        label = rows[1][col].strip() or rows[0][col].strip()
        print(f"  第 {col} 列 [{label}] -> {value}   （影响 {changed} 行）")

    # ---- 写回 ----
    if args.in_place:
        out_path = args.csvfile
        backup = args.csvfile + ".bak"
        shutil.copy2(args.csvfile, backup)
        print()
        print(f"原文件已备份 : {backup}")
    elif args.out:
        out_path = args.out
    else:
        base, ext = os.path.splitext(args.csvfile)
        out_path = f"{base}.patched{ext}"
        print()
        print("[提示] 没有指定 --out 也没指定 --in-place，写出到新文件")

    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator=newline)
    writer.writerows(rows)
    with open(out_path, "w", encoding=enc, newline="") as fh:
        fh.write(buf.getvalue())

    print(f"已写出       : {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
