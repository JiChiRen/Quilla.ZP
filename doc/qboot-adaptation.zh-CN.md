# GD32F502VE 上的 QBOOT 适配

**[English](qboot-adaptation.md)**

与 `Quilla.FR` 不同，**本项目不需要给 QBOOT 打任何补丁**。GD32F502VE 端口
已经使用 USART0 / PB6-PB7 / AF0 / 115200 / DMA0 CH4，与 Zephyr appliance 的
接线完全一致。因此 `quilla/` 保持 `develop` 分支的字节级干净 clone，
`appliance/` 保持 `main` 分支的干净 clone。

## 1. 拉取上游

```
git clone -b develop https://github.com/JiChiRen/Quilla.git quilla
git clone -b main   https://github.com/GD32-MCU-IOT/gd32_zephyr.git appliance
```

`gd32_zephyr` 是完整的 Zephyr 4.4 下游树（约 820 MB、12.5 万提交）。用
`--filter=blob:none` 部分克隆可在保留完整提交历史（仍可 merge）的同时跳过
历史 blob。两个目录均被本仓库 `.gitignore` 排除。

## 2. QBOOT 对 APP 的要求

| 要求 | 满足位置 |
| --- | --- |
| 向量表位于 `0x08007000`（MSP + 复位向量） | `CONFIG_FLASH_LOAD_OFFSET=0x7000`、`CONFIG_ROM_START_OFFSET=0`、不启用 MCUboot |
| APP 镜像结束于 Flash 末端（`0x0807FFFF`）之前 | `CONFIG_FLASH_LOAD_SIZE=0x79000` |
| QAV1 记录位于 `0x08007400` | `.quilla_secver` 段 + `ROM_START` 链接片段 |
| META 记录 QMTL/QMF1，CRC 与 flag 一致 | `app/src/quilla_meta.c` |
| APP 对 `part` 回答 `app1`，并接受 `swqboot` | `app/src/quilla_shell.c` |
| USART0 / PB6-PB7 上的 115200 控制台 | out-of-tree 板级 DTS + pinctrl |

QBOOT 设置 `SCB->VTOR = APP_START`，从前两个字装载 MSP 与复位向量，然后
**不复位 RCC** 直接跳转。板级 DTS 声明 160 MHz，使 Zephyr 时钟驱动与 UART
波特率推导和继承的时钟树一致。该时钟交接是必须上板确认的项目之一（见下文
清单）。

## 3. Flash 几何

GD32F502VE bank0 擦除页为 **2 KiB**，按 32 位字编程。META 区 4 KiB 分成两个
2 KiB slot，每个 slot 恰好一个擦除页。记录步长 256 B，以只编程不擦除的方式
追加写入，活动 slot 从不擦除。`app/src/quilla_meta.c` 用 `BUILD_ASSERT` 把
slot 尺寸与 2 KiB 页大小绑定。

QBOOT 的 GD32 flash 例程放在 RAM 中执行以避开读-写冲突；Zephyr 的 flash
驱动是另一套实现。这是待上板验证项，不能假设两者行为一致。

## 4. 板级复用的边界

上游 Zephyr 树有 `soc/gd/gd32/gd32f50x/` 与 `gd32f503v_eval` 等板级定义，
但**没有 GD32F502VE 的板级或 SoC 定义**。out-of-tree 板复用 `gd32f503` 的
SoC 描述，只在 DTS 中覆盖型号相关值：

| 项 | 上游 `gd32f503vg` | 本板 |
| --- | --- | --- |
| Flash | 1024 KiB | 512 KiB |
| SRAM | 128 KiB | 64 KiB |
| 主频 | 252 MHz | 160 MHz |
| USART0 引脚 | PA9 / PA10 | PB6 / PB7（AF0） |

复用同系列 SoC 描述是务实的移植步骤，**不等于声称 F502VE 与 F503V 寄存器
映射相同**。外设基址、RCU 时钟门控与 FMC 控制器都需在目标板上核对后才能
用于演示以外的场景，目前尚未验证。

`USART0_TX_PB6` / `USART0_RX_PB7`（AF0）来自 `appliance/west.yml` 声明的
`hal_gigadevice` 模块，存在于 `GD32-MCU-IOT/hal_gigadevice_zephyr`，不在
Zephyr 主树中，因此构建前 `west update` 必须成功。

## 5. 上板验证清单

尚未执行。发布前需完成：

1. `west build` 使用 out-of-tree 板与锁定的 Zephyr 树构建成功。
2. 检查 map 文件：`quilla_zp_secver` 位于 `0x08007400`，`.text` 在其后，
   `_vector_start` 为 `0x08007000`。
3. 上电串口打印 `[QAPP] Quilla.ZP V1.0.0001` 且无乱码（确认 160 MHz 时钟
   交接与 115200 波特率）。
4. `part` 返回 `app1`；Zephyr shell 提示符不含 ANSI 转义。
5. `swqboot` 写入 META flag，QBOOT 打印 `[BOOT] ...` 回来。
6. 分别用 CHECK、SEALED/SEC 完成一次完整 QIAP 升级，收到完成码且新 APP 启动。
7. 每次拉取上游后 `python tools/check_contract.py` 通过。
