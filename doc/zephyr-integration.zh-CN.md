# Zephyr 接入：注册点

**[English](zephyr-integration.md)**

两个上游仓库都是干净 clone。新增功能不得修改 Zephyr 内核、驱动或 sample 文件：
appliance 是 out-of-tree Zephyr 应用，全部通过 Zephyr 提供的扩展机制接入。

## Shell 命令 — `SHELL_CMD_REGISTER`

`app/src/quilla_shell.c` 注册 `part`、`version`、`swqboot`，对应上位机使用的
Quilla APP shell 协议：

- `part` 回答 `app1`，让上位机确认当前是运行中的 APP。
- `swqboot` 打印 `[QAPP] switching to QBOOT...`，追加一条 `flag=QBOOT` 的 META
  记录，然后调用 `sys_reboot(SYS_REBOOT_COLD)`；QBOOT 随后停留在自身的 shell，
  不再跳回 APP。
- META 写入失败时命令报错且**不复位**。半提交的 flag 不能当作交接成功。

`CONFIG_SHELL_PROMPT_UART="> "` 关闭 ANSI 转义与颜色输出，保证上位机的纯文本
行解析器能直接读到应答。

Zephyr shell 自带 `help` 与 `kernel` 命令组，不重复实现。

## 启动横幅 — `SYS_INIT`

`[QAPP] <name> V<version>` 横幅由 `POST_KERNEL` 优先级 99 的 `SYS_INIT` 钩子
打印，早于串口 shell 后端（`APPLICATION` 级初始化）接管 UART。它不从 `main()`
输出，因此不依赖应用线程是否被调度。

`[QAPP] switching to QBOOT...` 有意保留为镜像中的完整字面量：上位机工具从
镜像二进制中提取升级后的启动戳候选串。

## LED 心跳 — `K_THREAD_DEFINE` + devicetree

`app/src/led.c` 用静态线程注册，LED 来自 devicetree 的 `led0` alias。alias
不存在时该文件不产生任何代码，应用仍可构建运行。参考板的 LED 引脚不属于
QBOOT 契约，此处不臆造引脚；按实际板卡在 `app/app.overlay` 增加 `led0` 即可。

## META 记录写入 — flash API 与 chosen 节点

`app/src/quilla_meta.c` 通过 `DT_CHOSEN(zephyr_flash_controller)` 获取 flash
设备，使用 `flash_read` / `flash_erase` / `flash_write`。只追加一条改写交互
flag 的记录，manifest、seal 与防回滚 floor 原样继承。活动 slot 从不擦除，
掉电不会破坏唯一有效记录。

记录布局、魔数、flag 取值与 CRC 均在本地定义（不引用 Quilla 头文件），与
`quilla-qboot-meta.c` 二进制兼容；`tools/check_contract.py` 在每次拉取上游后
比对两侧。

CRC-32 在本地实现 IEEE 802.3 反射形式，与 QBOOT 的 `meta_crc32` 及 Zephyr 的
`crc32_ieee` 逐位一致（已用参考向量验证），避免依赖 Zephyr 4.4 中带条件的
`CRC_DRIVER_HAS_CRC32_IEEE`。

Zephyr flash 偏移相对 Flash 基址，QBOOT 分区常量是绝对地址，由
`flash_offset()` 转换。

## 安全版本记录 — section + 链接片段

QBOOT 在固定地址 `APP_START + 0x400` 读取 8 字节 `QAV1` 记录，不依赖符号表。
`app/src/quilla_secver.c` 用 `Z_GENERIC_SECTION` 把记录放进 `.quilla_secver`
输入段；`app/linker/quilla-secver.ld` 通过
`zephyr_linker_sources(ROM_START SORT_KEY 0x3secver ...)` 在第一个 ROM 输出段
内把该段钉到绝对地址。后续 ROM 段因此从记录之后开始，不会重叠——与 Quilla
自身 QAPP 链接脚本的布局一致。

版本取自共享头文件 `quilla/os/sys/quilla-version.h` 的
`QUILLA_APP_SECURITY_VERSION`（与 Quilla 自身 QAPP/QBOOT 同一个版本源，可在构建期用
`-DQUILLA_APP_SECURITY_VERSION=<n>` 覆盖），不由上位机传入，也不设 Zephyr
Kconfig 旋钮；记录位于受签名保护的镜像内。

`app/Kconfig` 里 `QUILLA_ZP_META_BASE`、`QUILLA_ZP_META_SIZE`、
`QUILLA_ZP_APP_START`、`QUILLA_ZP_SECVER_OFFSET` 四个几何值，是 QBOOT 侧
`quilla-qboot-hal.h` / `quilla-version.h` 常量的**刻意复制**：这是 hybrid
架构（裸机 QBOOT + Zephyr APP，两者不共享构建系统）下保留上游 Zephyr 树
零改动的取舍。它们必须人工对齐，改动时按
[MCU 移植说明](mcu-porting.zh-CN.md) 第 2 节的清单逐处同步并跑第 4 节验证；
只改一侧不会在编译期报错，会静默错开分区。

## 串口、容量与时钟 — out-of-tree board

`app/boards/gd/gd32f502ve_quilla/` 是 HWMv2 out-of-tree 板级定义，用
`-DBOARD_ROOT=app` 选中。复用上游 `gd32f50x` SoC 描述，只覆盖型号相关值：
512 KiB Flash、64 KiB SRAM、160 MHz，以及 USART0 重映射到 PB6/PB7（AF0）、
115200。`chosen` 指定 console、shell UART 与 flash controller；
`app/app.overlay` 留给不属于 QBOOT 契约的板级接线。

`CONFIG_FLASH_LOAD_OFFSET=0x7000` 与 `CONFIG_FLASH_LOAD_SIZE=0x79000` 把镜像
定位到 `0x08007000`。`CONFIG_ROM_START_OFFSET=0`、
`CONFIG_BOOTLOADER_MCUBOOT=n` 保证向量表位于镜像最开头，符合 QBOOT 跳转要求。

## 为什么不做成 Zephyr module 或 in-tree sample

把 `app/` 放进 `appliance/samples/` 会让上游 `git pull` / merge 与本地改动冲突。
改用 module（`ZEPHYR_EXTRA_MODULES`）会为一个应用引入额外的 manifest 与
Kconfig 间接层，没有收益：本工程只有一个应用，全部通过标准应用 CMake 入口
注册。两个上游 clone 保持字节级干净。
