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

#include <zephyr/kernel.h>

/*
 * Intentionally minimal. Every capability of this appliance is registered by
 * Zephyr itself:
 *
 *   quilla_shell.c  SHELL_CMD_REGISTER (part / version / swqboot)
 *                   SYS_INIT           (banner)
 *   led.c           K_THREAD_DEFINE   (LED heart-beat, optional)
 *   quilla_secver.c section attribute + ROM_START linker snippet (QAV1)
 *   quilla_meta.c   flash API, invoked only by the swqboot command
 *
 * main() only keeps the main thread alive; it must not accumulate unrelated
 * features, and it must never include a Quilla header.
 */
int main(void)
{
	while (true) {
		k_sleep(K_SECONDS(60));
	}
}
