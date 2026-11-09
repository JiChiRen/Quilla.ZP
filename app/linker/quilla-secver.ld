/*
 * Copyright (c) 2026, JiChiRen Info. Tech.
 * All rights reserved.
 * SPDX-License-Identifier: BSD-3-Clause
 *
 * Zephyr linker snippet, registered with
 *   zephyr_linker_sources(ROM_START SORT_KEY 0x3secver ...)
 *
 * It is included INSIDE the first ROM output section, immediately after the
 * vector table snippets (SORT_KEY 0x0/0x1/0x2 vectors). QBOOT reads the
 * security-version record at the fixed address APP_START + 0x400, so the
 * location counter is advanced to exactly that address and the record is
 * emitted there. All later ROM sections (.text, .rodata, ...) therefore start
 * after the record and cannot overlap it -- the same layout Quilla's own QAPP
 * linker script uses.
 *
 * The values come from app/Kconfig, so changing the partition layout is a
 * single Kconfig edit here and in QBOOT's build defines.
 */

#if defined(CONFIG_QUILLA_ZP_APP_START) && defined(CONFIG_QUILLA_ZP_SECVER_OFFSET)

	. = ALIGN(4);
	. = MAX(ABSOLUTE(.), (CONFIG_QUILLA_ZP_APP_START + CONFIG_QUILLA_ZP_SECVER_OFFSET));
	KEEP(*(.quilla_secver))
	. = ALIGN(4);

#endif
