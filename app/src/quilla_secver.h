/*
 * Copyright (c) 2026, JiChiRen Info. Tech.
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the conditions of the BSD-3
 * license referenced in the project LICENSE file are met.
 *
 * This file is part of the Quilla.ZP appliance.
 */

#ifndef QUILLA_ZP_SECVER_H_
#define QUILLA_ZP_SECVER_H_

#include <stdint.h>

/*
 * QBOOT's anti-rollback gate reads an 8-byte record at a FIXED flash address
 * (APP_START + 0x400) without any symbol table. The layout below is defined
 * locally in the appliance: including any Quilla header here would couple the
 * two images.
 *
 * This record sits inside the signed image, so its version cannot be changed
 * without the private key.
 */
#define QUILLA_ZP_SECVER_MAGIC_U32 0x31564151U /* "QAV1" */

typedef struct {
	uint32_t magic;
	uint32_t version;
} quilla_zp_secver_t;

/*
 * Zephyr-native placement: the variable is emitted into a dedicated input
 * section, and app/linker/quilla-secver.ld (registered through
 * zephyr_linker_sources(ROM_START ...)) pins that section to the absolute
 * address QBOOT reads. Do not move this definition into main.c.
 */
extern const quilla_zp_secver_t quilla_zp_secver;

#endif /* QUILLA_ZP_SECVER_H_ */
