#!/usr/bin/env python3
"""生成每品类约 20 条 Mock 商品 JSON，写入 pc_build_agent/data/products.json"""
from __future__ import annotations

import json
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "pc_build_agent" / "data" / "products.json"


def jd_url(sku: str) -> str:
    return f"https://item.jd.com/{sku}.html"


def pick(seq: list[str], i: int) -> str:
    return seq[i % len(seq)]


def main() -> None:
    rng = random.Random(42)
    items: list[dict] = []

    cpus_intel = [
        ("intel_i5_13400", "Intel i5-13400 10核16线程 处理器", 1399),
        ("intel_i5_13490f", "Intel i5-13490F 处理器 无核显", 1449),
        ("intel_i5_13600kf", "Intel i5-13600KF 14核20线程 处理器", 1799),
        ("intel_i5_14600kf", "Intel i5-14600KF 处理器", 1999),
        ("intel_i7_13700kf", "Intel i7-13700KF 处理器", 2599),
        ("intel_i7_14700kf", "Intel i7-14700KF 处理器", 2799),
    ]
    cpus_amd_am5 = [
        ("amd_r5_7500f", "AMD Ryzen 5 7500F 处理器 AM5", 1099),
        ("amd_r5_7600", "AMD Ryzen 5 7600 处理器 AM5", 1299),
        ("amd_r7_7700", "AMD Ryzen 7 7700 处理器 AM5", 1899),
        ("amd_r5_8600g", "AMD Ryzen 5 8600G 处理器 AM5 核显", 1599),
    ]
    cpus_amd_am4 = [
        ("amd_r5_5600", "AMD Ryzen 5 5600 处理器 AM4", 749),
        ("amd_r7_5700x", "AMD Ryzen 7 5700X 处理器 AM4", 1099),
    ]

    for i in range(20):
        if i % 3 == 0:
            sku, name, price = pick(cpus_intel, i // 3)
        elif i % 3 == 1:
            sku, name, price = pick(cpus_amd_am5, i // 3)
        else:
            sku, name, price = pick(cpus_amd_am4, i // 3)
        sku_id = f"mock_cpu_{i+1:03d}_{sku}"
        jitter = rng.randint(-80, 120)
        items.append(
            {
                "sku_id": sku_id,
                "category": "处理器",
                "name": name + (" 盒装" if rng.random() > 0.5 else ""),
                "price": max(399, price + jitter),
                "jd_url": jd_url(sku_id),
                "tags": [],
            }
        )

    coolers = []
    for i in range(20):
        kind = i % 4
        if kind == 0:
            name, base = "利民 PA120 SE 双塔风冷散热器", 169
        elif kind == 1:
            name, base = "利民 Frozen Magic 240 白色一体式水冷", 329
        elif kind == 2:
            name, base = "瓦尔基里 A360 白色 360一体式水冷", 429
        else:
            name, base = "猫头鹰 NH-U12A 静音双塔风冷", 799
        sku_id = f"mock_cooler_{i+1:03d}"
        coolers.append(
            {
                "sku_id": sku_id,
                "category": "散热",
                "name": name,
                "price": base + rng.randint(-30, 60),
                "jd_url": jd_url(sku_id),
                "tags": ["白色"] if "白色" in name else [],
            }
        )
    items.extend(coolers)

    boards = []
    patterns = [
        ("华硕 PRIME B760M-K DDR4 主板", 849, ["DDR4", "B760"]),
        ("华硕 TUF B760M-PLUS WIFI II DDR5 主板", 1299, ["DDR5", "B760"]),
        ("微星 MAG B760M MORTAR DDR5 主板", 1199, ["DDR5", "B760"]),
        ("技嘉 B760M AORUS ELITE DDR5", 1149, ["DDR5", "B760"]),
        ("华硕 ROG STRIX B650-A GAMING WIFI DDR5", 1699, ["DDR5", "B650"]),
        ("微星 PRO B650M-P DDR5 主板", 899, ["DDR5", "B650"]),
        ("华硕 TUF GAMING X670E-PLUS WIFI DDR5", 2399, ["DDR5", "X670"]),
        ("技嘉 A620M DS3H DDR5", 699, ["DDR5", "A620"]),
        ("微星 B550M MORTAR MAX WIFI DDR4", 879, ["DDR4", "B550"]),
        ("华硕 TUF GAMING B550M-PLUS WIFI II DDR4", 949, ["DDR4", "B550"]),
    ]
    for i in range(20):
        name, base, tags = patterns[i % len(patterns)]
        sku_id = f"mock_mb_{i+1:03d}"
        boards.append(
            {
                "sku_id": sku_id,
                "category": "主板",
                "name": name,
                "price": base + rng.randint(-60, 80),
                "jd_url": jd_url(sku_id),
                "tags": tags,
            }
        )
    items.extend(boards)

    gpus = []
    gpu_specs = [
        ("无需独立显卡（核显办公方案）", 0),
        ("翔升 RTX 4060 8G 显卡", 2199),
        ("七彩虹 RTX 4060 Ti 8G Ultra", 2899),
        ("铭瑄 RTX 4070 12G 显卡", 4299),
        ("华硕 ATS RTX 4070 SUPER O12G 显卡", 4899),
        ("微星 RTX 4070 Ti SUPER 16G", 6299),
        ("影驰 RTX 4080 SUPER 16G", 8099),
        ("蓝宝石 RX 7700 XT 12G", 3099),
        ("蓝宝石 RX 7800 XT 16G", 3799),
        ("瀚铠 RX 7900 GRE", 4199),
    ]
    for i in range(20):
        name, base = gpu_specs[i % len(gpu_specs)]
        sku_id = f"mock_gpu_{i+1:03d}"
        gpus.append(
            {
                "sku_id": sku_id,
                "category": "显卡",
                "name": name,
                "price": base + (rng.randint(-120, 200) if base > 0 else 0),
                "jd_url": jd_url(sku_id),
                "tags": [],
            }
        )
    items.extend(gpus)

    rams = []
    ram_specs = [
        ("金士顿 FURY 16G DDR4 3200 马甲条", 299),
        ("威刚 XPG 32G DDR4 3600 套装", 549),
        ("光威 天策 32G DDR5 6000 马甲条", 629),
        ("芝奇 幻锋戟 32G DDR5 6400 RGB", 899),
        ("阿斯加特 女武神 32G DDR5 6800 白色RGB", 999),
        ("海盗船 复仇者 64G DDR5 6000", 1699),
    ]
    for i in range(20):
        name, base = ram_specs[i % len(ram_specs)]
        sku_id = f"mock_ram_{i+1:03d}"
        rams.append(
            {
                "sku_id": sku_id,
                "category": "内存",
                "name": name,
                "price": base + rng.randint(-40, 90),
                "jd_url": jd_url(sku_id),
                "tags": ["白色"] if "白色" in name else [],
            }
        )
    items.extend(rams)

    ssds = []
    ssd_specs = [
        ("铠侠 RC20 1TB NVMe SSD", 399),
        ("西部数据 SN580 1TB PCIe4.0", 459),
        ("三星 990 PRO 1TB PCIe4.0", 699),
        ("致态 TiPlus7100 2TB PCIe4.0", 899),
        ("三星 990 PRO 2TB PCIe4.0", 1299),
        ("SOLIDIGM P44 Pro 2TB", 1099),
    ]
    for i in range(20):
        name, base = ssd_specs[i % len(ssd_specs)]
        sku_id = f"mock_ssd_{i+1:03d}"
        ssds.append(
            {
                "sku_id": sku_id,
                "category": "硬盘",
                "name": name,
                "price": base + rng.randint(-35, 70),
                "jd_url": jd_url(sku_id),
                "tags": [],
            }
        )
    items.extend(ssds)

    cases = []
    case_specs = [
        ("先马 平头哥 M2 M-ATX 机箱", 149),
        ("爱国者 YOGO M2 PRO 白色 MATX", 239),
        ("联力 LANCOOL 216 RGB ATX 机箱", 599),
        ("乔思伯 D300 白色 MATX 海景房", 459),
        ("航嘉 S980 全景白色海景房 ATX 支持360水冷", 349),
        ("酷冷至尊 NR400 MATX 机箱", 399),
    ]
    for i in range(20):
        name, base = case_specs[i % len(case_specs)]
        sku_id = f"mock_case_{i+1:03d}"
        tags = []
        if "海景房" in name:
            tags.append("海景房")
        if "白色" in name:
            tags.append("白色")
        if "360" in name:
            tags.append("360冷排")
        cases.append(
            {
                "sku_id": sku_id,
                "category": "机箱",
                "name": name,
                "price": base + rng.randint(-25, 55),
                "jd_url": jd_url(sku_id),
                "tags": tags,
            }
        )
    items.extend(cases)

    psus = []
    psu_specs = [
        ("航嘉 WD650 额定650W 铜牌电源", 319),
        ("鑫谷 GM750 金牌全模组 750W", 449),
        ("海韵 FOCUS GX850 金牌全模组", 949),
        ("振华 LEADEX VII 1000W 金牌全模组", 1299),
        ("长城 X7 750W 金牌全模组", 429),
        ("安钛克 NE850 金牌全模组", 659),
    ]
    for i in range(20):
        name, base = psu_specs[i % len(psu_specs)]
        sku_id = f"mock_psu_{i+1:03d}"
        psus.append(
            {
                "sku_id": sku_id,
                "category": "电源",
                "name": name,
                "price": base + rng.randint(-30, 70),
                "jd_url": jd_url(sku_id),
                "tags": [],
            }
        )
    items.extend(psus)

    fans = []
    fan_specs = [
        ("利民 TL-C12C 无光机箱风扇 三联包", 69),
        ("棱镜4 PRO 白色ARGB风扇 三联包", 99),
        ("联力 AL120 V2 积木风扇 白色三联包", 599),
        ("酷冷至尊 MF120 HALO ARGB 三联包", 249),
    ]
    for i in range(20):
        name, base = fan_specs[i % len(fan_specs)]
        sku_id = f"mock_fan_{i+1:03d}"
        fans.append(
            {
                "sku_id": sku_id,
                "category": "风扇",
                "name": name,
                "price": base + rng.randint(-10, 35),
                "jd_url": jd_url(sku_id),
                "tags": ["白色"] if "白色" in name else [],
            }
        )
    items.extend(fans)

    monitors = []
    mon_specs = [
        ("红米 27英寸 2K 165Hz IPS 显示器", 1099),
        ("HKC IG27Q 27英寸 2K 170Hz FastIPS", 999),
        ("联想 R27qe 27英寸 2K 180Hz", 1199),
        ("LG 27GP850 27英寸 2K NanoIPS 180Hz", 2199),
        ("三星 G8 34英寸 带鱼屏 QD-OLED", 8999),
    ]
    for i in range(20):
        name, base = mon_specs[i % len(mon_specs)]
        sku_id = f"mock_mon_{i+1:03d}"
        monitors.append(
            {
                "sku_id": sku_id,
                "category": "显示器",
                "name": name,
                "price": base + rng.randint(-80, 150),
                "jd_url": jd_url(sku_id),
                "tags": [],
            }
        )
    items.extend(monitors)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(items)} products -> {OUT}")


if __name__ == "__main__":
    main()
