# 把出厂镜像几何配置移植到另一颗 MCU

**[English](mcu-porting.md)**

`tools/qboot_image.py` 负责合成整片镜像（QBOOT + META + APP）。其中的分区常量
分为三类。移植到新 MCU 时只需修改**芯片相关组**，然后同步 QBOOT 侧与 APP 侧的
对应定义。本文即移植清单。

`Quilla.FR`（PY32F040xB）使用同一个工具，下面同时列出两套配置以便直接对照。

## 1. `tools/qboot_image.py` 中的常量

### 芯片相关 —— 必须修改

| 常量 | 含义 | Quilla.ZP（GD32F502VE） | Quilla.FR（PY32F040xB） |
| --- | --- | --- | --- |
| `FLASH_BASE` | Flash 基址 / 整片镜像烧录地址 | `0x08000000` | `0x08000000` |
| `FLASH_SIZE` | Flash 总容量；**同时决定 `combined.bin` 的精确字节长度** | `0x00080000`（512 KiB） | `0x00020000`（128 KiB） |
| `APP_SIZE` | APP 区长度，约束 `image_len` | `0x00079000`（484 KiB） | `0x00019000`（100 KiB） |
| `RAM_START` | SRAM 基址，初始 MSP 校验下界 | `0x20000000` | `0x20000000` |
| `RAM_SIZE` | SRAM 容量，**初始 MSP 校验上界** | `0x00010000`（64 KiB） | `0x00004000`（16 KiB） |

必须满足两个关系：

```
APP_SIZE   = FLASH_SIZE - (APP_START - FLASH_BASE) = FLASH_SIZE - 0x7000
SOC_FLASH_END（QBOOT soc.h） = FLASH_BASE + FLASH_SIZE - 1
```

> **`APP_SIZE` ≠ 运行时 APP 区可用长度**：表中 `APP_SIZE` 是工具按芯片 Flash
> 容量算出的物理分区长度（`combined.bin` 与 `image_len` 上界）。启用受写保护
> NV 计数器 后，QBOOT 把 `QUILLA_QBOOT_APP_END` 钳到计数区基址前一字节
> （PY32 → `0x0801DFFF`，可用 `0x17000`），比物理分区少顶部一个扇区；见主仓
> `doc/anti-rollback-counter.zh-CN.md` §2.1。二者不矛盾；改分区时仍按第 2 节
> 清单人工对齐。

本板 `SOC_FLASH_END = 0x0807FFFF`，GD32 QBOOT 构建传
`-DQUILLA_QBOOT_RAM_SIZE=0x00010000U`，使工具的 64 KiB MSP 上界与 QBOOT
一致。两者不符时，初始 MSP 位于 SRAM 顶端的合法 Zephyr 镜像也可能被
`quilla_qboot_hal_app_image_valid()` 判为非法。

`FLASH_SIZE` 不只是注释：工具按 `bytearray(b"\xFF" * FLASH_SIZE)` 分配，
`verify_combined()` 会拒绝任何其它长度的镜像。

### 分区常量 —— 仅在改动分区布局时才改

| 常量 | 值 | 说明 |
| --- | --- | --- |
| `QBOOT_SIZE` | `0x00006000`（24 KiB） | QBOOT 镜像预算，由 QBOOT 链接脚本固定 |
| `META_BASE` | `0x08006000` | 紧接 QBOOT 之后 |
| `META_SIZE` | `0x00001000`（4 KiB） | 双 2 KiB slot |
| `APP_START` | `0x08007000` | 必须按擦除页对齐（GD32F502VE 为 2 KiB） |
| `META_OFFSET` / `APP_OFFSET` | 推导值 | `*_BASE - FLASH_BASE`；`FLASH_BASE` 改变时同步 |

这四个常量在 Quilla.ZP 与 Quilla.FR 中**完全相同**。正是保持不变，才让 QBOOT
的策略层与 MCU 无关。若要移动分区，必须同时修改：QBOOT 构建宏、APP 的链接/
Zephyr 配置、APP 内 META 写入模块，以及上位机的 `--meta-base` / `--app-start`。

### 协议常量 —— 禁止修改

`RECORD_SIZE`（256 B）、`META_SLOT_SIZE`（2 KiB）、`SECVER_OFFSET`（`0x400`）、
`SECVER_MAGIC`（`QAV1`）、QMTL/QMF1 魔数与字段偏移、CRC-32（IEEE 802.3
反射形式）、flag 取值、manifest 的哈希/签名布局，以及 36 字节签名描述子。
它们构成与 QBOOT 的二进制契约，与 MCU 无关；`tools/check_contract.py` 会对
两个上游 clone 逐项比对。

## 2. 同一组数值必须重复出现的位置

### 人工对齐是有意的设计取舍（hybrid 架构）

Quilla.ZP 是 hybrid 架构：QBOOT 是裸机 C（Keil / GCC 构建，常量来自
`quilla/os/sys/quilla-version.h`、`quilla-qboot-hal.h` 及构建宏），APP 是
Zephyr out-of-tree 应用（常量来自 `app/Kconfig`、板级 DTS 与 linker 片段），
上位机打包工具 `tools/qboot_image.py` 另有自己的 Python 常量。三者不共享构建
系统，也没有共同生成的配置头。保持上游 Zephyr 树零改动、QBOOT 不引入
devicetree 依赖是刻意选择，代价就是**分区几何与协议常量必须在多处重复出现，
靠人工对齐**。这是受控的设计取舍，不是遗漏，也不是待重构的缺陷。

按归属分三类：

| 类别 | 落点 | 是否要人工同步 |
| --- | --- | --- |
| 功能开关 | Zephyr：`app/prj.conf`；QBOOT：构建宏 | 否，两侧各管各的 |
| 分区几何 / 协议常量 | 无单一事实源，以下表为唯一清单 | **是**，改一处必须改全部（见下表） |
| 固件安全版本 | 共享头 `quilla/os/sys/quilla-version.h` 的 `QUILLA_APP_SECURITY_VERSION` | 否；发布时构建期 `-DQUILLA_APP_SECURITY_VERSION=<n>` 覆盖，**不设 ZP 专用 Kconfig 旋钮** |

只改一边的后果是**静默错开**——QBOOT 读错 META 槽或 `QAV1` 记录、QIAP
写越界、验签失败——编译期不会显性报错。因此任何分区改动都必须：
① 逐行核对下表并在所有列出的位置同步修改；② 重跑第 4 节验证命令；
③ 在 Quilla.ZP 与 Quilla.FR 两个仓重复同样的核对；④ 上板用 `pinfo`
复核 `APP_START` / `APP_END`。版本号的抬高不属于分区改动，只需在构建期
覆盖共享头宏并重新签名。

| 层 | 文件 / 符号 | 要设置的值 |
| --- | --- | --- |
| QBOOT | `quilla/arch/cpu/arm/<mcu>/soc.h` → `SOC_FLASH_END` | `FLASH_BASE + FLASH_SIZE - 1`（本板 `0x0807FFFF`）；QBOOT 由此推导 `APP_END`，缺失时直接 `#error` |
| QBOOT | 构建宏 `QUILLA_QBOOT_RAM_START`、`QUILLA_QBOOT_RAM_SIZE` | 必须与工具的 `RAM_START` / `RAM_SIZE` 相等。GD32 构建传 `-DQUILLA_QBOOT_RAM_SIZE=0x00010000U`；PY32 用 16 KiB 默认值 |
| QBOOT | 构建宏 `QUILLA_QBOOT_PAGE_SIZE` | 物理擦除页：GD32F502VE 为 **2 KiB**，PY32F040 为 **256 B**。决定 QIAP 页合并与 META 追加策略 |
| QBOOT | 构建宏 `QUILLA_QBOOT_APP_START`、`QUILLA_QBOOT_APP_END`；META 几何取 `QUILLA_QBOOT_META_BASE` / `QUILLA_QBOOT_META_SIZE` | 与 `APP_START` / `META_BASE` / `SOC_FLASH_END` 一致 |
| 上位机打包 | `tools/qboot_image.py` 上述常量 | `FLASH_SIZE`、`APP_SIZE`、`RAM_SIZE`、`FLASH_BASE` |
| APP（Zephyr） | `app/prj.conf` | `CONFIG_FLASH_LOAD_OFFSET=0x7000`、`CONFIG_FLASH_LOAD_SIZE=APP_SIZE`（`0x79000`） |
| APP（Zephyr） | `app/boards/gd/gd32f502ve_quilla/gd32f502ve_quilla.dts` | `&flash0 reg = <FLASH_BASE DT_SIZE_K(512)>`、`&sram0 reg = <RAM_START DT_SIZE_K(64)>`、`clock-frequency` |
| APP（Zephyr） | `app/Kconfig` | `QUILLA_ZP_META_BASE`、`QUILLA_ZP_META_SIZE`、`QUILLA_ZP_APP_START`、`QUILLA_ZP_SECVER_OFFSET` |
| APP（FreeRTOS） | `appliance/gcc/py32f040xb.ld`（FR） | `FLASH ORIGIN = 0x08007000`、`LENGTH = APP_SIZE`；`RAM ORIGIN = RAM_START`、`LENGTH = RAM_SIZE` |
| APP（Keil） | `appliance/MDK-ARM/*.uvprojx`（FR） | IROM1 = `0x08007000` / `APP_SIZE`；IRAM1 = `RAM_START` / `RAM_SIZE`；带 `QAPP_BUILD` |
| APP | META 写入模块的擦除页常量 | ZP：`app/src/quilla_meta.c` 的 `QZP_ERASE_PAGE_SIZE`（2048），带 `BUILD_ASSERT(slot == page)`；FR：`appliance/Src/app_qboot_meta.c` 的 `QB_PAGE_SIZE`（256） |
| APP | secver 段 | `APP_START + 0x400`，每个 APP 构建都要产出，且被签名覆盖。ZP 由 `app/linker/quilla-secver.ld` 钉住 |
| 跨镜像（QBOOT / ZP APP / FR APP） | `quilla/os/sys/quilla-version.h` → `QUILLA_APP_SECURITY_VERSION` | 默认 `1U`；发布不可回滚固件时构建期 `-DQUILLA_APP_SECURITY_VERSION=<n>` 覆盖。ZP 侧无 Kconfig 旋钮，见 `doc/zephyr-integration.zh-CN.md` 安全版本节 |

## 3. 移植步骤

1. 从数据手册记录 Flash 基址/容量、SRAM 基址/容量，以及**物理擦除页大小**。
2. 在工具中设置 `FLASH_BASE`、`FLASH_SIZE`、`RAM_START`、`RAM_SIZE`，重算
   `APP_SIZE = FLASH_SIZE - 0x7000`。
3. 在新 `arch/cpu/arm/<mcu>/soc.h` 补齐 `SOC_FLASH_END`，并为每个 QBOOT
   target（CHECK / SEALED / SECURED，GCC 与 Keil）设置上表所列构建宏。
4. 更新 Zephyr 的 `FLASH_LOAD_*`、板级 DTS `reg` 与 `app/Kconfig` 几何
   （或 FreeRTOS/Keil 的链接设置）；secver 记录保持在 `+0x400`。
5. 更新 APP META 写入模块的擦除页常量。GD32 的 2 KiB 页恰好等于一个 META
   slot；PY32 的 256 B 页恰好等于一条记录。追加规则是「活动 slot 永不擦除」，
   页大小不一致会静默写坏日志。
6. 编译 QBOOT 与 APP，烧录前先校验。

## 4. 验证命令

```
python tools/check_contract.py
python tools/qboot_image.py selftest
python tools/qboot_image.py pack --boot <QBOOT.bin> --app <zephyr.bin> \
    --out combined.bin --key <private.hex>
python tools/qboot_image.py verify --image combined.bin
```

`check_contract.py` 对两个上游 clone 比对分区几何、META 布局、flag 取值、
secver 魔数与串口接线共 22 项，每次拉取上游后都应重跑。
`qboot_image.py selftest` 覆盖 CRC、记录布局、向量表边界与签名出厂镜像生成。

另外用 `nm` / `objdump` 检查 Zephyr ELF：初始 MSP 落在
`[RAM_START, RAM_START + RAM_SIZE)` 内，复位向量是 APP 区内的 Thumb 地址，
`_vector_start` 为 `APP_START`，`QAV1` 记录位于 `APP_START + 0x400`；用
`zephyr.bin` 偏移 `0x400` 处的 8 字节确认 `QAV1` 魔数与版本值。分区几何
变更后还须上板执行 `pinfo` 复核 `APP_START` / `APP_END`，并在 ZP、FR 两个
仓各重跑一次本节全部命令。

## 5. 时钟交接是另一件事

几何不是唯一的芯片相关项。QBOOT **不复位 RCC** 直接跳转，Quilla.FR 曾因 HAL
用陈旧的 `SystemCoreClock` 变量计算波特率而出现 6 倍偏差。本项目在板级 DTS
声明 160 MHz 与 QBOOT 继承的时钟树对齐；新移植必须确认继承时钟与 Zephyr 的
波特率推导一致。该项已列入 `doc/qboot-adaptation.md` 的上板验证清单，目前
尚未验证。
