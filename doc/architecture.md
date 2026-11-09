# Architecture

**[中文](architecture.zh-CN.md)**

## Two images, one MCU

| | QBOOT | appliance (APP) |
| --- | --- | --- |
| Source | `quilla/` (upstream clone, unmodified) | `app/` (out-of-tree Zephyr application) |
| Runtime | Quilla cooperative processes, no heap | Zephyr 4.4 kernel, preemptive threads |
| Flash | `0x08000000` .. `0x08005FFF` | `0x08007000` .. `0x0807FFFF` |
| Serial driver | `quilla/arch/cpu/arm/gd32f502ve/shellport.c` | Zephyr `gd,gd32-usart` + serial shell backend |
| Console | interactive QBOOT shell + QIAP binary protocol | Zephyr shell (`part`, `version`, `swqboot`) |

Both images drive USART0 / PB6 TX / PB7 RX / AF0 / 115200. One host connector
serves normal operation and firmware updates. QBOOT uses DMA0 CH4 for reception
in CIRCULAR mode; the appliance uses the interrupt-driven Zephyr UART driver.
QBOOT disables USART0 and DMA0 CH4 IRQs and stops the DMA channel before the
jump, so the appliance starts from a clean peripheral state.

## Zero code coupling

QBOOT includes no appliance header or source, and the appliance includes no
Quilla header or source. The shared contract is implemented independently on
each side and checked by `tools/check_contract.py`:

| Contract | QBOOT side | Appliance side |
| --- | --- | --- |
| Partition | `QUILLA_QBOOT_META_BASE` / `_SIZE` in `quilla-qboot-hal.h` | Kconfig `QUILLA_ZP_META_*` / `QUILLA_ZP_APP_START` |
| META record | QMTL + QMF1, 256 B, CRC-32 (IEEE 802.3 reflected) | `app/src/quilla_meta.c`, local constants and CRC |
| META flags | `APP1` / `QIAP` / `QBOOT` in `quilla-qboot-flag.h` | `QUILLA_ZP_FLAG_*` in `app/src/quilla_meta.h` |
| secver | `QAV1` + version at `APP_START + 0x400` | `.quilla_secver` section at the same address |
| Console | USART0 / PB6-PB7 / 115200 | board DTS + pinctrl overlay |
| Core clock | 160 MHz, 8 MHz HXTAL + PLL | `clock-frequency = <DT_FREQ_M(160)>` in board DTS |

## Boot and update sequence

1. QBOOT reads the META log. With a valid manifest it jumps to `0x08007000`.
2. The Zephyr image starts with its vector table at that address. Its own
   startup sets VTOR to the linked vector table, consistent with the value
   QBOOT already wrote.
3. The `SYS_INIT` hook prints `[QAPP] Quilla.ZP V1.0.0001`; the serial shell
   backend becomes ready.
4. The host sends `part` and receives a line containing `app1`.
5. The host sends `swqboot`. The command writes `flag=QBOOT` into META and
   resets; QBOOT stays in its shell instead of jumping to the APP.
6. The host sends `qiap` and runs ENTER / DATA / END [/ SIGN].
7. QBOOT writes the manifest, sets `flag=APP1`, sends the completion ACK and
   reboots into the new APP. The ACK is the completion verdict; the `[QAPP]`
   stamp is only a non-fatal confirmation.

## Security boundary

CHECK verifies transport integrity (SHA-256) only. SEALED and SEC add
Ed25519 authentication and anti-rollback, and require the QAV1 record. The
default Quilla keypair is public and must be replaced before shipment.

The APP-side secver self-check used by other Quilla appliances is obfuscation,
not a cryptographic control; it is not implemented here. The real gate is the
QBOOT signature check plus the persisted floor. Absolute rollback protection
would require a hardware monotonic counter (eFuse/OTP), which is outside this
demo.
