#!/usr/bin/env python3
"""
基站数据扩展脚本
在现有 base2info.json 基础上增加天线参数、容量模型、状态监控、空间特征
"""

import json
import random
import numpy as np
from pathlib import Path

# 配置
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
INPUT_FILE = DATA_DIR / "base2info.json"
OUTPUT_FILE = DATA_DIR / "base2info_extended.json"

# 随机种子保证可复现
random.seed(42)
np.random.seed(42)


def generate_antenna_params():
    """生成天线参数（假数据）"""
    return {
        "azimuth": random.randint(0, 360),  # 方位角 0-360度
        "downtilt": random.randint(0, 15),   # 下倾角 0-15度
        "power": random.randint(30, 46),     # 发射功率 30-46 dBm
        "height": random.randint(20, 50),    # 天线高度 20-50米
        "pattern": "omni" if random.random() > 0.7 else "sector"  # 70%扇形天线
    }


def generate_capacity_model():
    """生成容量模型（假数据）"""
    return {
        "prb_pool": random.choice([50, 75, 100, 150]),  # PRB资源池
        "max_users": random.choice([50, 100, 200, 500]),  # 最大用户数
        "bandwidth": random.choice([20, 40, 60, 80]),  # 带宽 MHz
        "throughput_curve": [
            {"load": 0.0, "throughput": 0},
            {"load": 0.2, "throughput": 20},
            {"load": 0.4, "throughput": 38},
            {"load": 0.6, "throughput": 52},
            {"load": 0.8, "throughput": 60},
            {"load": 1.0, "throughput": 65}
        ],
        "carrier_frequency": random.choice([2.1, 2.6, 3.5, 4.9])  # 载波频率 GHz
    }


def generate_status_monitoring():
    """生成状态监控数据（假数据）"""
    load = round(random.uniform(0.1, 0.95), 2)
    active_users = int(load * random.choice([50, 100, 200, 500]))
    
    # 随机生成告警（10%概率有告警）
    alarms = []
    if random.random() < 0.1:
        alarms.append(random.choice([
            "HIGH_TEMPERATURE",
            "POWER_LOW",
            "SIGNAL_WEAK",
            "HARDWARE_FAULT"
        ]))
    
    return {
        "load": load,
        "active_users": active_users,
        "alarms": alarms,
        "kpi": {
            "rsrp": round(random.uniform(-110, -80), 1),  # 参考信号接收功率 dBm
            "sinr": round(random.uniform(5, 25), 1),       # 信干噪比 dB
            "packet_loss": round(random.uniform(0, 0.05), 4),  # 丢包率
            "latency": round(random.uniform(10, 100), 1)   # 延迟 ms
        }
    }


def generate_spatial_features():
    """生成空间特征（假数据）"""
    # 128维卫星图像特征向量
    satellite_features = np.random.randn(128).tolist()
    
    # 64维POI特征向量
    poi_features = np.random.randn(64).tolist()
    
    # 附近POI（随机生成1-5个）
    nearby_pois = []
    poi_types = ["commercial", "residential", "office", "school", "hospital", "park"]
    for _ in range(random.randint(1, 5)):
        nearby_pois.append({
            "type": random.choice(poi_types),
            "distance": random.randint(50, 2000)  # 距离 50-2000米
        })
    
    return {
        "satellite_image": {
            "url": None,  # 预留，后续可填充真实URL
            "features": [round(x, 4) for x in satellite_features]
        },
        "poi": {
            "nearby": nearby_pois,
            "features": [round(x, 4) for x in poi_features]
        },
        "building_density": round(random.uniform(0.1, 0.9), 2),  # 建筑密度
        "population_density": random.randint(1000, 20000)  # 人口密度 人/km²
    }


def extend_base_station(base_id, base_info):
    """扩展单个基站数据"""
    # 保留原有字段
    extended = {
        "id": base_info["id"],
        "name": f"基站{base_info['id']:04d}",  # 新增：基站名称
        "location": {
            "longitude": base_info["loc"][0],
            "latitude": base_info["loc"][1],
            "altitude": random.randint(0, 100)  # 新增：海拔
        },
        "type": random.choice(["macro", "micro", "pico"]),  # 新增：基站类型
        "status": "active" if random.random() > 0.05 else "maintenance",  # 新增：状态
        "antenna": generate_antenna_params(),
        "capacity": generate_capacity_model(),
        "status_monitoring": generate_status_monitoring(),
        "spatial": generate_spatial_features()
    }
    
    # 保留原有 loc 字段以保持兼容性
    extended["loc"] = base_info["loc"]
    
    return extended


def main():
    """主函数"""
    print("开始扩展基站数据...")
    
    # 读取原始数据
    print(f"读取原始数据: {INPUT_FILE}")
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        original_data = json.load(f)
    
    print(f"原始基站数量: {len(original_data)}")
    
    # 扩展数据
    extended_data = {}
    for idx, (base_id, base_info) in enumerate(original_data.items()):
        extended_data[base_id] = extend_base_station(base_id, base_info)
        
        # 进度显示
        if (idx + 1) % 1000 == 0:
            print(f"已处理: {idx + 1}/{len(original_data)}")
    
    # 保存扩展后的数据
    print(f"保存扩展数据: {OUTPUT_FILE}")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(extended_data, f, ensure_ascii=False, indent=2)
    
    # 统计信息
    print("\n扩展完成!")
    print(f"基站总数: {len(extended_data)}")
    print(f"每个基站字段数: {len(extended_data[list(extended_data.keys())[0]])}")
    
    # 显示一个示例
    sample_key = list(extended_data.keys())[0]
    print(f"\n示例基站 ({sample_key}):")
    sample = extended_data[sample_key]
    print(f"  - 名称: {sample['name']}")
    print(f"  - 类型: {sample['type']}")
    print(f"  - 状态: {sample['status']}")
    print(f"  - 天线方位角: {sample['antenna']['azimuth']}°")
    print(f"  - 容量(最大用户): {sample['capacity']['max_users']}")
    print(f"  - 当前负载: {sample['status_monitoring']['load']}")
    print(f"  - 空间特征维度: 卫星{len(sample['spatial']['satellite_image']['features'])}维 + POI{len(sample['spatial']['poi']['features'])}维")


if __name__ == "__main__":
    main()
