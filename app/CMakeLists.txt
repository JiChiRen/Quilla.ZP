# Copyright (c) 2026, JiChiRen Info. Tech.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the conditions of the BSD-3
# license referenced in the project LICENSE file are met.

cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(quilla_zp LANGUAGES C)

# Each Quilla-side capability is a separate translation unit registered
# through Zephyr's own mechanisms (SHELL_CMD_REGISTER, SYS_INIT, Kconfig,
# devicetree). Nothing is added to the upstream Zephyr tree.
target_sources(app PRIVATE
  src/main.c
  src/quilla_shell.c
  src/quilla_meta.c
  src/quilla_secver.c
  src/led.c
)

target_include_directories(app PRIVATE src)

# The QAV1 security-version record must sit at a fixed flash address because
# QBOOT reads it without a symbol table. A ROM_START linker snippet is the
# standard Zephyr way to reserve that slot; see app/linker/quilla-secver.ld.
# SORT_KEY places it after Zephyr's own vector-table snippets.
zephyr_linker_sources(ROM_START SORT_KEY 0x3secver linker/quilla-secver.ld)
