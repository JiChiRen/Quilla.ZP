# 架构

**[English](architecture.md)**

## 两个镜像，一颗 MCU

| | QBOOT | appliance（APP） |
| --- | --- | --- |
| 源码 | `quilla/`（上游 clone，零改动） | `app/`（out-of-tree Zephyr 应用） |
| 运行时 | Quilla 协作式进程，无堆 | Zephyr 4.4 内核，抢占式线程 |
| Flash | `0x08000000` .. `0x08005FFF` | `0x08007000` .. `0x0807FFFF` |
| 串口驱动 | `quilla/arch/cpu/arm/gd32f502ve/shellport.c` | Zephyr `gd,gd32-usart` + 串口 shell 后端 |
| 控制台 | QBOOT shell + QIAP 二进制协议 | Zephyr shell（`part`、`version`、`swqboot`） |

两个镜像都使用 USART0 / PB6 TX / PB7 RX / AF0 / 115200，一个连接器同时承担
正常运行与固件升级。QBOOT 用 DMA0 CH4 做 CIRCULAR 接收；appliance 使用
Zephyr 的中断驱动 UART。QBOOT 在跳转前关闭 USART0 与 DMA0 CH4 中断并停止
DMA 通道，appliance 因此从干净的外设状态启动。

## 零代码耦合

QBOOT 不引用 appliance 的任何头文件或源文件，appliance 也不引用 Quilla 的
任何头文件或源文件。双方独立实现同一组契约，由 `tools/check_contract.py`
比对：

| 契约 | QBOOT 侧 | Appliance 侧 |
| --- | --- | --- |
| 分区 | `quilla-qboot-hal.h` 的 `QUILLA_QBOOT_META_BASE` / `_SIZE` | Kconfig `QUILLA_ZP_META_*` / `QUILLA_ZP_APP_START` |
| META 记录 | QMTL + QMF1，256 B，CRC-32（IEEE 802.3 反射） | `app/src/quilla_meta.c`，本地常量与 CRC |
| META flag | `quilla-qboot-flag.h` 的 `APP1` / `QIAP` / `QBOOT` | `app/src/quilla_meta.h` 的 `QUILLA_ZP_FLAG_*` |
| secver | `APP_START + 0x400` 处的 `QAV1` + 版本 | 同地址的 `.quilla_secver` 段 |
| 串口 | USART0 / PB6-PB7 / 115200 | 板级 DTS + pinctrl overlay |
| 主频 | 160 MHz，8 MHz HXTAL + PLL | 板级 DTS `clock-frequency = <DT_FREQ_M(160)>` |

## 启动与升级时序

1. QBOOT 读取 META 日志，manifest 有效时跳转到 `0x08007000`。
2. Zephyr 镜像的向量表位于该地址；自身启动流程把 VTOR 设为链接后的向量表，
   与 QBOOT 已写入的值一致。
3. `SYS_INIT` 钩子打印 `[QAPP] Quilla.ZP V1.0.0001`，串口 shell 后端就绪。
4. 上位机发送 `part`，收到含 `app1` 的应答。
5. 上位机发送 `swqboot`：命令写入 `flag=QBOOT` 并复位；QBOOT 停留在自身
   shell，不再跳回 APP。
6. 上位机发送 `qiap`，执行 ENTER / DATA / END [/ SIGN]。
7. QBOOT 写入 manifest、置 `flag=APP1`、发送完成码并重启进入新 APP。
   完成判据是 ACK；`[QAPP]` 启动戳只是非致命的二次确认。

## 安全边界

CHECK 仅校验传输完整性（SHA-256）。SEALED 与 SEC 增加 Ed25519 认证与防回滚，
并要求 QAV1 记录。Quilla 默认密钥对是公开的，出货前必须替换。

其他 Quilla appliance 使用的 APP 侧 secver 自检属于混淆，不是密码学控制，
本工程未实现。真正的闸门是 QBOOT 的验签加上持久化 floor；绝对防回滚需要
硬件单调计数器（eFuse/OTP），不在本演示范围内。
