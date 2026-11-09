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

#include "quilla_secver.h"

#include <zephyr/toolchain.h>

/*
 * Owns the QAV1 region and nothing else. The section name is consumed by
 * app/linker/quilla-secver.ld; the version comes from Kconfig, never from
 * the host updater.
 */
const quilla_zp_secver_t quilla_zp_secver
	Z_GENERIC_SECTION(.quilla_secver) __used = {
	.magic = QUILLA_ZP_SECVER_MAGIC_U32,
	.version = CONFIG_QUILLA_ZP_SECURITY_VERSION,
};
