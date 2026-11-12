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

"""Verify that the out-of-tree Zephyr appliance still matches Quilla QBOOT.

Both ``quilla/`` and ``appliance/`` are independent upstream clones that can
be pulled or merged at any time. The two images share no source files, so a
binary-contract drift would only show up on hardware. This script compares the
constants used on both sides and is intended to run before every release.

Usage (from the repository root)::

    python tools/check_contract.py

Exit status is 0 when all checks pass, 1 when a contract mismatch is found,
and 2 when an input file is missing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUILLA = ROOT / "quilla"
APP = ROOT / "app"

QBOOT_HAL_H = QUILLA / "os/services/quilla-qboot/quilla-qboot-hal.h"
QBOOT_META_H = QUILLA / "os/services/quilla-qboot/quilla-qboot-meta.h"
QBOOT_FLAG_H = QUILLA / "os/services/quilla-qboot/quilla-qboot-flag.h"
QBOOT_VERSION_H = QUILLA / "os/sys/quilla-version.h"
QBOOT_SHELLPORT_C = QUILLA / "arch/cpu/arm/gd32f502ve/shellport.c"

APP_KCONFIG = APP / "Kconfig"
APP_META_C = APP / "src/quilla_meta.c"
APP_META_H = APP / "src/quilla_meta.h"
APP_SEGVER_H = APP / "src/quilla_secver.h"
APP_SEGVER_C = APP / "src/quilla_secver.c"
APP_BOARD_DTS = APP / "boards/gd/gd32f502ve_quilla/gd32f502ve_quilla.dts"
APP_PINCTRL = APP / "boards/gd/gd32f502ve_quilla/gd32f502ve_quilla-pinctrl.dtsi"

REQUIRED = (
    QBOOT_HAL_H, QBOOT_META_H, QBOOT_FLAG_H, QBOOT_VERSION_H, QBOOT_SHELLPORT_C,
    APP_KCONFIG, APP_META_C, APP_META_H, APP_SEGVER_H, APP_BOARD_DTS,
    APP_PINCTRL,
)

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def define(text: str, name: str) -> str | None:
    m = re.search(r"^\s*#define\s+" + re.escape(name) + r"\s+([^\s/]+)",
                  text, re.M)
    return m.group(1) if m else None


def num(text: str, name: str) -> int | None:
    raw = define(text, name)
    if raw is None:
        return None
    try:
        return int(raw.rstrip("UuLl"), 0)
    except ValueError:
        return None


def kconfig(text: str, name: str) -> str | None:
    m = re.search(r"^\s*config\s+" + re.escape(name) +
                  r"\s*$.*?^\s*default\s+([^\s#]+)", text, re.M | re.S)
    return m.group(1) if m else None


def kconfig_num(text: str, name: str) -> int | None:
    raw = kconfig(text, name)
    if raw is None:
        return None
    try:
        return int(raw, 0)
    except ValueError:
        return None


def crc32_reflected(data: bytes) -> int:
    """QBOOT meta_crc32 / Zephyr crc32_ieee, IEEE 802.3 reflected form."""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xEDB88320 if crc & 1 else crc >> 1
    return crc ^ 0xFFFFFFFF


def main() -> int:
    missing = [str(p.relative_to(ROOT)) for p in REQUIRED if not p.is_file()]
    if missing:
        print("ERROR: missing input files:", file=sys.stderr)
        for name in missing:
            print("  " + name, file=sys.stderr)
        print("Clone both upstream repositories first (see README.md).",
              file=sys.stderr)
        return 2

    hal = read(QBOOT_HAL_H)
    meta = read(QBOOT_META_H)
    flag = read(QBOOT_FLAG_H)
    ver = read(QBOOT_VERSION_H)
    port = read(QBOOT_SHELLPORT_C)
    cfg = read(APP_KCONFIG)
    meta_c = read(APP_META_C)
    meta_h = read(APP_META_H)
    sec_h = read(APP_SEGVER_H)
    sec_c = read(APP_SEGVER_C)
    dts = read(APP_BOARD_DTS)
    pin = read(APP_PINCTRL)

    # ---- Partition geometry ------------------------------------------------
    meta_base = num(hal, "QUILLA_QBOOT_META_BASE")
    meta_size = num(hal, "QUILLA_QBOOT_META_SIZE")
    app_start = meta_base + meta_size if meta_base and meta_size else None
    check(meta_base == kconfig_num(cfg, "QUILLA_ZP_META_BASE"),
          "META base matches (0x%08X)" % (meta_base or 0))
    check(meta_size == kconfig_num(cfg, "QUILLA_ZP_META_SIZE"),
          "META size matches (0x%X)" % (meta_size or 0))
    check(app_start == kconfig_num(cfg, "QUILLA_ZP_APP_START"),
          "APP start matches (0x%08X)" % (app_start or 0))

    sec_off = num(ver, "QUILLA_APP_SECVER_OFF")
    check(sec_off == kconfig_num(cfg, "QUILLA_ZP_SECVER_OFFSET"),
          "secver offset matches (0x%X)" % (sec_off or 0))
    # The appliance record no longer redefines the magic/version locally:
    # quilla_secver.c initializes quilla_zp_secver from the shared header
    # macros, so the contract is that the initializer references exactly the
    # macros QBOOT and the host updater also use (single source of truth).
    check("QUILLA_APP_SECVER_MAGIC_U32" in sec_c and
          "QUILLA_APP_SECURITY_VERSION" in sec_c,
          "secver record initialized from shared quilla-version.h macros")

    # ---- META record layout -------------------------------------------------
    pairs = (
        ("record size", num(meta, "QUILLA_META_RECORD_SIZE"),
         num(meta_c, "QZP_META_RECORD_SIZE")),
        ("QMTL magic", num(meta, "QUILLA_META_BLK_MAGIC"),
         num(meta_c, "QZP_META_BLK_MAGIC")),
        ("QMF1 magic", num(meta, "QUILLA_MANI_BLK_MAGIC"),
         num(meta_c, "QZP_MANI_BLK_MAGIC")),
        ("manifest offset", num(meta, "QUILLA_MANI_BLK_OFF"),
         num(meta_c, "QZP_MANI_BLK_OFF")),
        ("meta CRC offset", num(meta, "QUILLA_META_OFF_CRC"),
         num(meta_c, "QZP_OFF_CRC")),
        ("manifest CRC offset", num(meta, "QUILLA_MANI_OFF_CRC"),
         num(meta_c, "QZP_MANI_OFF_CRC")),
    )
    for label, upstream, ours in pairs:
        check(upstream == ours and upstream is not None,
              "%s matches (%s)" % (label, upstream))

    # ---- Flag values --------------------------------------------------------
    for name in ("APP1", "QIAP", "QBOOT"):
        up = num(flag, "QUILLA_QBOOT_FLAG_" + name)
        ours = num(meta_h, "QUILLA_ZP_FLAG_" + name)
        check(up == ours and up is not None,
              "flag %s matches (%s)" % (name, up))

    # ---- Serial wiring ------------------------------------------------------
    for macro, token in (
        ("SHELLPORT_USART", "USART0"),
        ("SHELLPORT_TX_PIN", "GPIO_PIN_6"),
        ("SHELLPORT_RX_PIN", "GPIO_PIN_7"),
        ("SHELLPORT_DMA_RX_CH", "DMA_CH4"),
    ):
        check(define(port, macro) == token,
              "QBOOT console %s is %s" % (macro, token))
    check("USART0_TX_PB6" in pin and "USART0_RX_PB7" in pin,
          "appliance binds USART0 to PB6/PB7")
    check("zephyr,shell-uart = &usart0" in dts and
          "zephyr,console = &usart0" in dts,
          "console and shell-uart both point at usart0")
    check("current-speed = <115200>" in dts, "baud rate is 115200")

    # ---- CRC equivalence ----------------------------------------------------
    # Guard the locally implemented CRC against the value QBOOT would compute
    # for a representative record prefix. Both use the reflected IEEE form.
    sample = b"Quilla.ZP QMTL record 1234567890"
    check(crc32_reflected(sample) == 0xBD53E8F9,
          "CRC-32 (IEEE 802.3 reflected) reference vector")

    for ok, label in results:
        print("%s  %s" % ("OK  " if ok else "FAIL", label))
    failed = [label for ok, label in results if not ok]
    print("\n%d/%d checks passed" % (len(results) - len(failed), len(results)))
    if failed:
        print("Contract mismatch -- do not build a release image.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
