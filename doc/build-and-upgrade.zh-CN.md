# 构建与升级说明

**[English](build-and-upgrade.md)**

> **状态**：已完成干净的 Zephyr 构建（Windows 原生 + gnuarmemb，零告警），产物在
> `app/build-w/zephyr/`，secver 段位于 `0x08007400`。**真机验证已闭环**：
> 2026-11-09（QBOOT_SECURED）QIAP 升级两次 `ACK_SIGN 0x84`、横幅无乱码、
> 多次冷启动一致、shell 正常、ZP 自身 `swqboot` 成功回到 `[BOOT]`；
> 2026-11-12（GD32 真 OTP 两阶段）`OTP_COUNTER` 1→2、`APP_END=0x0807FFFF`
> 不钳位、低版本镜像被 `NAK 0x0A ROLLBACK` 拒绝、同版本再升合法。
> 第 5、6 节保留作为复验清单。

## 1. 主机工具（Windows 原生）

Zephyr 官方支持 Windows 10/11 原生开发。上游明确**不推荐 WSL**（WSL 内烧录
与调试不可靠）；本机 `wsl.exe` 还被本地安全策略禁止，因此 Windows 原生是唯一
路线。

本机已有 `winget`，用它安装依赖后重新打开终端刷新 PATH：

```
winget install Kitware.CMake Ninja-build.Ninja oss-winget.gperf `
  Python.Python.3.12 Git.Git oss-winget.dtc wget 7zip.7zip
```

| 工具 | 要求版本 | 本机现状 |
| --- | --- | --- |
| CMake | >= 3.28.0 | 无 |
| Ninja | 较新版本 | 无 |
| Python | **强烈推荐 3.12** | `py -3.12` 可用（uv 装的 3.12.14）；PATH 上的 `python` 是 3.13.14，不要用 |
| Devicetree compiler (dtc) | >= 1.4.6 | 无 |
| gperf | 较新版本 | 无 |
| Git | 较新版本 | 有 |
| wget / 7-Zip | 较新版本 | 无 |
| west | 较新版本（`pip install west`） | 无 |

Zephyr 官方提示：较新的 Python 在 Windows 上安装依赖包可能失败。用 3.12
启动器显式创建虚拟环境：

```
cd %HOMEPATH%
py -3.12 -m venv zephyrproject\.venv
zephyrproject\.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install west
```

PowerShell 激活需要先执行
`Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`。

## 2. 交叉编译器：两条路线

**路线 A（推荐用于首次快速验证）：复用已有 GNU Arm 工具链。** 本机已有
`C:\toolchains\Arm_GNU_Toolchain_arm-none-eabi_13.2_Rel1` 下的 Arm GNU
Toolchain 13.2.1（含 newlib）。Zephyr 4.4 仍保留 `gnuarmemb` 与
`cross-compile` 工具链变体，因此无需下载 SDK：

```
set ZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb
set GNUARMEMB_TOOLCHAIN_PATH=C:\toolchains\Arm_GNU_Toolchain_arm-none-eabi_13.2_Rel1
```

等价写法是 `ZEPHYR_TOOLCHAIN_VARIANT=cross-compile` 加
`CROSS_COMPILE=C:\toolchains\...\bin\arm-none-eabi-`。上游说明这类变体的
机制受支持，但**未针对任意编译器做官方测试**；Zephyr SDK 才是测试过的路径。

**路线 B（上游默认，约 1–2 GB）：Zephyr SDK 1.0.1 Windows 包。** 锁定树的
`SDK_VERSION` 为 `1.0.1`，SDK 提供 `_windows-x86_64_gnu` 包，内含
`arm-zephyr-eabi`：

```
west sdk install
set ZEPHYR_TOOLCHAIN_VARIANT=zephyr
```

路线 A 失败、或需要可复现的上游测试工具链时改用路线 B。

## 3. 构建命令

构建环境自包含在仓库的 `.venv`（Python 3.12 / pip 版 cmake / ninja），交叉
编译器用 gnuarmemb（`C:\toolchains\Arm_GNU_Toolchain_arm-none-eabi_13.2_Rel1`）。
以下命令以 Quilla.ZP 仓库根为当前目录：

```
set ZEPHYR_BASE=%CD%\appliance
set BOARD_ROOT=%CD%\app
set ZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb
set GNUARMEMB_TOOLCHAIN_PATH=C:\toolchains\Arm_GNU_Toolchain_arm-none-eabi_13.2_Rel1
set ZEPHYR_MODULES=%CD%\modules\hal\gigadevice;%CD%\modules\hal\cmsis_6
.venv\Lib\site-packages\cmake\data\bin\cmake.exe -B app\build-w -GNinja -S app -DBOARD=gd32f502ve_quilla -DBOARD_ROOT=app -DPython3_EXECUTABLE=%CD%\.venv\Scripts\python.exe -DCMAKE_MAKE_PROGRAM=%CD%\.venv\Scripts\ninja.exe
.venv\Scripts\ninja.exe -C app\build-w
python tools\check_contract.py
```

`Python3_EXECUTABLE` 与 `CMAKE_MAKE_PROGRAM` 必须显式指向 `.venv`：否则 cmake
会抓到 PATH 上的 Python 3.13（缺 Zephyr 依赖）或找不到 ninja。产物为
`app\build-w\zephyr\zephyr.bin`；后续命令均以仓库根为当前目录。

`BOARD_ROOT` 必须是**包含** `boards/` 的目录，即 `app`，不是板目录本身。
`app/CMakeLists.txt` 使用
`find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})`，因此 `ZEPHYR_BASE`
决定选用哪棵 Zephyr 树。

## 4. 烧录前验证镜像

```
arm-none-eabi-nm -n app\build-w\zephyr\zephyr.elf | findstr quilla_zp_secver
arm-none-eabi-objdump -h app\build-w\zephyr\zephyr.elf
```

检查项：

- `_vector_start` 为 `0x08007000`——QBOOT 从这里读取 MSP 与复位向量。
- `quilla_zp_secver` 位于 `0x08007400`，`.text` 在其**之后**开始。
- 镜像落在 `0x08007000` .. `0x0807FFFF` 范围内。
- `zephyr.bin` 前 8 字节是合法 MSP（位于 SRAM）与 APP 区内的 Thumb 复位地址。

用现有工具合成出厂镜像（SECURED 变体需要
`quilla/tools/_keytest/private.hex` 测试私钥）：

**工具的 `FLASH_SIZE` / `APP_SIZE` / `RAM_SIZE` 是芯片相关配置**，此处按
GD32F502VE（512 KiB Flash / 64 KiB SRAM）设置。移植到其它 MCU 时，常量表、
QBOOT 与 APP 侧必须同步修改的位置，以及与 Quilla.FR 的对照，见
[MCU 移植说明](mcu-porting.zh-CN.md)。

```
python tools\qboot_image.py pack --boot <QBOOT_SECURED.bin> ^
  --app app\build-w\zephyr\zephyr.bin --out combined.bin ^
  --key quilla\tools\_keytest\private.hex
python tools\qboot_image.py verify --image combined.bin
```

### 抬高固件安全版本

`QUILLA_APP_SECURITY_VERSION` 的唯一来源是共享头
`quilla/os/sys/quilla-version.h`（默认 `1U`），位于受签名保护的镜像内，
上位机不传版本，ZP appliance 也不设 Zephyr Kconfig 旋钮。发布不可回滚的
固件时在构建期覆盖该宏，再重新签名升级：

```
cmake -B app/build-w ... -DEXTRA_CFLAGS=-DQUILLA_APP_SECURITY_VERSION=2
ninja -C app/build-w
```

覆盖值只留在本次 build 目录的 CMake cache：不带该参数重新配置会退回 `1U`。
验证：`zephyr.bin` 偏移 `0x400` 为 `QAV1`、`0x404` 为新版本值；升级后
`secver` 应显示对应 `FW_SECVER`。版本抬高**不属于分区改动**，无需同步
`app/Kconfig` 几何；分区几何的人工对齐契约见
[MCU 移植说明](mcu-porting.zh-CN.md) 第 2 节。

## 5. 真机升级

先烧 QBOOT，再使用 `quilla/` clone 中的上位机：

```
python quilla\tools\quilla_host_updater.py COM7 app\build-w\zephyr\zephyr.bin --key quilla\tools\_keytest\private.hex
```

完成判据是 `ACK_SIGN 0x84`（SEALED/SECURED）或 `ACK_END 0x83`（CHECK）。
`[QAPP]` 启动戳只是非致命的二次确认；本 appliance 打印完整 banner 字面量，
应能匹配。

上板需验证：横幅无乱码（160 MHz 时钟交接）、`part` -> `app1`、
`swqboot` -> `[BOOT]` 横幅，随后用新镜像完成第二次完整 QIAP 升级。用 Keil
烧录时选「Erase Sectors」而非全片擦除，避免抹掉 META manifest。

## 6. 已知风险与复验清单

> 以下为集成期登记项。11-09 / 11-12 的真机验证已覆盖 QIAP 链路、时钟交接、
> XIP 下 META 写入与 secver 落位；但 SoC 描述复用的寄存器级核对等项目未逐项
> 单独复核，故保留为清单，不改写为"已验证"。

- 为 GD32F502VE 复用 `gd32f503` SoC 描述尚未验证；外设地址、RCU 门控与
  FMC 行为需上板核对。
- Zephyr 的 GD32 flash 驱动与 QBOOT 的 RAM 常驻 FMC 例程是不同实现；
  XIP 下写 META 需验证。
- 必须检查生成的链接脚本是否包含 `ROM_START` 片段：若启用 CMake 链接脚本
  生成器而非 LD 模板，`snippets-rom-start.ld` 不会被消费。secver 未落在
  `0x08007400` 时固定 `CONFIG_LD_LINKER_TEMPLATE=y`。
- pinctrl 头文件名含括号，需确认 Windows 上的 C 预处理器能正确解析。
