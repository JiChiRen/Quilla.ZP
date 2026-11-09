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

#include "quilla_meta.h"

#include <errno.h>

#include <zephyr/init.h>
#include <zephyr/kernel.h>
#include <zephyr/shell/shell.h>
#include <zephyr/sys/printk.h>
#include <zephyr/sys/reboot.h>

/*
 * The Quilla APP shell, registered as a Zephyr shell command set. The host
 * updater talks to this text protocol: it probes with "part" and expects a
 * line containing "app1", then sends "swqboot" to park the device in QBOOT.
 *
 * Zephyr's own shell already provides "help" and "kernel"; Quilla's shell
 * provides "part", "kernel" and registered APP commands. Only the two
 * protocol-facing commands are added here, each with SHELL_CMD_REGISTER.
 */

static int cmd_part(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);

	shell_print(sh, "app1");
	return 0;
}

static int cmd_version(const struct shell *sh, size_t argc, char **argv)
{
	ARG_UNUSED(argc);
	ARG_UNUSED(argv);

	shell_print(sh, "[QAPP] " CONFIG_QUILLA_ZP_APP_NAME " "
			 CONFIG_QUILLA_ZP_APP_VERSION);
	return 0;
}

static int cmd_swqboot(const struct shell *sh, size_t argc, char **argv)
{
	int rc;

	ARG_UNUSED(argc);
	ARG_UNUSED(argv);

	/* This literal is extracted from the image by the host updater as the
	 * post-upgrade boot stamp candidate; keep it as a complete string. */
	shell_print(sh, "[QAPP] switching to QBOOT...");

	rc = quilla_zp_meta_set_flag(QUILLA_ZP_FLAG_QBOOT);
	if (rc != 0) {
		shell_error(sh, "META flag commit failed (%d); staying in APP", rc);
		return -EIO;
	}

	/* Let the line reach the host before the UART is shut down by reset. */
	k_msleep(20);
	sys_reboot(SYS_REBOOT_COLD);
	return 0;
}

SHELL_CMD_REGISTER(part, NULL, "Show partition identity", cmd_part);
SHELL_CMD_REGISTER(version, NULL, "Show appliance version", cmd_version);
SHELL_CMD_REGISTER(swqboot, NULL, "Switch to QBOOT for an upgrade", cmd_swqboot);

/* Print at POST_KERNEL, before the serial shell backend (APPLICATION level)
 * takes over the UART, so the banner arrives as one clean line. Registered
 * through SYS_INIT rather than called from main(): the console and the shell
 * are separate Zephyr subsystems and must not depend on the app thread. */
static int quilla_zp_banner(void)
{
	printk("[QAPP] " CONFIG_QUILLA_ZP_APP_NAME " "
	       CONFIG_QUILLA_ZP_APP_VERSION "\n");
	return 0;
}

SYS_INIT(quilla_zp_banner, POST_KERNEL, 99);
