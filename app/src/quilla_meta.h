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

#ifndef QUILLA_ZP_META_H_
#define QUILLA_ZP_META_H_

#include <stdint.h>

/* Values are defined by Quilla's quilla-qboot-flag.h. They are duplicated
 * here (not included) so the appliance has no Quilla header dependency. */
#define QUILLA_ZP_FLAG_APP1  0x00000001U
#define QUILLA_ZP_FLAG_QIAP  0x00000002U
#define QUILLA_ZP_FLAG_QBOOT 0x00000003U

/*
 * Append a META record carrying the requested flag, keeping the manifest,
 * seal and anti-rollback floor inherited from the newest valid record.
 * Returns 0 on success, negative errno on flash failure. A failure is a
 * failed commit: the caller must NOT reboot into the upgrade.
 */
int quilla_zp_meta_set_flag(uint32_t flag);

#endif /* QUILLA_ZP_META_H_ */
