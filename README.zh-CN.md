# Quilla.ZP

**[English](README.md)**

最小演示工程：用 **Quilla QBOOT** 在 GD32F502VE（Cortex-M33）上启动一个
**Zephyr RTOS appliance**，替代 Quilla 自带的 Contiki APP。

这是 `Quilla.FR` 的 Zephyr 对应版本。演示的重点是两个镜像之间的边界：不共享
任何头文件或源文件，只约定一组二进制 Flash 接口。

## 目录

| 路径 | 内容 |
| --- | --- |
| `quilla/` | `github.com/JiChiRen/Quilla` 的独立 clone（`develop` 分支），不纳入本仓库版本管理，可随时 pull / merge 上游 |
| `appliance/` | `github.com/GD32-MCU-IOT/gd32_zephyr` 的独立 clone（`main` 分支，Zephyr 4.4 下游树，含 GD32 支持）。保持上游目录结构不变以便 merge，不纳入版本管理 |
| `app/` | 本仓库自有的 out-of-tree Zephyr 应用。所有 Quilla 侧能力均通过 Zephyr 注册机制接入，不修改任何 Zephyr 上游文件 |
| `doc/` | 架构、注册点、QBOOT 适配、构建与升级说明（中英双语） |
| `tools/` | `check_contract.py`（二进制契约自检）与 `qboot_image.py`（出厂镜像打包） |

两个上游 clone 由 `.gitignore` 排除，重建命令见 `doc/build-and-upgrade.md`。

## 二进制契约

| 项 | 值 |
| --- | --- |
| QBOOT | `0x08000000`，24 KiB |
| META | `0x08006000`，4 KiB（双 2 KiB slot，记录 256 B） |
| APP | `0x08007000` .. `0x0807FFFF`（484 KiB） |
| QAV1 记录 | `0x08007400`（APP 起始 + `0x400`），8 字节，位于受签名保护的镜像内 |
| 串口 | USART0 / PB6 TX / PB7 RX / AF0 / 115200 8N1；QBOOT 侧使用 DMA0 CH4 |
| 主频 | 160 MHz（8 MHz HXTAL + PLL），由 QBOOT 配置，板级 DTS 同步声明 |

QBOOT 设置 `SCB->VTOR = APP_START`，从 APP 镜像前两个字读取 MSP 与复位向量后跳转。
因此 Zephyr 镜像必须从 `0x08007000` 起放置向量表，不能预留镜像头。

## 注册点

appliance 侧的所有行为都通过 Zephyr 机制注册，不塞进任何无关的 Zephyr 文件：

| 能力 | Zephyr 机制 | 文件 |
| --- | --- | --- |
| `part` / `version` / `swqboot` 命令 | `SHELL_CMD_REGISTER` | `app/src/quilla_shell.c` |
| `[QAPP]` 启动横幅 | `SYS_INIT` | `app/src/quilla_shell.c` |
| LED 心跳 | `K_THREAD_DEFINE` + `led0` devicetree alias | `app/src/led.c` |
| META flag 提交 | Zephyr flash 驱动 API，`DT_CHOSEN(zephyr_flash_controller)` | `app/src/quilla_meta.c` |
| QAV1 记录 | section 属性 + `zephyr_linker_sources(ROM_START ...)` | `app/src/quilla_secver.c`、`app/linker/quilla-secver.ld` |
| 串口与 Flash 布局 | out-of-tree board（`BOARD_ROOT`）+ devicetree chosen / overlay | `app/boards/gd/gd32f502ve_quilla/`、`app/app.overlay` |
| 版本、几何与分区 | Kconfig | `app/Kconfig`、`app/prj.conf` |

各选择的理由见 `doc/zephyr-integration.md`。

## 验证状态

**编译：已验证。上板：QIAP 全流程升级一次通过（2026-11-09）。** 已在
Windows 原生环境用 Zephyr 4.4（`ZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb`，GNU Arm
Embedded 13.2）完成一次干净的 `west build -b gd32f502ve_quilla`，零告警通过：

- FLASH 42 004 B / 484 KB（8.48 %），RAM 9 112 B / 64 KB（13.9 %）
- `quilla_secver`（QAV1）段精确落在 `0x08007400`，已在 `zephyr.bin` 中核实
  （偏移 0x400 处为 `QAV1` + 安全版本号）
- `CONFIG_FLASH_LOAD_OFFSET=0x7000`，`CONFIG_FLASH_LOAD_SIZE=0x79000`

真机（GD32F502VE，QBOOT V0.11.0002 SEC 模式）已验证：

- 旧 APP `swqboot` → QBOOT → QIAP 完整升级：42004 B / 5.2 s 写入，SIGN 验签
  通过（ACK_SIGN 0x84），防回滚 secver=1 被接受
- QBOOT 跳转后横幅 `[QAPP] Quilla.ZP V1.0.0001` 一行干净输出（160 MHz 时钟
  交接与波特率推导正确，无乱码）；多次冷启动结果一致
- Zephyr shell 正常工作，`help` 列出 `part` / `version` / `swqboot` 等
- ZP 自身 `swqboot`（XIP 下 Zephyr flash 驱动写 META flag + 冷复位）成功回到
  `[BOOT]` 横幅，未报 META 提交失败
- 从 ZP APP 发起的第二次完整 QIAP 升级（同版本 secver=1）再次通过
  ACK_SIGN 0x84，META 双槽记录与防回滚在重复升级下表现正常

Windows 注意事项：路径含空格会同时破坏 CMake/Ninja 与 GCC（`__FILE__`
进入未加引号的汇编段名）。把工程放在不含空格的路径下则完全不受影响；路径
无法调整时，可在配置完成后统一替换为 8.3 短路径绕过。

`python tools/check_contract.py` 对两个 clone 的 22 项检查全部通过，覆盖分区
几何、META 记录布局、flag 取值、secver 魔数、串口接线与 CRC 参考向量。每次
拉取上游后都应重跑。

移植到其它 MCU 时需注意：`tools/qboot_image.py` 中的容量按 GD32F502VE
（512 KiB Flash / 64 KiB SRAM）固化。常量表与必须同步修改的位置见
[doc/mcu-porting.zh-CN.md](doc/mcu-porting.zh-CN.md)。

## 许可

本仓库自有文件采用 BSD-3（见 `LICENSE`）。两个上游 clone 保留各自许可
（Quilla BSD-3、Zephyr Apache-2.0），本仓库不重新分发它们。
