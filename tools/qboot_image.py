#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (c) 2026, JiChiRen Info. Tech.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the conditions of the BSD-3
# license referenced in the project LICENSE file are met.
#
# This file is part of the Quilla.ZP appliance.
#
"""QBOOT_CHECK 出厂镜像核心（纯标准库，无第三方依赖）。

职责：
  1. 按 quilla 的 QMTL/QMF1 记录格式生成首片 manifest；
  2. 把 QBOOT + META + APP 合成一个从 0x08000000 开始的整片 512 KiB bin；
  3. 校验合成结果（向量表、CRC、SHA-256），供烧录前后自查。

分区（默认布局，与 quilla-qboot-hal.h / keil-qboot-app-build 文档一致；
META 起址与 APP 起址可通过参数/GUI 覆盖，QBOOT 固定于 0x08000000）：
  0x08000000  QBOOT  0x6000  24 KiB（固定）
  0x08006000  META   0x1000   4 KiB (两个 2 KiB slot，记录 256 B)
  0x08007000  APP    0x19000 100 KiB（至 0x08020000 end）

QBOOT_CHECK 的放行条件是：META 中存在合法 manifest（image_len != 0），
且 SHA-256(APP 起址 .. +image_len) 与 manifest.hash 一致。
CHECK 模式不验签、不防回滚，manifest.sig 用 64 字节全 0（与 QIAP END 的
zero_sig 路径一致）。本工具不对安全性作任何超出该机制的声明。

命令行：
  python qboot_image.py pack --boot QBOOT_CHECK.bin --app Project.bin \
                             --out combined.bin [--meta-out meta.bin] [--version 0] \
                             [--meta-base 0x08006000] [--app-start 0x08007000]
  python qboot_image.py verify --image combined.bin \
                               [--meta-base 0x08006000] [--app-start 0x08007000]
  python qboot_image.py selftest
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
import zlib

# ---------------------------------------------------------------- 分区常量
# GD32F502VE: 512 KiB Flash @0x08000000, 64 KiB SRAM @0x20000000.
# QBOOT 的 GD32 构建定义 QUILLA_QBOOT_RAM_SIZE=0x00010000U (64 KiB),
# 这里的 RAM_SIZE 必须与之一致，否则 MSP 合法性校验会用错边界。
# 改芯片时必须同步修改 FLASH_SIZE / APP_SIZE / RAM_SIZE，并同步 QBOOT 侧的
# SOC_FLASH_END、QUILLA_QBOOT_RAM_SIZE、QUILLA_QBOOT_PAGE_SIZE，以及 APP 侧的
# 链接/Zephyr 配置与 META 写入页常量。完整清单见 doc/mcu-porting.zh-CN.md。
FLASH_BASE = 0x08000000
FLASH_SIZE = 0x00080000
QBOOT_SIZE = 0x00006000
META_BASE = 0x08006000
META_OFFSET = META_BASE - FLASH_BASE          # 0x6000
META_SIZE = 0x00001000
APP_START = 0x08007000
APP_OFFSET = APP_START - FLASH_BASE            # 0x7000
APP_SIZE = 0x00079000

RAM_START = 0x20000000
RAM_SIZE = 0x00010000

# META 起址与 APP 起址可由调用方/GUI 覆盖（resolve_layout 校验约束）；
# QBOOT 固定于 FLASH_BASE、占 QBOOT_SIZE，整片长度固定 FLASH_SIZE。
DEFAULT_META_BASE = META_BASE
DEFAULT_APP_START = APP_START

RECORD_SIZE = 256
META_SLOT_SIZE = META_SIZE // 2

# QMTL / QMF1 块布局
META_BLK_MAGIC = 0x514D544C                    # "QMTL"
META_OFF_MAGIC = 0
META_OFF_SEQ = 4
META_OFF_FLAG = 8
META_OFF_FLOOR = 12
META_OFF_SEAL_HASH = 16
META_OFF_SEAL_LEN = 48
META_OFF_CRC = 52

MANI_BLK_MAGIC = 0x514D4631                    # "QMF1"
MANI_BLK_OFF = 64
MANI_BLK_SIZE = 128
MANI_OFF_MAGIC = 0
MANI_OFF_VERSION = 4
MANI_OFF_IMAGE_LEN = 8
MANI_OFF_HASH = 12
MANI_OFF_SIG = 44
MANI_OFF_CRC = 108

FLAG_APP1 = 0x00000001
FLAG_QIAP = 0x00000002
FLAG_QBOOT = 0x00000003

HASH_SIZE = 32
SIG_SIZE = 64


class ImageError(Exception):
    """镜像不合法或校验失败。"""


# ---------------------------------------------------------------- 基础工具
def crc32_ieee(data: bytes) -> int:
    """IEEE 802.3 反射 CRC-32，与 quilla 的 meta_crc32 逐位等价。"""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc >> 1) ^ 0xEDB88320) if (crc & 1) else (crc >> 1)
    return crc ^ 0xFFFFFFFF


def _wr32(buf: bytearray, off: int, value: int) -> None:
    struct.pack_into("<I", buf, off, value & 0xFFFFFFFF)


def _rd32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


# ---------------------------------------------------------------- 输入校验
VARIANT_TAGS = (
    (b"[SEALED]", "SEALED"),
    (b"[SEC]", "SEC"),
    (b"[CHECK]", "CHECK"),
)


def detect_variant(boot: bytes) -> str:
    """从 QBOOT bin 里识别编译变体（banner 变体串，如 'Quilla x.y [CHECK]'）。

    返回 'CHECK' / 'SEALED' / 'SEC' / 'unknown'。Keil 三个 target 共用
    对象目录，切 target 后增量构建可能链接出串变体的产物——文件名叫
    QBOOT_CHECK.bin、内容却是 SEALED。打包前检测可在源头拦住这类事故。
    """
    for tag, name in VARIANT_TAGS:
        if tag in boot:
            return name
    return "unknown"


def validate_boot(boot: bytes) -> tuple[int, int]:
    """校验 QBOOT 镜像大小与向量表，返回 (初始MSP, 复位向量)。"""
    if not boot:
        raise ImageError("QBOOT 镜像为空")
    if len(boot) > QBOOT_SIZE:
        raise ImageError(
            "QBOOT 镜像 %d B 超过分区 %d B（0x6000）"
            % (len(boot), QBOOT_SIZE)
        )
    if len(boot) < 8:
        raise ImageError("QBOOT 镜像不足 8 字节，读不到向量表")
    sp, reset = struct.unpack_from("<II", boot, 0)
    if not (RAM_START <= sp < RAM_START + RAM_SIZE):
        raise ImageError(
            "QBOOT 初始 MSP 0x%08X 不在 RAM [0x%08X, 0x%08X) 内"
            % (sp, RAM_START, RAM_START + RAM_SIZE)
        )
    if not (FLASH_BASE <= reset < FLASH_BASE + QBOOT_SIZE):
        raise ImageError(
            "QBOOT 复位向量 0x%08X 不在 QBOOT 区内" % reset
        )
    return sp, reset


def resolve_layout(meta_base: int | None = None,
                   app_start: int | None = None) -> dict:
    """解析并校验 META/APP 起址布局，返回偏移与 APP 容量。

    约束：QBOOT 固定占 [FLASH_BASE, FLASH_BASE+QBOOT_SIZE)；
    META 区大小固定 META_SIZE；META 与 APP 起址 4 字节对齐；
    APP 区从 app_start 一直延伸到 FLASH 末尾（容量自动推导）。
    """
    meta_base = DEFAULT_META_BASE if meta_base is None else meta_base
    app_start = DEFAULT_APP_START if app_start is None else app_start
    if meta_base % 4 or app_start % 4:
        raise ImageError("META/APP 起址必须 4 字节对齐")
    if not FLASH_BASE + QBOOT_SIZE <= meta_base <= \
            FLASH_BASE + FLASH_SIZE - META_SIZE:
        raise ImageError(
            "META 起址 0x%08X 越界（应在 0x%08X..0x%08X 之间）"
            % (meta_base, FLASH_BASE + QBOOT_SIZE,
               FLASH_BASE + FLASH_SIZE - META_SIZE))
    if app_start < meta_base + META_SIZE:
        raise ImageError(
            "APP 起址 0x%08X 必须不早于 META 区结束 0x%08X"
            % (app_start, meta_base + META_SIZE))
    if app_start >= FLASH_BASE + FLASH_SIZE:
        raise ImageError("APP 起址 0x%08X 超出 FLASH 末尾" % app_start)
    return {
        "meta_base": meta_base,
        "app_start": app_start,
        "app_size": FLASH_BASE + FLASH_SIZE - app_start,
        "meta_offset": meta_base - FLASH_BASE,
        "app_offset": app_start - FLASH_BASE,
    }


def validate_app(app: bytes, app_start: int = APP_START,
                 app_size: int = APP_SIZE) -> tuple[int, int]:
    """校验 APP 镜像大小与向量表，返回 (初始MSP, 复位向量)。

    重点：SP 必须严格小于 RAM 末址。quilla 的
    quilla_qboot_hal_app_image_valid() 把 "SP >= RAM_START + RAM_SIZE"
    判为非法镜像并拒跳 APP；GCC 链接脚本若把 _estack 定义成
    ORIGIN(RAM)+LENGTH(RAM)（0x20004000）会正好踩中这条。
    """
    if not app:
        raise ImageError("APP 镜像为空")
    if len(app) > app_size:
        raise ImageError(
            "APP 镜像 %d B 超过分区 %d B（起址 0x%08X）"
            % (len(app), app_size, app_start)
        )
    if len(app) < 8:
        raise ImageError("APP 镜像不足 8 字节，读不到向量表")
    sp, reset = struct.unpack_from("<II", app, 0)
    if not (RAM_START <= sp < RAM_START + RAM_SIZE):
        raise ImageError(
            "APP 初始 MSP 0x%08X 不在 RAM [0x%08X, 0x%08X) 内；"
            "若等于 0x%08X，检查链接脚本的 _estack"
            % (sp, RAM_START, RAM_START + RAM_SIZE, RAM_START + RAM_SIZE)
        )
    if not (app_start <= reset < app_start + app_size):
        raise ImageError(
            "APP 复位向量 0x%08X 不在 APP 区 [0x%08X, 0x%08X) 内；"
            "检查 IROM / scatter / ld 是否已改到 APP 起址"
            % (reset, app_start, app_start + app_size)
        )
    if (reset & 1) == 0:
        raise ImageError("APP 复位向量 0x%08X 缺少 Thumb 位" % reset)
    return sp, reset


# ---------------------------------------------------------------- META 记录
# SEALED/SEC 出厂签名：复用 quilla 上游的纯标准库 Ed25519 实现
# （quilla/tools/quilla_ed25519_sign.py，RFC 8032，经 7.1 向量自检），
# 避免在本工具里复制第二份曲线实现造成漂移。
_SIGN_TOOL_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "quilla", "tools"))


def _load_sign_tool():
    import sys
    if _SIGN_TOOL_DIR not in sys.path:
        sys.path.insert(0, _SIGN_TOOL_DIR)
    try:
        import quilla_ed25519_sign as ed
    except ImportError as exc:
        raise ImageError(
            "找不到签名模块 quilla_ed25519_sign.py（应在 %s）：%s"
            % (_SIGN_TOOL_DIR, exc))
    return ed


# APP 镜像内的固件安全版本区（quilla-version.h）：
# 偏移 QUILLA_APP_SECVER_OFF=0x400 处 8 字节 = magic "QAV1" + u32 LE version。
SECVER_OFFSET = 0x400
SECVER_MAGIC = 0x31564151                      # "QAV1" 小端读出


def read_secver(app: bytes) -> int:
    """读取 APP 镜像的 secver 版本；magic 不符时抛错。

    SEALED/SEC 变体下 QBOOT 的 SIGN 与启动验版本都依赖该区
    （缺失时设备回 RC_VER / QUILLA_SB_ERR），出厂打包必须在源头拦住。
    """
    if len(app) < SECVER_OFFSET + 8:
        raise ImageError("APP 镜像太短，放不下 secver 区（偏移 0x400）")
    magic, version = struct.unpack_from("<II", app, SECVER_OFFSET)
    if magic != SECVER_MAGIC:
        raise ImageError(
            "APP 镜像偏移 0x400 处 secver magic 不是 \"QAV1\"（0x%08X）——"
            "镜像未包含安全版本区，SEALED/SEC 变体会拒收（QIAP 回 RC_VER）。"
            "请先在 APP 工程加入 .quilla_secver 段再打包"
            % magic)
    if version == 0:
        raise ImageError("APP secver 版本为 0，QBOOT 会视为无效版本（RC_VER）")
    return version


def build_meta_record(
    image_len: int,
    image_hash: bytes,
    version: int = 0,
    seq: int = 1,
    flag: int = FLAG_APP1,
    floor: int = 0,
    sig: bytes | None = None,
    seal_hash: bytes | None = None,
    seal_len: int = 0,
    app_size: int = APP_SIZE,
) -> bytes:
    """生成一条 256 B 的 QMTL + QMF1 首片记录。

    image_hash 必须是对 [APP_START, APP_START+image_len) 的 SHA-256，
    也就是 APP bin 的前 image_len 字节。

    设备端 meta_append() 每条记录都写完整快照（QMTL 的 flag/floor/seal +
    QMF1 的 manifest），因此出厂单条记录带齐 manifest+sig+seal+floor，
    与 QIAP SIGN 流程（manifest 一条 + seal/floor 后续追加）的最终状态一致。
    """
    if len(image_hash) != HASH_SIZE:
        raise ImageError("manifest hash 必须是 32 字节")
    if image_len <= 0 or image_len > app_size:
        raise ImageError("image_len %d 越界（APP 容量 %d B）"
                         % (image_len, app_size))
    if seq == 0:
        raise ImageError("seq 0 是空记录哨兵，不能使用")
    if sig is None:
        sig = bytes(SIG_SIZE)                  # QIAP END 的 zero_sig 路径
    if len(sig) != SIG_SIZE:
        raise ImageError("sig 必须是 64 字节")
    if seal_hash is None:
        seal_hash = bytes(HASH_SIZE)
    if len(seal_hash) != HASH_SIZE:
        raise ImageError("seal hash 必须是 32 字节")

    rec = bytearray(b"\xFF" * RECORD_SIZE)

    # ---- QMTL meta block (64 B) ----
    _wr32(rec, META_OFF_MAGIC, META_BLK_MAGIC)
    _wr32(rec, META_OFF_SEQ, seq)
    _wr32(rec, META_OFF_FLAG, flag)
    _wr32(rec, META_OFF_FLOOR, floor)
    rec[META_OFF_SEAL_HASH:META_OFF_SEAL_HASH + HASH_SIZE] = seal_hash
    _wr32(rec, META_OFF_SEAL_LEN, seal_len)
    _wr32(rec, META_OFF_CRC, crc32_ieee(bytes(rec[:META_OFF_CRC])))

    # ---- QMF1 manifest block (128 B) ----
    m = MANI_BLK_OFF
    _wr32(rec, m + MANI_OFF_MAGIC, MANI_BLK_MAGIC)
    _wr32(rec, m + MANI_OFF_VERSION, version)
    _wr32(rec, m + MANI_OFF_IMAGE_LEN, image_len)
    rec[m + MANI_OFF_HASH:m + MANI_OFF_HASH + HASH_SIZE] = image_hash
    rec[m + MANI_OFF_SIG:m + MANI_OFF_SIG + SIG_SIZE] = sig
    _wr32(rec, m + MANI_OFF_CRC,
          crc32_ieee(bytes(rec[m:m + MANI_OFF_CRC])))

    return bytes(rec)


def parse_meta_record(rec: bytes, *, check_hash: bytes | None = None,
                      image: bytes | None = None,
                      app_offset: int = APP_OFFSET,
                      app_size: int = APP_SIZE) -> dict:
    """解析并校验一条记录；给定 image 时同时复算 APP 区域 SHA-256。"""
    if len(rec) < RECORD_SIZE:
        raise ImageError("META 记录不足 256 字节")

    if _rd32(rec, META_OFF_MAGIC) != META_BLK_MAGIC:
        raise ImageError("meta 块 magic 不是 QMTL（META 区可能是空的）")
    if crc32_ieee(rec[:META_OFF_CRC]) != _rd32(rec, META_OFF_CRC):
        raise ImageError("meta 块 CRC32 不匹配")

    m = MANI_BLK_OFF
    if _rd32(rec, m + MANI_OFF_MAGIC) != MANI_BLK_MAGIC:
        raise ImageError("manifest 块 magic 不是 QMF1")
    if crc32_ieee(rec[m:m + MANI_OFF_CRC]) != _rd32(rec, m + MANI_OFF_CRC):
        raise ImageError("manifest 块 CRC32 不匹配")

    info = {
        "seq": _rd32(rec, META_OFF_SEQ),
        "flag": _rd32(rec, META_OFF_FLAG),
        "floor": _rd32(rec, META_OFF_FLOOR),
        "version": _rd32(rec, m + MANI_OFF_VERSION),
        "image_len": _rd32(rec, m + MANI_OFF_IMAGE_LEN),
        "hash": rec[m + MANI_OFF_HASH:m + MANI_OFF_HASH + HASH_SIZE],
        "sig": rec[m + MANI_OFF_SIG:m + MANI_OFF_SIG + SIG_SIZE],
    }
    seal_hash = rec[META_OFF_SEAL_HASH:META_OFF_SEAL_HASH + HASH_SIZE]
    info["seal_len"] = _rd32(rec, META_OFF_SEAL_LEN)
    info["has_seal"] = int(any(seal_hash) and info["seal_len"] != 0)
    info["sig_zero"] = int(not any(info["sig"]))
    if info["seq"] == 0:
        raise ImageError("记录 seq 为 0（无效记录）")
    if info["image_len"] == 0 or info["image_len"] > app_size:
        raise ImageError("image_len %d 越界，QBOOT_CHECK 会判 NO_MANIFEST/LEN"
                         % info["image_len"])
    if check_hash is not None and info["hash"] != check_hash:
        raise ImageError("manifest hash 与期望值不一致")
    if image is not None:
        app_area = image[app_offset:app_offset + info["image_len"]]
        if len(app_area) != info["image_len"]:
            raise ImageError("整片镜像长度不足以容纳 image_len")
        actual = hashlib.sha256(app_area).digest()
        if actual != info["hash"]:
            raise ImageError(
                "APP 区域 SHA-256 与 manifest 不一致：\n"
                "  manifest = %s\n  actual   = %s"
                % (info["hash"].hex(), actual.hex())
            )
    return info


# ---------------------------------------------------------------- 合成/校验
def make_combined(boot: bytes, app: bytes, version: int = 0,
                  sign_seed: bytes | None = None,
                  preset_seal: bool = True,
                  meta_base: int | None = None,
                  app_start: int | None = None) -> tuple[bytes, bytes, dict]:
    """返回 (整片 512 KiB 镜像, 256 B META 记录, manifest 信息字典)。

    meta_base / app_start 可覆盖默认布局（None 用出厂默认
    0x08006000 / 0x08007000）；QBOOT 固定在 0x08000000。

    image_len 取 APP bin 的实际长度；QBOOT_CHECK 只哈希这段长度，
    所以 APP 区其余部分用 0xFF 填充不会进入摘要。

    变体感知（按 boot bin 内的 banner 变体串自动判定）：
      * CHECK  —— 行为与旧版一致：sig 全零、无 seal、floor=0、
                  version 用调用方传入值。
      * SEALED —— 要求 sign_seed（32 B Ed25519 私钥 seed）。对描述子
                  image_len(4, LE) || SHA-256(image)（36 B，与设备端
                  quilla_qboot_secure_verify_descriptor 一致）签名；
                  manifest version / floor 取镜像 secver 版本（防降级
                  从首片生效）；预置 seal（seal_hash=镜像哈希、
                  seal_len=image_len），出厂首启免 ~20 s Ed25519 验签。
      * SEC    —— 同 SEALED 的签名与版本要求，但不写 seal（设备端
                  SECURE 模式每次启动全量验签，不用 seal）。
    """
    layout = resolve_layout(meta_base, app_start)
    validate_boot(boot)
    validate_app(app, layout["app_start"], layout["app_size"])

    variant = detect_variant(boot)
    image_len = len(app)
    image_hash = hashlib.sha256(app).digest()

    sig = None
    seal_hash = None
    seal_len = 0
    floor = 0

    if variant in ("SEALED", "SEC"):
        if not sign_seed:
            raise ImageError(
                "QBOOT 变体为 %s：出厂打包必须提供 Ed25519 私钥"
                "（quilla_ed25519_sign.py keygen 生成的 private.hex，"
                "且公钥须与该 QBOOT 内置公钥配对）" % variant)
        if len(sign_seed) != 32:
            raise ImageError("Ed25519 私钥 seed 必须是 32 字节")
        secver_version = read_secver(app)

        ed = _load_sign_tool()
        sig = ed.sign_descriptor(sign_seed, image_len, image_hash)
        # 用配对公钥自验一次，私钥/公钥不配套在这里就拦住
        desc = struct.pack("<I", image_len) + image_hash
        if not ed.verify(sig, desc, ed.pubkey_from_seed(sign_seed)):
            raise ImageError("签名自验失败：私钥与生成的签名不匹配")

        floor = secver_version
        version = secver_version          # manifest version 与镜像版本一致
        if variant == "SEALED" and preset_seal:
            seal_hash = image_hash
            seal_len = image_len

    rec = build_meta_record(image_len, image_hash, version=version,
                            sig=sig, floor=floor,
                            seal_hash=seal_hash, seal_len=seal_len,
                            app_size=layout["app_size"])

    image = bytearray(b"\xFF" * FLASH_SIZE)
    image[0:len(boot)] = boot
    image[layout["meta_offset"]:layout["meta_offset"] + RECORD_SIZE] = rec
    image[layout["app_offset"]:layout["app_offset"] + image_len] = app

    info = {
        "boot_size": len(boot),
        "boot_crc": crc32_ieee(boot),
        "app_crc": crc32_ieee(app),
        "app_size": image_len,
        "image_len": image_len,
        "hash": image_hash,
        "version": version,
        "seq": 1,
        "flag": FLAG_APP1,
        "variant": variant,
        "signed": sig is not None,
        "seal_preset": seal_hash is not None,
        "floor": floor,
        "meta_base": layout["meta_base"],
        "app_start": layout["app_start"],
    }
    return bytes(image), rec, info


def verify_combined(image: bytes, meta_base: int | None = None,
                    app_start: int | None = None) -> dict:
    """按 QBOOT 的视角复核整片镜像（布局与打包时一致才放行）。"""
    if len(image) != FLASH_SIZE:
        raise ImageError(
            "整片镜像长度应为 %d B（0x08000000 起），实际 %d B"
            % (FLASH_SIZE, len(image))
        )

    layout = resolve_layout(meta_base, app_start)
    boot_area = image[:QBOOT_SIZE]
    boot_sp, boot_reset = validate_boot(boot_area)
    app_sp, app_reset = validate_app(
        image[layout["app_offset"]:layout["app_offset"] + layout["app_size"]],
        layout["app_start"], layout["app_size"])

    rec = image[layout["meta_offset"]:layout["meta_offset"] + RECORD_SIZE]
    info = parse_meta_record(rec, image=image,
                             app_offset=layout["app_offset"],
                             app_size=layout["app_size"])

    info.update({
        "boot_sp": boot_sp,
        "boot_reset": boot_reset,
        "app_sp": app_sp,
        "app_reset": app_reset,
        "variant": detect_variant(boot_area),
        "boot_crc": crc32_ieee(boot_area),
        "meta_base": layout["meta_base"],
        "app_start": layout["app_start"],
    })
    return info


# ---------------------------------------------------------------- 自检
def selftest() -> None:
    """不依赖任何固件文件的确定性自检。"""
    # 1) CRC 实现与 zlib 逐字节一致（quilla 用的是同一个多项式）
    samples = [b"", b"A", b"123456789", bytes(range(256)), b"\x00\xFF" * 73]
    for s in samples:
        assert crc32_ieee(s) == (zlib.crc32(s) & 0xFFFFFFFF), "CRC32 不等价"

    # 2) 构造一对向量表合法的假镜像
    boot = bytearray(b"\x00" * 512)
    struct.pack_into("<II", boot, 0, 0x20003000, FLASH_BASE + 0x100 + 1)
    boot[32:32 + 7] = b"[CHECK]"
    app = bytearray(b"\x5A" * 4096)
    struct.pack_into("<II", app, 0, 0x20003ED0, APP_START + 0x200 + 1)

    combined, rec, info = make_combined(bytes(boot), bytes(app), version=7)
    assert len(combined) == FLASH_SIZE
    assert len(rec) == RECORD_SIZE
    assert combined[META_OFFSET:META_OFFSET + RECORD_SIZE] == rec
    assert combined[APP_OFFSET:APP_OFFSET + len(app)] == app
    assert info["hash"] == hashlib.sha256(app).digest()
    assert info["variant"] == "CHECK"

    parsed = verify_combined(combined)
    assert parsed["seq"] == 1 and parsed["flag"] == FLAG_APP1
    assert parsed["version"] == 7 and parsed["image_len"] == len(app)
    assert parsed["variant"] == "CHECK"

    # 3) 改动 APP 一个字节必须让校验失败（manifest 确实绑定了镜像内容）
    broken = bytearray(combined)
    broken[APP_OFFSET + 100] ^= 0xFF
    try:
        verify_combined(bytes(broken))
    except ImageError:
        pass
    else:
        raise AssertionError("APP 被篡改后校验仍通过，manifest 未生效")

    # 4) 空 META 必须被检出（这正是 QBOOT_CHECK 拒跳 APP 的原始问题）
    no_meta = bytearray(combined)
    no_meta[META_OFFSET:META_OFFSET + RECORD_SIZE] = b"\xFF" * RECORD_SIZE
    try:
        verify_combined(bytes(no_meta))
    except ImageError:
        pass
    else:
        raise AssertionError("空 META 未被检出")

    # 5) _estack == RAM 末址必须被拒绝
    bad_sp = bytearray(app)
    struct.pack_into("<I", bad_sp, 0, RAM_START + RAM_SIZE)
    try:
        validate_app(bytes(bad_sp))
    except ImageError:
        pass
    else:
        raise AssertionError("初始 MSP 越界未被检出")

    # 6) SEALED/SEC 出厂签名路径（Ed25519，复用上游 RFC 8032 实现）
    def _boot_with(tag):
        b = bytearray(b"\x00" * 512)
        struct.pack_into("<II", b, 0, 0x20003000, FLASH_BASE + 0x100 + 1)
        b[32:32 + len(tag)] = tag
        return bytes(b)

    def _app_with_secver(ver):
        a = bytearray(b"\x5A" * 4096)
        struct.pack_into("<II", a, 0, 0x20003ED0, APP_START + 0x200 + 1)
        struct.pack_into("<II", a, SECVER_OFFSET, SECVER_MAGIC, ver)
        return bytes(a)

    seed = bytes(range(32))
    sealed_boot = _boot_with(b"[SEALED]")
    sec_app = _app_with_secver(3)

    # 6a) SEALED 无私钥必须被拒
    try:
        make_combined(sealed_boot, sec_app)
    except ImageError:
        pass
    else:
        raise AssertionError("SEALED 缺私钥未被检出")

    # 6b) SEALED 镜像缺 secver 必须被拒
    plain_app = bytearray(b"\x5A" * 4096)
    struct.pack_into("<II", plain_app, 0, 0x20003ED0, APP_START + 0x200 + 1)
    try:
        make_combined(sealed_boot, bytes(plain_app), sign_seed=seed)
    except ImageError:
        pass
    else:
        raise AssertionError("SEALED 镜像缺 secver 未被检出")

    # 6c) SEALED 正常路径：签名 + 预置 seal + floor/version=secver
    comb_s, rec_s, info_s = make_combined(sealed_boot, sec_app, sign_seed=seed)
    assert info_s["variant"] == "SEALED" and info_s["signed"]
    assert info_s["seal_preset"] and info_s["floor"] == 3 and info_s["version"] == 3
    ps = parse_meta_record(rec_s)
    assert ps["has_seal"] == 1 and ps["sig_zero"] == 0 and ps["floor"] == 3

    # 6d) 端到端：用 META 里的 sig 按设备端描述子验签必须通过
    ed = _load_sign_tool()
    desc = struct.pack("<I", info_s["image_len"]) + info_s["hash"]
    assert ed.verify(ps["sig"], desc, ed.pubkey_from_seed(seed))

    # 6e) SEC：要求签名、不预置 seal（设备端 SECURE 每次启动全量验签）
    sec_boot = _boot_with(b"[SEC]")
    comb_x, rec_x, info_x = make_combined(sec_boot, sec_app, sign_seed=seed)
    assert info_x["variant"] == "SEC" and info_x["signed"]
    assert not info_x["seal_preset"]

    # 7) 自定义布局：META/APP 起址可配置，端到端一致才通过
    custom_meta, custom_app = 0x08007000, 0x08009000
    app_c = bytearray(app)
    struct.pack_into("<I", app_c, 4, custom_app + 0x200 + 1)  # 复位向量随布局
    comb_c, rec_c, info_c = make_combined(
        bytes(boot), bytes(app_c), version=7,
        meta_base=custom_meta, app_start=custom_app)
    assert info_c["meta_base"] == custom_meta
    assert info_c["app_start"] == custom_app
    assert comb_c[custom_meta - FLASH_BASE:
                  custom_meta - FLASH_BASE + RECORD_SIZE] == rec_c
    assert comb_c[custom_app - FLASH_BASE:
                  custom_app - FLASH_BASE + len(app_c)] == bytes(app_c)
    assert comb_c[META_OFFSET:META_OFFSET + RECORD_SIZE] == b"\xFF" * RECORD_SIZE
    parsed_c = verify_combined(comb_c, meta_base=custom_meta,
                               app_start=custom_app)
    assert parsed_c["version"] == 7 and parsed_c["image_len"] == len(app)
    # 布局不一致的校验必须失败（防错位解析）
    try:
        verify_combined(comb_c)
    except ImageError:
        pass
    else:
        raise AssertionError("自定义布局镜像按默认布局校验未被拒绝")

    # 8) 非法布局必须被拒（APP 起址落在 META 区内）
    try:
        resolve_layout(META_BASE, META_BASE + 0x100)
    except ImageError:
        pass
    else:
        raise AssertionError("APP 起址早于 META 区结束未被拒绝")

    print("selftest: OK (CRC32 / 记录格式 / 合成布局 / 篡改检测 / 向量表边界 / "
          "变体检测 / Ed25519 出厂签名 / 自定义布局)")


# ---------------------------------------------------------------- CLI
def _read_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _write_file(path: str, data: bytes) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _print_info(info: dict) -> None:
    if info.get("boot_size"):
        print("  QBOOT       : %d B, CRC32 0x%08X"
              % (info["boot_size"], info.get("boot_crc", 0)))
    if info.get("app_crc") is not None:
        print("  APP CRC32   : 0x%08X" % info["app_crc"])
    if info.get("meta_base") and info.get("app_start"):
        print("  布局        : QBOOT 0x%08X / META 0x%08X / APP 0x%08X"
              % (FLASH_BASE, info["meta_base"], info["app_start"]))
    variant = info.get("variant", "unknown")
    print("  QBOOT 变体  : %s%s" % (
        variant,
        "" if variant != "unknown" else "（未识别到变体串，请人工核对）"))
    if variant in ("SEALED", "SEC"):
        print("  [!] 注意    : 该 QBOOT 带验签，出厂打包需确认与 META 密钥/签名方案匹配；"
              "若意图为 CHECK，说明构建串了变体，请 Rebuild all")
    if info.get("floor"):
        print("  floor       : %d（防降级下限）" % info["floor"])
    if info.get("has_seal"):
        print("  seal        : 已预置（SEALED 首启免 ~20 s 验签）")
    if info.get("sig_zero") == 0 and variant == "CHECK":
        print("  sig         : 非零（CHECK 变体不验签，仅记录）")
    print("  APP         : %d B (image_len)" % info["image_len"])
    print("  version     : %d" % info["version"])
    print("  flag        : %d (APP1)" % info.get("flag", FLAG_APP1))
    print("  SHA-256     : %s" % info["hash"].hex())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="QBOOT_CHECK 出厂镜像：生成 manifest + 合成整片 bin")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_pack = sub.add_parser("pack", help="导入 boot/app，生成 manifest 并合成单 bin")
    p_pack.add_argument("--boot", required=True, help="QBOOT bin（CHECK/SEALED/SEC 任一变体）")
    p_pack.add_argument("--app", required=True, help="量产 APP .bin（链接到 0x08007000）")
    p_pack.add_argument("--out", required=True, help="输出整片 bin（烧录到 0x08000000）")
    p_pack.add_argument("--meta-out", help="额外单独导出 256 B META 记录")
    p_pack.add_argument("--version", type=int, default=0,
                        help="manifest 版本号（仅 CHECK 变体使用；SEALED/SEC 自动取镜像 secver）")
    p_pack.add_argument("--key", help="Ed25519 私钥 private.hex（SEALED/SEC 变体必填）")
    p_pack.add_argument("--no-seal", action="store_true",
                        help="SEALED 变体不预置 seal（出厂首启将执行 ~20 s 全量验签）")
    p_pack.add_argument("--meta-base", type=lambda s: int(s, 0),
                        help="META 记录起址（默认 0x08006000），与 QBOOT 端配置一致")
    p_pack.add_argument("--app-start", type=lambda s: int(s, 0),
                        help="APP 起址（默认 0x08007000），须与 APP 链接基址一致")

    p_verify = sub.add_parser("verify", help="校验已有整片 bin")
    p_verify.add_argument("--image", required=True)
    p_verify.add_argument("--meta-base", type=lambda s: int(s, 0),
                          help="META 记录起址（默认 0x08006000）")
    p_verify.add_argument("--app-start", type=lambda s: int(s, 0),
                          help="APP 起址（默认 0x08007000）")

    sub.add_parser("selftest", help="运行内置自检")

    args = ap.parse_args(argv)

    try:
        if args.cmd == "pack":
            boot = _read_file(args.boot)
            app = _read_file(args.app)
            sign_seed = None
            if args.key:
                hex_text = "".join(_read_file(args.key)
                                   .decode("ascii", "strict").split())
                hex_text = hex_text.replace(":", "").replace(",", "")
                sign_seed = bytes.fromhex(hex_text)
            combined, rec, info = make_combined(
                boot, app, version=args.version,
                sign_seed=sign_seed, preset_seal=not args.no_seal,
                meta_base=args.meta_base, app_start=args.app_start)
            _write_file(args.out, combined)
            if args.meta_out:
                _write_file(args.meta_out, rec)
            print("已生成：%s (%d B, 基址 0x%08X)" %
                  (args.out, len(combined), FLASH_BASE))
            _print_info(info)
            if args.meta_out:
                print("  META 记录  : %s (256 B, 0x%08X)" %
                      (args.meta_out, info["meta_base"]))
            print("提示：烧录时选择整片擦除；烧录地址 0x%08X。" % FLASH_BASE)
            return 0

        if args.cmd == "verify":
            image = _read_file(args.image)
            info = verify_combined(image, meta_base=args.meta_base,
                                   app_start=args.app_start)
            print("校验通过：%s" % args.image)
            _print_info(info)
            print("  MSP/reset  : APP 0x%08X / 0x%08X" %
                  (info["app_sp"], info["app_reset"]))
            return 0

        if args.cmd == "selftest":
            selftest()
            return 0
    except (ImageError, OSError) as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
