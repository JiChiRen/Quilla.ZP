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
#include <string.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/flash.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/util.h>

/*
 * APP-side META writer. QBOOT owns the boot policy; the appliance is only
 * allowed to append one record changing the interaction flag. Every field
 * that belongs to QBOOT (manifest, seal, anti-rollback floor) is inherited
 * unchanged, so an upgrade request cannot erase the factory manifest.
 *
 * The record layout, magics and CRC are binary-compatible with
 * quilla-qboot-meta.c. No Quilla header is included: the two images share
 * only a flash contract.
 */

#define QZP_META_RECORD_SIZE 256U
#define QZP_META_SLOT_SIZE   (CONFIG_QUILLA_ZP_META_SIZE / 2U)
#define QZP_META_SLOTS       2U
#define QZP_REC_PER_SLOT     (QZP_META_SLOT_SIZE / QZP_META_RECORD_SIZE)

#define QZP_META_BLK_MAGIC  0x514D544CU /* "QMTL" */
#define QZP_MANI_BLK_MAGIC  0x514D4631U /* "QMF1" */
#define QZP_MANI_BLK_OFF    64U
#define QZP_MANI_BLK_SIZE   128U

#define QZP_OFF_MAGIC       0U
#define QZP_OFF_SEQ         4U
#define QZP_OFF_FLAG        8U
#define QZP_OFF_FLOOR       12U
#define QZP_OFF_CRC         52U

#define QZP_MANI_OFF_MAGIC     0U
#define QZP_MANI_OFF_VERSION   4U
#define QZP_MANI_OFF_IMAGE_LEN 8U
#define QZP_MANI_OFF_CRC       108U

/* The GD32 bank0 erase page is 2 KiB, i.e. exactly one META slot. QBOOT never
 * erases the active slot; only the standby slot is erased. */
#define QZP_ERASE_PAGE_SIZE 2048U

BUILD_ASSERT(QZP_META_SLOT_SIZE == QZP_ERASE_PAGE_SIZE,
	     "META slot must equal one GD32 flash erase page");
BUILD_ASSERT((CONFIG_QUILLA_ZP_META_BASE % QZP_ERASE_PAGE_SIZE) == 0,
	     "META base must be erase-page aligned");

static const struct device *const flash_dev =
	DEVICE_DT_GET(DT_CHOSEN(zephyr_flash_controller));

/* uint32_t storage keeps the programming buffer naturally aligned for the
 * GD32 FMC word-program path. */
static uint32_t s_best_words[QZP_META_RECORD_SIZE / 4U];
static uint32_t s_work_words[QZP_META_RECORD_SIZE / 4U];

static uint32_t rd32(const uint8_t *p)
{
	return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
	       ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static void wr32(uint8_t *p, uint32_t v)
{
	p[0] = (uint8_t)(v >> 0);
	p[1] = (uint8_t)(v >> 8);
	p[2] = (uint8_t)(v >> 16);
	p[3] = (uint8_t)(v >> 24);
}

/* IEEE 802.3 CRC-32, reflected polynomial 0xEDB88320. Bit-identical to
 * QBOOT's meta_crc32 and to Zephyr's crc32_ieee(); implemented locally so the
 * appliance does not depend on the CRC Kconfig driver selection. */
static uint32_t crc32_ieee(const uint8_t *p, uint32_t len)
{
	uint32_t crc = 0xFFFFFFFFU;

	for (uint32_t i = 0U; i < len; i++) {
		crc ^= p[i];
		for (uint32_t j = 0U; j < 8U; j++) {
			crc = (crc & 1U) ? ((crc >> 1U) ^ 0xEDB88320U) : (crc >> 1U);
		}
	}
	return crc ^ 0xFFFFFFFFU;
}

/* Zephyr flash API offsets are relative to the flash base, while the QBOOT
 * partition constants are absolute addresses. */
static off_t flash_offset(uint32_t abs_addr)
{
	return (off_t)(abs_addr - DT_REG_ADDR(DT_CHOSEN(zephyr_flash)));
}

static int meta_read(uint32_t abs_addr, uint8_t *dst, size_t len)
{
	return flash_read(flash_dev, flash_offset(abs_addr), dst, len);
}

static int meta_erase_slot(uint32_t abs_addr)
{
	return flash_erase(flash_dev, flash_offset(abs_addr), QZP_META_SLOT_SIZE);
}

static uint32_t record_seq(uint32_t abs_addr, uint8_t *scratch)
{
	if (meta_read(abs_addr, scratch, QZP_META_RECORD_SIZE) != 0) {
		return 0U;
	}
	if (rd32(scratch + QZP_OFF_MAGIC) != QZP_META_BLK_MAGIC) {
		return 0U;
	}
	if (crc32_ieee(scratch, QZP_OFF_CRC) != rd32(scratch + QZP_OFF_CRC)) {
		return 0U;
	}
	/* seq 0 is the "empty record" sentinel. */
	return rd32(scratch + QZP_OFF_SEQ);
}

static bool manifest_valid(const uint8_t *rec)
{
	const uint8_t *p = rec + QZP_MANI_BLK_OFF;

	if (rd32(p + QZP_MANI_OFF_MAGIC) != QZP_MANI_BLK_MAGIC) {
		return false;
	}
	return crc32_ieee(p, QZP_MANI_OFF_CRC) == rd32(p + QZP_MANI_OFF_CRC);
}

static void build_empty_manifest(uint8_t *rec)
{
	uint8_t *p = rec + QZP_MANI_BLK_OFF;

	memset(p, 0xFFU, QZP_MANI_BLK_SIZE);
	wr32(p + QZP_MANI_OFF_MAGIC, QZP_MANI_BLK_MAGIC);
	wr32(p + QZP_MANI_OFF_VERSION, 0U);
	wr32(p + QZP_MANI_OFF_IMAGE_LEN, 0U);
	wr32(p + QZP_MANI_OFF_CRC, crc32_ieee(p, QZP_MANI_OFF_CRC));
}

static bool region_erased(uint32_t abs_addr, size_t len)
{
	uint8_t buf[QZP_META_RECORD_SIZE];

	if (meta_read(abs_addr, buf, len) != 0) {
		return false;
	}
	for (size_t i = 0U; i < len; i++) {
		if (buf[i] != 0xFFU) {
			return false;
		}
	}
	return true;
}

int quilla_zp_meta_set_flag(uint32_t flag)
{
	uint8_t *best = (uint8_t *)s_best_words;
	uint8_t *work = (uint8_t *)s_work_words;
	uint32_t head[QZP_META_SLOTS] = { 0U, 0U };
	uint32_t best_seq = 0U;
	uint8_t best_slot = 0U;
	bool found = false;
	uint32_t slot_base;
	uint32_t target;
	uint32_t new_seq;
	int rc;

	if (!device_is_ready(flash_dev)) {
		return -ENODEV;
	}

	/* Scan both slots; the highest sequence is authoritative. */
	for (uint8_t slot = 0U; slot < QZP_META_SLOTS; slot++) {
		for (uint32_t idx = 0U; idx < QZP_REC_PER_SLOT; idx++) {
			uint32_t addr = CONFIG_QUILLA_ZP_META_BASE +
					((uint32_t)slot * QZP_META_SLOT_SIZE) +
					(idx * QZP_META_RECORD_SIZE);
			uint32_t seq = record_seq(addr, work);

			if (seq == 0U) {
				break;
			}
			head[slot] = idx + 1U;
			if (!found || (seq > best_seq)) {
				best_seq = seq;
				best_slot = slot;
				found = true;
				memcpy(best, work, QZP_META_RECORD_SIZE);
			}
		}
	}

	uint8_t active = found ? best_slot : 0U;
	new_seq = best_seq + 1U; /* empty store -> first record has seq 1 */

	/* Active slot full, or its write head is not blank: switch to the
	 * standby slot and erase it. The authoritative record lives in the
	 * other slot, so a power loss here cannot destroy the only copy. */
	bool switch_needed = head[active] >= QZP_REC_PER_SLOT;
	if (!switch_needed) {
		slot_base = CONFIG_QUILLA_ZP_META_BASE +
			    ((uint32_t)active * QZP_META_SLOT_SIZE);
		target = slot_base + head[active] * QZP_META_RECORD_SIZE;
		switch_needed = !region_erased(target, QZP_META_RECORD_SIZE);
	}
	if (switch_needed) {
		uint8_t other = (uint8_t)(1U - (uint32_t)active);

		rc = meta_erase_slot(CONFIG_QUILLA_ZP_META_BASE +
				     ((uint32_t)other * QZP_META_SLOT_SIZE));
		if (rc != 0) {
			return rc;
		}
		active = other;
		head[active] = 0U;
	}

	slot_base = CONFIG_QUILLA_ZP_META_BASE +
		    ((uint32_t)active * QZP_META_SLOT_SIZE);
	target = slot_base + head[active] * QZP_META_RECORD_SIZE;

	/* Compose the record: inherit every field, change only seq and flag. */
	if (found) {
		memcpy(work, best, QZP_META_RECORD_SIZE);
	} else {
		memset(work, 0xFFU, QZP_META_RECORD_SIZE);
		memset(work + QZP_OFF_FLOOR, 0U, QZP_OFF_CRC - QZP_OFF_FLOOR);
	}
	wr32(work + QZP_OFF_MAGIC, QZP_META_BLK_MAGIC);
	wr32(work + QZP_OFF_SEQ, new_seq);
	wr32(work + QZP_OFF_FLAG, flag);
	wr32(work + QZP_OFF_CRC, crc32_ieee(work, QZP_OFF_CRC));

	if (!found || !manifest_valid(work)) {
		build_empty_manifest(work);
	}

	/* Program-only append into erased cells; no erase of the active slot. */
	rc = flash_write(flash_dev, flash_offset(target), work,
			 QZP_META_RECORD_SIZE);
	if (rc != 0) {
		return rc;
	}

	/* Re-read using QBOOT's own acceptance rules. */
	if (record_seq(target, best) != new_seq) {
		return -EIO;
	}
	if (rd32(best + QZP_OFF_FLAG) != flag) {
		return -EIO;
	}
	return 0;
}
