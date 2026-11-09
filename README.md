# Quilla.ZP

**[中文](README.zh-CN.md)**

A minimal reference design showing **Quilla QBOOT** booting a **Zephyr RTOS
appliance** on a GD32F502VE (Cortex-M33) instead of Quilla's own
Contiki-based APP.

This is the Zephyr counterpart of `Quilla.FR`. The point of the demo is the
boundary between the two images: they share no header and no source file, only
a binary flash contract.

## Layout

| Path | Contents |
| --- | --- |
| `quilla/` | Independent clone of `github.com/JiChiRen/Quilla` (branch `develop`). Not tracked here; pull/merge upstream at any time. |
| `appliance/` | Independent clone of `github.com/GD32-MCU-IOT/gd32_zephyr` (branch `main`), a Zephyr 4.4 downstream tree with GD32 support. Its directory structure is kept intact so upstream can be merged. Not tracked here. |
| `app/` | The out-of-tree Zephyr application owned by this repository. Every Quilla-side capability is added through Zephyr's own registration mechanisms; no upstream Zephyr file is modified. |
| `doc/` | Architecture, registration points, QBOOT adaptation, and build/upgrade guides (EN / zh-CN). |
| `tools/` | `check_contract.py` (binary-contract checker) and `qboot_image.py` (factory image packer). |

Both upstream clones are deliberately excluded by `.gitignore`. Recreate them
with the commands in `doc/build-and-upgrade.md`.

## The contract

| Item | Value |
| --- | --- |
| QBOOT | `0x08000000`, 24 KiB |
| META | `0x08006000`, 4 KiB (two 2 KiB slots, 256 B records) |
| APP | `0x08007000` .. `0x0807FFFF` (484 KiB) |
| QAV1 record | `0x08007400` (APP start + `0x400`), 8 bytes, inside the signed image |
| Console | USART0 / PB6 TX / PB7 RX / AF0 / 115200 8N1, DMA0 CH4 in QBOOT |
| Core clock | 160 MHz (8 MHz HXTAL + PLL), set by QBOOT and declared in the board DTS |

QBOOT sets `SCB->VTOR = APP_START`, loads MSP and the reset handler from the
first two words of the APP image, and jumps. The Zephyr image must therefore
start with its vector table at `0x08007000` with no image header.

## Registration points

All appliance-side behaviour is registered with Zephyr, never pasted into an
unrelated Zephyr file:

| Capability | Zephyr mechanism | File |
| --- | --- | --- |
| `part` / `version` / `swqboot` commands | `SHELL_CMD_REGISTER` | `app/src/quilla_shell.c` |
| `[QAPP]` boot banner | `SYS_INIT` | `app/src/quilla_shell.c` |
| LED heart-beat | `K_THREAD_DEFINE` + `led0` devicetree alias | `app/src/led.c` |
| META flag commit | Zephyr flash driver API, `DT_CHOSEN(zephyr_flash_controller)` | `app/src/quilla_meta.c` |
| QAV1 record | section attribute + `zephyr_linker_sources(ROM_START ...)` | `app/src/quilla_secver.c`, `app/linker/quilla-secver.ld` |
| Console and flash layout | out-of-tree board (`BOARD_ROOT`) + devicetree chosen/overlay | `app/boards/gd/gd32f502ve_quilla/`, `app/app.overlay` |
| Version, geometry, partition | Kconfig | `app/Kconfig`, `app/prj.conf` |

See `doc/zephyr-integration.md` for the rationale of each choice.

## Verification status

**This application has not been compiled or run on hardware.** The Windows
workspace used to create it has no `west`, no Zephyr SDK and no Linux build
environment. All upstream APIs, Kconfig symbols, devicetree bindings and CRC
behaviour were checked against the pinned Zephyr 4.4 tree, but a first
`west build` and an on-target run are still required. See
`doc/build-and-upgrade.md` for the exact build commands and the verification
checklist.

`python tools/check_contract.py` passes 22/22 checks against the two clones.
It compares partition geometry, META record layout, flag values, secver magic,
console wiring and the CRC reference vector. Run it after every upstream pull.

For porting to another MCU, `tools/qboot_image.py` hard-codes the GD32F502VE
geometry (512 KiB Flash / 64 KiB SRAM). See
[doc/mcu-porting.md](doc/mcu-porting.md) for the constant table and the
synchronisation checklist.

## License

The appliance-owned files are BSD-3 (see `LICENSE`). The two upstream clones
keep their own licenses (Quilla BSD-3, Zephyr Apache-2.0) and are not
redistributed by this repository.
