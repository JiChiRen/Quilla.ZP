# Build and upgrade guide

**[中文](build-and-upgrade.zh-CN.md)**

> **Status**: a clean Zephyr build has been completed in this workspace
> (native Windows + gnuarmemb, zero warnings); outputs are in
> `app/build-w/zephyr/` and the secver section sits at `0x08007400`.
> **On-target verification is closed**: 2026-11-09 (QBOOT_SECURED) — two
> QIAP upgrades with `ACK_SIGN 0x84`, clean banner, identical cold boots,
> working shell, and the appliance's own `swqboot` returning to `[BOOT]`;
> 2026-11-12 (GD32 true-OTP, both phases) — `OTP_COUNTER` 1→2,
> `APP_END=0x0807FFFF` with no clamp, a lower-version image refused with
> `NAK 0x0A ROLLBACK`, and a same-version upgrade accepted.
> Sections 6 and 7 remain as re-verification checklists; section 3 records
> the workspace layout before the repository move.

## 1. Host tools (Windows native)

Zephyr officially supports native Windows 10/11. WSL is explicitly **not**
recommended by upstream because flashing and debugging from WSL is unreliable;
on this machine `wsl.exe` is additionally blocked by the local security
policy, so Windows native is the only route here.

Install with `winget` (already available on this machine), then reopen the
terminal so PATH is refreshed:

```
winget install Kitware.CMake Ninja-build.Ninja oss-winget.gperf `
  Python.Python.3.12 Git.Git oss-winget.dtc wget 7zip.7zip
```

| Tool | Required version | Present on this machine |
| --- | --- | --- |
| CMake | >= 3.28.0 | no |
| Ninja | recent | no |
| Python | **3.12 strongly recommended** | `py -3.12` yes (uv-installed 3.12.14); `python` on PATH is 3.13.14, do not use it |
| Devicetree compiler (dtc) | >= 1.4.6 | no |
| gperf | recent | no |
| Git | any recent | yes |
| wget / 7-Zip | recent | no |
| west | recent (`pip install west`) | no |

Zephyr's own note: newer Python releases may fail on Windows when installing
the required packages. Create the venv with the 3.12 launcher explicitly:

```
cd %HOMEPATH%
py -3.12 -m venv zephyrproject\.venv
zephyrproject\.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install west
```

PowerShell activation requires
`Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`.

## 2. Cross compiler — two options

**Option A (recommended for a quick first build): reuse the existing GNU Arm
toolchain.** This machine already has Arm GNU Toolchain 13.2.1 with newlib at
`C:\toolchains\Arm_GNU_Toolchain_arm-none-eabi_13.2_Rel1`. Zephyr 4.4 still
ships the `gnuarmemb` and `cross-compile` toolchain variants, so no SDK
download is needed:

```
set ZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb
set GNUARMEMB_TOOLCHAIN_PATH=C:\toolchains\Arm_GNU_Toolchain_arm-none-eabi_13.2_Rel1
```

or, equivalently, `ZEPHYR_TOOLCHAIN_VARIANT=cross-compile` with
`CROSS_COMPILE=C:\toolchains\...\bin\arm-none-eabi-`. Upstream documents
these variants as supported in mechanism but **not officially tested** with
arbitrary compilers; Zephyr SDK is the tested path.

**Option B (upstream default, ~1-2 GB): Zephyr SDK 1.0.1 Windows bundle.**
The pinned tree's `SDK_VERSION` is `1.0.1`, and the SDK ships a Windows
`_windows-x86_64_gnu` bundle containing `arm-zephyr-eabi`:

```
west sdk install
set ZEPHYR_TOOLCHAIN_VARIANT=zephyr
```

Use Option B if Option A fails or if a reproducible, upstream-tested
toolchain is required.

## 3. Workspace topology (historical, before the repository move; see section 4)

> This section records the setup used while the repositories lived under a
> path containing spaces (`...\Midora SA\...`). Since 2026-11-11 all three
> repos live under `C:\D\workspace\prestudy\Quilla\go\`, which is space-free;
> junctions are no longer needed.

`appliance/` is a **full Zephyr tree and also the west manifest repo**
(`appliance/west.yml`, 81 projects). Two constraints follow:

1. **Do not put the build workspace on a path containing spaces.** Spaces in
   the source path are known to break CMake/Ninja/Zephyr on Windows. Create a
   separate build workspace at a short path without spaces, such as
   `C:\zph`, and expose the existing clones there with directory junctions (junctions do not change either clone, so both remain
   pullable/mergeable):

   ```
   mkdir C:\zph
   mklink /J C:\zph\appliance "<...>\Quilla.ZP\appliance"
   mklink /J C:\zph\quilla    "<...>\Quilla.ZP\quilla"
   mklink /J C:\zph\app       "<...>\Quilla.ZP\app"
   ```

2. **The GD32 HAL module is mandatory.** `soc.h` includes `gd32f50x.h`,
   `SystemInit()` and the pinctrl header `gd32f503v(g-e-c)xx-pinctrl.h` all
   come from `hal_gigadevice`, declared in `appliance/west.yml` as
   `https://github.com/GD32-MCU-IOT/hal_gigadevice_zephyr.git` (branch
   `main`, path `modules/hal/gigadevice`). A full `west update` pulls dozens
   of unrelated modules; the minimal route is to clone only what is needed
   and point Zephyr at it:

   ```
   git clone https://github.com/GD32-MCU-IOT/hal_gigadevice_zephyr.git C:\zph\modules\hal\gigadevice
   set EXTRA_ZEPHYR_MODULES=C:\zph\modules\hal\gigadevice
   ```

   `CONFIG_CPU_CORTEX_M` selects `HAS_CMSIS_CORE`, so a CMSIS module may also
   be required; the first build will report it. The full, safer route is a
   normal west workspace with `west update` and a narrowed `group-filter`.

Whether Zephyr 4.4 can build entirely without a west workspace (using
`ZEPHYR_BASE` + `EXTRA_ZEPHYR_MODULES`) must be confirmed by the first build.
If module discovery fails, run `west init -l C:\zph\appliance` in `C:\zph`
and `west update hal_gigadevice` there instead.

## 4. Build commands

> **Path note (after the 2026-11-11 repository move)**: all three repos now
> live under a space-free path. The `C:\zph` junction in sections 3 and 4 is a
> record of the earlier workspace. Builds can use the repo's own `.venv`
> (Python 3.12 / cmake / ninja) and `app/build-w` directly, without any
> junction; the space-in-path pitfalls below only applied to the old path.

**Current build entry point (after the move)** — run from the Quilla.ZP repo
root. The command block below is a historical example; do not copy it:

```
set ZEPHYR_BASE=%CD%\appliance
set BOARD_ROOT=%CD%\app
set ZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb
set GNUARMEMB_TOOLCHAIN_PATH=C:\toolchains\Arm_GNU_Toolchain_arm-none-eabi_13.2_Rel1
set ZEPHYR_MODULES=%CD%\modules\hal\gigadevice;%CD%\modules\hal\cmsis_6
.venv\Lib\site-packages\cmake\data\bin\cmake.exe -B app\build-w -GNinja -S app -DBOARD=gd32f502ve_quilla -DBOARD_ROOT=app -DPython3_EXECUTABLE=%CD%\.venv\Scripts\python.exe -DCMAKE_MAKE_PROGRAM=%CD%\.venv\Scripts\ninja.exe
.venv\Scripts\ninja.exe -C app\build-w
```

`Python3_EXECUTABLE` and `CMAKE_MAKE_PROGRAM` must point into `.venv`:
otherwise CMake picks the system Python 3.13 (missing Zephyr dependencies) or
cannot find Ninja. The output is `app\build-w\zephyr\zephyr.bin`; all later
commands in this guide use the repo root as the working directory.

```
set ZEPHYR_BASE=C:\zph\appliance
set BOARD_ROOT=C:\zph\app
python tools\check_contract.py

cmake -B C:\zph\build -GNinja -S C:\zph\app ^
  -DBOARD=gd32f502ve_quilla -DBOARD_ROOT=C:\zph\app
ninja -C C:\zph\build
```

`BOARD_ROOT` must be the directory **containing** `boards/`, i.e. `app`, not
the board directory itself. `app/CMakeLists.txt` uses
`find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})`, so `ZEPHYR_BASE` is
what selects the GD32 downstream tree.

> **Space-in-path pitfall (verified on Windows)**: if the project path
> contains spaces, two failures occur: ① CMake emits unquoted `-imacros`
> arguments that get split at the space, and Ninja fails; ② Zephyr's
> `K_THREAD_DEFINE`/`K_HEAP_DEFINE` embed `__FILE__` into assembler section
> names without quoting, and GNU as reports `junk at end of line`. A working
> workaround: after a successful configure, replace the long paths in
> `build/build.ninja` and `build/zephyr/misc/generated/syscalls_file_list.txt`
> with 8.3 short paths (e.g. the `C:\PROGRA~1` form), then run `ninja`. The
> file list and the scan directories must use the same path form, otherwise
> every syscall header is parsed twice and the generated syscall headers
> contain duplicate definitions. **Placing the project under a space-free
> path avoids all of this and is the recommended approach.**

## 5. Verify the produced image before flashing

```
arm-none-eabi-nm -n app\build-w\zephyr\zephyr.elf | findstr quilla_zp_secver
arm-none-eabi-objdump -h app\build-w\zephyr\zephyr.elf
```

Checklist:

- `_vector_start` is `0x08007000` — QBOOT reads MSP/reset there.
- `quilla_zp_secver` is at `0x08007400` and `.text` starts **after** it.
- The image fits within `0x08007000` .. `0x0807FFFF`.
- The first 8 bytes of `zephyr.bin` hold a valid MSP (in SRAM) and a Thumb
  reset address inside the APP region.

Pack a factory image with the existing tool (the SECURED variant needs the test
private key from `quilla/tools/_keytest/private.hex`):

**The tool's `FLASH_SIZE` / `APP_SIZE` / `RAM_SIZE` are MCU-specific** and are
set here for GD32F502VE (512 KiB Flash / 64 KiB SRAM). For another MCU, see
[MCU porting guide](mcu-porting.md) for the constant table, the QBOOT/APP
definitions that must be updated together, and the Quilla.FR comparison.

```
python tools\qboot_image.py pack --boot <QBOOT_SECURED.bin> ^
  --app app\build-w\zephyr\zephyr.bin --out combined.bin ^
  --key quilla\tools\_keytest\private.hex
python tools\qboot_image.py verify --image combined.bin
```

### Bumping the firmware security version

The single source of `QUILLA_APP_SECURITY_VERSION` is the shared header
`quilla/os/sys/quilla-version.h` (default `1U`). It sits inside the signed
image; the host updater never supplies a version, and the ZP appliance has no
Zephyr Kconfig knob for it. For a release that must not be rolled back,
override the macro at build time and re-sign the upgrade:

```
cmake -B app/build-w ... -DEXTRA_CFLAGS=-DQUILLA_APP_SECURITY_VERSION=2
ninja -C app/build-w
```

The override lives only in that build directory's CMake cache: reconfiguring
without the argument falls back to `1U`. Verify that offset `0x400` of
`zephyr.bin` holds `QAV1` and `0x404` holds the new version, then confirm the
matching `FW_SECVER` with `secver` after the upgrade. Bumping the version is
**not a partition change**: `app/Kconfig` geometry is unaffected. The manual
alignment contract for partition geometry is in section 2 of the
[MCU porting guide](mcu-porting.md).

## 6. On-target upgrade

Flash QBOOT first, then use the host updater from the `quilla/` clone:

```
python quilla\tools\quilla_host_updater.py COM7 app\build-w\zephyr\zephyr.bin --key quilla\tools\_keytest\private.hex
```

The completion verdict is `ACK_SIGN 0x84` (SEALED/SECURED) or `ACK_END 0x83`
(CHECK). The `[QAPP]` boot stamp is only a non-fatal confirmation; the
appliance prints a complete banner literal, so it should match.

Verify on hardware: banner with no garbling (160 MHz clock handover),
`part` -> `app1`, `swqboot` -> `[BOOT]` banner, then a second full QIAP
upgrade with the new image. Use "Erase Sectors" rather than full-chip erase
when flashing with Keil, so the META manifest is not wiped.

## 7. Known risks and re-verification checklist

> Items registered during integration. On-target verification on 11-09 / 11-12
> covered the QIAP path, clock handover, META writes under XIP and secver
> placement; register-level checks behind the reused SoC description were not
> individually repeated, so these entries remain a checklist rather than being
> marked verified.

- Reusing the `gd32f503` SoC description for a GD32F502VE part is unverified;
  peripheral addresses, RCU gating and FMC behaviour need on-target checks.
- Zephyr's GD32 flash driver is a different implementation from QBOOT's
  RAM-resident FMC routines; META programming from XIP must be verified.
- The `ROM_START` linker snippet must be checked in the generated linker
  script — with the CMake linker generator instead of the LD template,
  `snippets-rom-start.ld` is not consumed. Pin `CONFIG_LD_LINKER_TEMPLATE=y`
  if the secver section does not appear at `0x08007400`.
- The pinctrl header name contains parentheses; verify the C preprocessor
  resolves it on Windows.
