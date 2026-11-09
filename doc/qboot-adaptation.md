# QBOOT adaptation on GD32F502VE

**[中文](qboot-adaptation.zh-CN.md)**

Unlike `Quilla.FR`, **QBOOT needs no patch at all here**. The GD32F502VE port
already drives USART0 / PB6-PB7 / AF0 / 115200 / DMA0 CH4 — the same wiring
the Zephyr appliance uses. `quilla/` therefore stays a byte-for-byte clean
clone on `develop`, while `appliance/` stays a clean clone on `main`.

## 1. Clones

```
git clone -b develop https://github.com/JiChiRen/Quilla.git quilla
git clone -b main   https://github.com/GD32-MCU-IOT/gd32_zephyr.git appliance
```

`gd32_zephyr` is a full Zephyr 4.4 downstream tree (about 820 MB, 125k
commits). A `--filter=blob:none` partial clone keeps the history mergeable
while avoiding historical blobs. Both directories are gitignored by this
repository.

## 2. What QBOOT expects from the APP

| Requirement | Where it is satisfied |
| --- | --- |
| Vector table at `0x08007000` (MSP + reset handler) | `CONFIG_FLASH_LOAD_OFFSET=0x7000`, `CONFIG_ROM_START_OFFSET=0`, no MCUboot |
| APP image ends before Flash end (`0x0807FFFF`) | `CONFIG_FLASH_LOAD_SIZE=0x79000` |
| QAV1 record at `0x08007400` | `.quilla_secver` section + `ROM_START` linker snippet |
| META record QMTL/QMF1 with the same CRC and flags | `app/src/quilla_meta.c` |
| APP answers `part` with `app1` and accepts `swqboot` | `app/src/quilla_shell.c` |
| 115200 console on USART0 / PB6-PB7 | out-of-tree board DTS + pinctrl |

QBOOT sets `SCB->VTOR = APP_START`, loads MSP and the reset handler from the
first two words, and jumps **without resetting RCC**. The board DTS declares
160 MHz so Zephyr's clock driver and UART baud derivation agree with the
inherited 160 MHz clock tree. This clock handover is one of the items that
must be confirmed on hardware (see the checklist below).

## 3. Flash geometry

GD32F502VE bank0 erases in **2 KiB** pages and programs 32-bit words. The META
region is 4 KiB split into two 2 KiB slots; each slot is exactly one erase
page. Records have a 256 B stride and are appended with program-only writes —
the active slot is never erased. `app/src/quilla_meta.c` contains a
`BUILD_ASSERT` tying the slot size to the 2 KiB page size.

QBOOT's GD32 flash routines run from RAM to avoid read-while-write conflicts.
The Zephyr flash driver used by the appliance is a different implementation;
this is a hardware-verification item, not an assumption that both behave alike.

## 4. Board reuse and its limits

The upstream Zephyr tree has `soc/gd/gd32/gd32f50x/` and boards such as
`gd32f503v_eval`, but **no GD32F502VE board or SoC definition**. The
out-of-tree board reuses the `gd32f503` SoC description and overrides only the
part-specific values in its DTS:

| Item | Upstream `gd32f503vg` | This board |
| --- | --- | --- |
| Flash | 1024 KiB | 512 KiB |
| SRAM | 128 KiB | 64 KiB |
| CPU clock | 252 MHz | 160 MHz |
| USART0 pins | PA9 / PA10 | PB6 / PB7 (AF0) |

Reusing a sibling SoC description is a pragmatic porting step, **not a claim
that F502VE and F503V register maps are identical**. Peripheral base
addresses, RCU clock gating and the FMC controller must be checked on the
target before this is used outside a demo. This has not been verified.

The pinctrl macros `USART0_TX_PB6` / `USART0_RX_PB7` (AF0) come from the
`hal_gigadevice` module declared in `appliance/west.yml` and are present in
`GD32-MCU-IOT/hal_gigadevice_zephyr`. They are not part of the Zephyr main
tree, so `west update` must succeed before the build.

## 5. On-target verification checklist

Not yet performed. Before any release:

1. `west build` succeeds with the out-of-tree board and the pinned Zephyr tree.
2. Inspect the map file: `quilla_zp_secver` is at `0x08007400`, `.text` starts
   after it, and `_vector_start` is `0x08007000`.
3. On power-up the console prints `[QAPP] Quilla.ZP V1.0.0001` with no
   garbling (confirms the 160 MHz clock handover and 115200 baud).
4. `part` returns `app1`; Zephyr shell prompt contains no ANSI escapes.
5. `swqboot` writes the META flag and QBOOT comes back with `[BOOT] ...`.
6. A full QIAP upgrade with CHECK, then SEALED/SEC, returns the completion ACK
   and the new APP boots.
7. `python tools/check_contract.py` passes after any upstream pull.
