# Copyright (c) 2026, JiChiRen Info. Tech.
# All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause

# Flashing is done with the same debug probe as the QBOOT build. Full-chip
# erase is deliberately NOT the default: it would wipe the META manifest.
board_runner_args(jlink "--device=GD32F502VE" "--speed=4000")

include(${ZEPHYR_BASE}/boards/common/openocd.board.cmake)
include(${ZEPHYR_BASE}/boards/common/jlink.board.cmake)
