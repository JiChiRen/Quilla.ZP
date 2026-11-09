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

**本应用尚未编译，也未上板运行。** 创建该工程的工作环境为 Windows，没有
`west`、Zephyr SDK 或 Linux 构建环境。所有上游 API、Kconfig 符号、devicetree
binding 与 CRC 行为均已对照锁定的 Zephyr 4.4 源码核实，但仍需完成首次
`west build` 与真机验证。构建命令与验证清单见 `doc/build-and-upgrade.md`。

`python tools/check_contract.py` 对两个 clone 的 22 项检查全部通过，覆盖分区
几何、META 记录布局、flag 取值、secver 魔数、串口接线与 CRC 参考向量。每次
拉取上游后都应重跑。

移植到其它 MCU 时需注意：`tools/qboot_image.py` 中的容量按 GD32F502VE
（512 KiB Flash / 64 KiB SRAM）固化。常量表与必须同步修改的位置见
[doc/mcu-porting.zh-CN.md](doc/mcu-porting.zh-CN.md)。

## 许可

本仓库自有文件采用 BSD-3（见 `LICENSE`）。两个上游 clone 保留各自许可
（Quilla BSD-3、Zephyr Apache-2.0），本仓库不重新分发它们。
