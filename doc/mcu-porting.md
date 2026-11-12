# Porting the factory image geometry to another MCU

**[中文](mcu-porting.zh-CN.md)**

`tools/qboot_image.py` builds a full-chip image (QBOOT + META + APP). Its
partition constants fall into three groups. Porting to a new MCU means
changing **only the MCU-specific group** and then updating the matching
definitions on the QBOOT side and the APP side. This document is the checklist.

The same tool is used in `Quilla.FR` (PY32F040xB). Both configurations are
listed below so they can be compared directly.

## 1. Constants in `tools/qboot_image.py`

### MCU-specific — must be changed

| Constant | Meaning | Quilla.ZP (GD32F502VE) | Quilla.FR (PY32F040xB) |
| --- | --- | --- | --- |
| `FLASH_BASE` | Flash base address / combined image load address | `0x08000000` | `0x08000000` |
| `FLASH_SIZE` | Total Flash size; **also the exact byte length of `combined.bin`** | `0x00080000` (512 KiB) | `0x00020000` (128 KiB) |
| `APP_SIZE` | APP region length; bounds `image_len` | `0x00079000` (484 KiB) | `0x00019000` (100 KiB) |
| `RAM_START` | SRAM base; lower bound of the initial MSP check | `0x20000000` | `0x20000000` |
| `RAM_SIZE` | SRAM size; **upper bound of the initial MSP check** | `0x00010000` (64 KiB) | `0x00004000` (16 KiB) |

Two relations must hold:

```
APP_SIZE   = FLASH_SIZE - (APP_START - FLASH_BASE) = FLASH_SIZE - 0x7000
SOC_FLASH_END (QBOOT soc.h) = FLASH_BASE + FLASH_SIZE - 1
```

> **`APP_SIZE` is not the runtime-usable APP length**: the table value is the
> physical partition length derived from the Flash size (bound for
> `combined.bin` and `image_len`). With the write-protected NV counter enabled,
> QBOOT clamps `QUILLA_QBOOT_APP_END` to the byte before the counter base
> (PY32 → `0x0801DFFF`, usable `0x17000`), one top sector smaller than the
> physical partition; see `doc/anti-rollback-counter.md` §2.1 in the main repo.
> The two are not in conflict; partition changes still follow the manual
> alignment checklist in section 2.

For this board: `SOC_FLASH_END = 0x0807FFFF`, and the GD32 QBOOT build passes
`-DQUILLA_QBOOT_RAM_SIZE=0x00010000U` so the tool's 64 KiB MSP bound matches
QBOOT. If those two disagree, `quilla_qboot_hal_app_image_valid()` can reject
a perfectly valid Zephyr image whose initial MSP sits at the top of SRAM.

`FLASH_SIZE` is not merely documentation: the tool allocates
`bytearray(b"\xFF" * FLASH_SIZE)` and `verify_combined()` rejects an image of
any other length.

### Layout constants — only change if the partition map itself changes

| Constant | Value | Note |
| --- | --- | --- |
| `QBOOT_SIZE` | `0x00006000` (24 KiB) | QBOOT image budget, fixed by the QBOOT linker script |
| `META_BASE` | `0x08006000` | Immediately after QBOOT |
| `META_SIZE` | `0x00001000` (4 KiB) | Two 2 KiB slots |
| `APP_START` | `0x08007000` | Must be erase-page aligned (2 KiB on GD32F502VE) |
| `META_OFFSET` / `APP_OFFSET` | derived | `*_BASE - FLASH_BASE`; update if `FLASH_BASE` changes |

These four are **identical in Quilla.ZP and Quilla.FR**. Keeping them fixed is
what lets QBOOT stay MCU-independent at the policy layer. If you move them,
change all of the following together: QBOOT build defines, the APP linker/Zephyr
configuration, the META writer in the APP, and `--meta-base` / `--app-start` on
the host.

### Protocol constants — do not change

`RECORD_SIZE` (256 B), `META_SLOT_SIZE` (2 KiB), `SECVER_OFFSET` (`0x400`),
`SECVER_MAGIC` (`QAV1`), the QMTL/QMF1 magics and field offsets, CRC-32
(IEEE 802.3 reflected), flag values, manifest hash/signature layout, and the
36-byte signed descriptor. These form the binary contract with QBOOT and are
independent of the MCU. `tools/check_contract.py` verifies them against both
clones.

## 2. Where the same numbers must be repeated

### Manual alignment is a deliberate design trade-off (hybrid architecture)

Quilla.ZP is a hybrid: QBOOT is bare-metal C (Keil / GCC builds, constants from
`quilla/os/sys/quilla-version.h`, `quilla-qboot-hal.h` and build defines), the
APP is a Zephyr out-of-tree application (constants from `app/Kconfig`, board
DTS and linker snippets), and the host packer `tools/qboot_image.py` has its own
Python constants. The three do not share a build system and have no common
generated configuration header. Keeping the upstream Zephyr tree untouched and
keeping QBOOT free of devicetree dependencies are deliberate choices; the price
is that **partition geometry and protocol constants must be repeated in several
places and aligned by hand**. This is a controlled design trade-off, not an
oversight or a defect awaiting refactoring.

| Class | Where it lives | Manual sync needed |
| --- | --- | --- |
| Feature switches | Zephyr: `app/prj.conf`; QBOOT: build defines | No, each side owns its own |
| Partition geometry / protocol constants | No single source; the table below is the authoritative list | **Yes**, a change in one place must be applied to all |
| Firmware security version | `QUILLA_APP_SECURITY_VERSION` in the shared header `quilla/os/sys/quilla-version.h` | No; override per build with `-DQUILLA_APP_SECURITY_VERSION=<n>`, **no ZP-specific Kconfig knob** |

Changing only one side **fails silently**: QBOOT reads the wrong META slot or
`QAV1` record, QIAP writes out of bounds, or signature verification fails —
there is no compile-time error. Every partition change therefore requires:
(1) walking the table below and updating every listed location; (2) re-running
the verification commands in section 4; (3) repeating the same check in both
Quilla.ZP and Quilla.FR; (4) confirming `APP_START` / `APP_END` on target with
`pinfo`. Bumping the security version is not a partition change: it only needs
the build-time override of the shared macro and a re-signed image.

| Layer | File / symbol | What to set |
| --- | --- | --- |
| QBOOT | `quilla/arch/cpu/arm/<mcu>/soc.h` → `SOC_FLASH_END` | `FLASH_BASE + FLASH_SIZE - 1` (`0x0807FFFF` here). QBOOT derives `APP_END` from it and fails with `#error` if missing. |
| QBOOT | build defines `QUILLA_QBOOT_RAM_START`, `QUILLA_QBOOT_RAM_SIZE` | Must equal `RAM_START` / `RAM_SIZE` in the tool. GD32 builds pass `-DQUILLA_QBOOT_RAM_SIZE=0x00010000U`; PY32 uses the 16 KiB default. |
| QBOOT | build define `QUILLA_QBOOT_PAGE_SIZE` | Physical erase page: **2 KiB** on GD32F502VE, **256 B** on PY32F040. Drives QIAP page coalescing and the META append strategy. |
| QBOOT | build defines `QUILLA_QBOOT_APP_START`, `QUILLA_QBOOT_APP_END`; META geometry from `QUILLA_QBOOT_META_BASE` / `QUILLA_QBOOT_META_SIZE` | Match `APP_START` / `META_BASE` / `SOC_FLASH_END`. |
| Host packer | `tools/qboot_image.py` constants above | `FLASH_SIZE`, `APP_SIZE`, `RAM_SIZE`, `FLASH_BASE`. |
| APP (Zephyr) | `app/prj.conf` | `CONFIG_FLASH_LOAD_OFFSET=0x7000`, `CONFIG_FLASH_LOAD_SIZE=APP_SIZE` (`0x79000`). |
| APP (Zephyr) | `app/boards/gd/gd32f502ve_quilla/gd32f502ve_quilla.dts` | `&flash0 reg = <FLASH_BASE DT_SIZE_K(512)>`, `&sram0 reg = <RAM_START DT_SIZE_K(64)>`, `clock-frequency`. |
| APP (Zephyr) | `app/Kconfig` | `QUILLA_ZP_META_BASE`, `QUILLA_ZP_META_SIZE`, `QUILLA_ZP_APP_START`, `QUILLA_ZP_SECVER_OFFSET`. |
| APP (FreeRTOS) | `appliance/gcc/py32f040xb.ld` (FR) | `FLASH ORIGIN = 0x08007000`, `LENGTH = APP_SIZE`; `RAM ORIGIN = RAM_START`, `LENGTH = RAM_SIZE`. |
| APP (Keil) | `appliance/MDK-ARM/*.uvprojx` (FR) | IROM1 = `0x08007000` / `APP_SIZE`; IRAM1 = `RAM_START` / `RAM_SIZE`; build with `QAPP_BUILD`. |
| APP | META writer page constant | ZP: `QZP_ERASE_PAGE_SIZE` in `app/src/quilla_meta.c` (2048) with `BUILD_ASSERT(slot == page)`. FR: `QB_PAGE_SIZE` in `appliance/Src/app_qboot_meta.c` (256). |
| APP | secver section | `APP_START + 0x400`, emitted by every APP build and covered by the signature. In ZP it is pinned by `app/linker/quilla-secver.ld`. |
| Cross-image (QBOOT / ZP APP / FR APP) | `quilla/os/sys/quilla-version.h` → `QUILLA_APP_SECURITY_VERSION` | Default `1U`; bump at build time with `-DQUILLA_APP_SECURITY_VERSION=<n>` for a release that must not be rolled back. No ZP Kconfig knob; see the security-version section of `doc/zephyr-integration.md`. |

## 3. Porting procedure

1. From the datasheet, record Flash base/size, SRAM base/size and the
   **physical erase page size**.
2. Set `FLASH_BASE`, `FLASH_SIZE`, `RAM_START`, `RAM_SIZE` in the tool;
   recompute `APP_SIZE = FLASH_SIZE - 0x7000`.
3. Add or fix `SOC_FLASH_END` in the new `arch/cpu/arm/<mcu>/soc.h`, and set
   the QBOOT build defines listed above for every QBOOT target (CHECK /
   SEALED / SECURED, GCC and Keil).
4. Update the Zephyr `FLASH_LOAD_*` values, board DTS `reg` entries and
   `app/Kconfig` geometry (or the FreeRTOS/Keil linker settings). Keep the
   secver record at `+0x400`.
5. Update the APP META writer's erase-page constant. On GD32 the 2 KiB page
   equals one META slot; on PY32 the 256 B page equals one record. The
   append-only rule is "never erase the active slot", so a mismatch silently
   corrupts the log.
6. Build QBOOT and APP, then verify before flashing.

## 4. Verification commands

```
python tools/check_contract.py
python tools/qboot_image.py selftest
python tools/qboot_image.py pack --boot <QBOOT.bin> --app <zephyr.bin> \
    --out combined.bin --key <private.hex>
python tools/qboot_image.py verify --image combined.bin
```

`check_contract.py` compares geometry, META layout, flag values, secver magic
and console wiring against both upstream clones (22 checks); run it after
every upstream pull. `qboot_image.py selftest` covers CRC, record layout,
vector-table bounds and signed-factory-image generation.

Also check with `nm`/`objdump` on the Zephyr ELF: the initial MSP lies inside
`[RAM_START, RAM_START + RAM_SIZE)`, the reset vector is a Thumb address inside
the APP region, `_vector_start` is `APP_START`, and the `QAV1` record sits at
`APP_START + 0x400`; read the 8 bytes at offset `0x400` of `zephyr.bin` to
confirm the `QAV1` magic and version word. After any partition change, also
confirm `APP_START` / `APP_END` on target with `pinfo`, and re-run every
command in this section in both ZP and FR repositories.

## 5. Clock handover is a separate concern

Geometry is not the only MCU-specific item. QBOOT jumps **without resetting
RCC**, and Quilla.FR hit a 6x baud mismatch because the HAL derives UART baud
from the stale `SystemCoreClock` variable. This project declares 160 MHz in
the board DTS to match QBOOT's inherited clock tree; a new port must confirm
that the inherited clock and Zephyr's baud derivation agree. This is listed as
an on-target verification item in `doc/qboot-adaptation.md` and has not been
verified yet.
