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

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>

/*
 * Zephyr's static thread registration replaces the Quilla QAPP Contiki
 * process / FreeRTOS task: the LED heart-beat is a K_THREAD_DEFINE entry, and
 * the LED itself comes from the devicetree "led0" alias. Adding an alias in
 * app.overlay is enough to enable the thread; no source change required.
 *
 * This file owns the LED only. It does not touch the console, META or secver.
 */

#if DT_NODE_EXISTS(DT_ALIAS(led0))

static const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);

static void led_thread(void *unused1, void *unused2, void *unused3)
{
	ARG_UNUSED(unused1);
	ARG_UNUSED(unused2);
	ARG_UNUSED(unused3);

	if (!gpio_is_ready_dt(&led)) {
		return;
	}
	if (gpio_pin_configure_dt(&led, GPIO_OUTPUT_ACTIVE) != 0) {
		return;
	}

	while (true) {
		gpio_pin_toggle_dt(&led);
		k_msleep(CONFIG_QUILLA_ZP_LED_BEAT_MS);
	}
}

K_THREAD_DEFINE(quilla_zp_led_tid, 512, led_thread, NULL, NULL, NULL,
		K_LOWEST_APPLICATION_THREAD_PRIO, 0, 0);

#endif /* DT_NODE_EXISTS(DT_ALIAS(led0)) */
