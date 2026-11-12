# Zephyr integration: registration points

**[中文](zephyr-integration.zh-CN.md)**

Both upstream trees are pristine clones. Adding a feature must never mean
editing a Zephyr kernel, driver or sample file: the appliance is an
out-of-tree Zephyr application and uses the extension mechanisms Zephyr
provides.

## Shell commands — `SHELL_CMD_REGISTER`

`app/src/quilla_shell.c` registers `part`, `version` and `swqboot`. These are
the Quilla APP shell commands the host updater speaks:

- `part` answers `app1`, telling the host it is talking to the running APP.
- `swqboot` prints `[QAPP] switching to QBOOT...`, appends a META record with
  `flag=QBOOT` and calls `sys_reboot(SYS_REBOOT_COLD)`. QBOOT then stays in its
  shell instead of jumping back to the APP.
- On a META write failure the command reports an error and does **not** reboot.
  A half-committed flag must never be treated as a successful handover.

`CONFIG_SHELL_PROMPT_UART="> "` keeps ANSI escapes and colour codes out of the
line protocol, so the host's plain-text parser sees the reply.

Zephyr's shell already supplies `help` and the `kernel` command group; they are
not reimplemented.

## Boot banner — `SYS_INIT`

The `[QAPP] <name> V<version>` banner is emitted by a `SYS_INIT` hook at
`POST_KERNEL` priority 99, before the serial shell backend (an `APPLICATION`
level init) takes over the UART. It is not printed from `main()`, so it does
not depend on the application thread being scheduled.

The literal `[QAPP] switching to QBOOT...` is deliberately kept as a complete
string in the image: host tools extract the post-upgrade boot-stamp candidate
from the binary.

## LED heart-beat — `K_THREAD_DEFINE` + devicetree

`app/src/led.c` registers a static Zephyr thread and reads the LED from the
`led0` devicetree alias. If the alias is absent the file contributes nothing,
and the application still builds and runs. The LED pin of the reference board
is not part of the QBOOT contract, so no pin is invented here; add a `led0`
alias to `app/app.overlay` for the actual board.

## META record writer — flash API and chosen node

`app/src/quilla_meta.c` obtains the flash device with
`DT_CHOSEN(zephyr_flash_controller)` and uses `flash_read`, `flash_erase` and
`flash_write`. It only appends one record that changes the interaction flag;
the manifest, seal and anti-rollback floor are inherited unchanged. The active
slot is never erased, so a power loss cannot destroy the only valid record.

The record layout, magics, flags and CRC are duplicated locally (no Quilla
header is included) and are binary-compatible with `quilla-qboot-meta.c`.
`tools/check_contract.py` compares both sides after every upstream pull.

CRC-32 is implemented locally in the IEEE 802.3 reflected form. It is
bit-identical to QBOOT's `meta_crc32` and Zephyr's `crc32_ieee` (verified with
a reference vector), and avoids depending on `CRC_DRIVER_HAS_CRC32_IEEE`,
which is conditional in Zephyr 4.4.

Zephyr flash offsets are relative to the flash base, whereas QBOOT partition
constants are absolute addresses; `flash_offset()` converts between them.

## Security-version record — section + linker snippet

QBOOT reads the 8-byte `QAV1` record at the fixed address
`APP_START + 0x400`, without a symbol table. `app/src/quilla_secver.c` emits it
into a `.quilla_secver` input section with `Z_GENERIC_SECTION`, and
`app/linker/quilla-secver.ld` (registered through
`zephyr_linker_sources(ROM_START SORT_KEY 0x3secver ...)`) pins the section to
that absolute address inside the first ROM output section. Later ROM sections
therefore start after the record and cannot overlap it — the same layout
Quilla's own QAPP linker script uses.

The version comes from `QUILLA_APP_SECURITY_VERSION` in the shared header
`quilla/os/sys/quilla-version.h` — the same single source Quilla's own QAPP and
QBOOT use, overridable per build with `-DQUILLA_APP_SECURITY_VERSION=<n>` —
never from the host updater, and with no Zephyr Kconfig knob of its own. The
record is inside the signed image.

The four geometry values in `app/Kconfig` — `QUILLA_ZP_META_BASE`,
`QUILLA_ZP_META_SIZE`, `QUILLA_ZP_APP_START` and `QUILLA_ZP_SECVER_OFFSET` —
are **deliberate copies** of the QBOOT-side constants in `quilla-qboot-hal.h`
and `quilla-version.h`. This is the trade-off of a hybrid architecture
(bare-metal QBOOT + Zephyr APP with no shared build system) that keeps the
upstream Zephyr tree untouched. They must be aligned by hand: follow the
checklist in section 2 of the [MCU porting guide](mcu-porting.md) and run its
section 4 verification whenever they change. Updating only one side produces no
compile-time error; the two images silently disagree about the partition map.

## Console, geometry and clock — out-of-tree board

`app/boards/gd/gd32f502ve_quilla/` is a HWMv2 out-of-tree board selected with
`-DBOARD_ROOT=app`. It reuses the upstream `gd32f50x` SoC description and
overrides only part-specific values: 512 KiB Flash, 64 KiB SRAM, 160 MHz, and
USART0 remapped to PB6/PB7 (AF0) at 115200. `chosen` selects the console,
shell UART and flash controller. `app/app.overlay` is reserved for board
wiring that is not part of the QBOOT contract.

`CONFIG_FLASH_LOAD_OFFSET=0x7000` and `CONFIG_FLASH_LOAD_SIZE=0x79000` place
the image at `0x08007000`. `CONFIG_ROM_START_OFFSET=0` and
`CONFIG_BOOTLOADER_MCUBOOT=n` keep the vector table at the very beginning of
the image, as QBOOT's jump code requires.

## Why not a Zephyr module or a sample

Adding `app/` as an in-tree sample under `appliance/samples/` would make
`git pull` / merge of the upstream tree conflict with local edits. A module
(`ZEPHYR_EXTRA_MODULES`) would add a manifest and Kconfig indirection for no
benefit: this is one application, registered entirely through the standard
application CMake entry point. Both upstream clones stay byte-for-byte clean.
