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
#include "quilla-version.h"

#include <zephyr/toolchain.h>

/*
 * Owns the QAV1 region and nothing else. The section name is consumed by
 * app/linker/quilla-secver.ld. Both the magic and the version come from the
 * shared Quilla header (single source for QAPP, QBOOT and this appliance);
 * the version is never supplied by the host updater.
 */
const quilla_zp_secver_t quilla_zp_secver
	Z_GENERIC_SECTION(.quilla_secver) __used = {
	.magic = QUILLA_APP_SECVER_MAGIC_U32,
	.version = QUILLA_APP_SECURITY_VERSION,
};
