# Build and upgrade guide

**[中文](build-and-upgrade.zh-CN.md)**

> **Status**: the commands below are derived from the pinned Zephyr 4.4 tree
> and the official Zephyr getting-started instructions. They have **not** been
> executed in this workspace; no `west build` has run yet. Treat the first
> build as a verification step, not a proven procedure.

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

## 3. Workspace topology (important)

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

## 5. Verify the produced image before flashing

```
arm-none-eabi-nm -n C:\zph\build\zephyr\zephyr.elf | findstr quilla_zp_secver
arm-none-eabi-objdump -h C:\zph\build\zephyr\zephyr.elf
```

Checklist:

- `_vector_start` is `0x08007000` — QBOOT reads MSP/reset there.
- `quilla_zp_secver` is at `0x08007400` and `.text` starts **after** it.
- The image fits within `0x08007000` .. `0x0807FFFF`.
- The first 8 bytes of `zephyr.bin` hold a valid MSP (in SRAM) and a Thumb
  reset address inside the APP region.

Pack a factory image with the existing tool (the SEC variant needs the test
private key from `quilla/tools/_keytest/private.hex`):

```
python tools\qboot_image.py pack --boot <QBOOT_SEC.bin> ^
  --app C:\zph\build\zephyr\zephyr.bin --out combined.bin ^
  --key C:\zph\quilla\tools\_keytest\private.hex
python tools\qboot_image.py verify --image combined.bin
```

## 6. On-target upgrade

Flash QBOOT first, then use the host updater from the `quilla/` clone:

```
python C:\zph\quilla\tools\quilla_host_updater.py COM7 C:\zph\build\zephyr\zephyr.bin --key C:\zph\quilla\tools\_keytest\private.hex
```

The completion verdict is `ACK_SIGN 0x84` (SEALED/SEC) or `ACK_END 0x83`
(CHECK). The `[QAPP]` boot stamp is only a non-fatal confirmation; the
appliance prints a complete banner literal, so it should match.

Verify on hardware: banner with no garbling (160 MHz clock handover),
`part` -> `app1`, `swqboot` -> `[BOOT]` banner, then a second full QIAP
upgrade with the new image. Use "Erase Sectors" rather than full-chip erase
when flashing with Keil, so the META manifest is not wiped.

## 7. Known risks before the first build

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
