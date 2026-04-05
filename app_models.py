"""
APP 分类流量模型
基于 user_data_shanghai_v1 中的真实 APP 使用数据定义流量特征模型。
将 20 个 APP 类别映射到 4 大流量模式。
"""


# ==========================================
# APP 类别到流量模式的映射
# ==========================================

# 四大流量模式分类
TRAFFIC_PATTERN_VIDEO = "video"        # 视频类：下行突发、高带宽
TRAFFIC_PATTERN_SOCIAL = "social"      # 社交类：上下均衡、中等带宽
TRAFFIC_PATTERN_GAMING = "gaming"      # 游戏类：低延迟、中等带宽
TRAFFIC_PATTERN_BROWSING = "browsing"  # 浏览类：下行中等、间歇性

# APP 类别 → 流量模式映射（基于真实数据中的 20 个类别）
CATEGORY_TO_PATTERN = {
    # 视频类 - 下行突发、5-10 Mbps
    "Photo & Video": TRAFFIC_PATTERN_VIDEO,
    "Entertainment": TRAFFIC_PATTERN_VIDEO,
    "Music": TRAFFIC_PATTERN_VIDEO,

    # 社交类 - 上下均衡、0.5-2 Mbps
    "Social Networking": TRAFFIC_PATTERN_SOCIAL,
    "Lifestyle": TRAFFIC_PATTERN_SOCIAL,
    "Infant & Mom": TRAFFIC_PATTERN_SOCIAL,

    # 游戏类 - 低延迟、1-3 Mbps
    "Games": TRAFFIC_PATTERN_GAMING,
    "Sports": TRAFFIC_PATTERN_GAMING,

    # 浏览类 - 下行中等、2-5 Mbps
    "News": TRAFFIC_PATTERN_BROWSING,
    "Shopping": TRAFFIC_PATTERN_BROWSING,
    "Books": TRAFFIC_PATTERN_BROWSING,
    "Education": TRAFFIC_PATTERN_BROWSING,
    "References": TRAFFIC_PATTERN_BROWSING,
    "Business": TRAFFIC_PATTERN_BROWSING,
    "Finance": TRAFFIC_PATTERN_BROWSING,
    "Health & Fitness": TRAFFIC_PATTERN_BROWSING,
    "Travel": TRAFFIC_PATTERN_BROWSING,
    "Navigation": TRAFFIC_PATTERN_BROWSING,
    "Utilities": TRAFFIC_PATTERN_BROWSING,
    "Weather": TRAFFIC_PATTERN_BROWSING,
}


# ==========================================
# 流量特征模型定义
# ==========================================

TRAFFIC_MODELS = {
    TRAFFIC_PATTERN_VIDEO: {
        "name": "视频流媒体",
        "name_en": "Video Streaming",
        "description": "抖音、B站、爱奇艺等视频应用",
        "bandwidth_range_mbps": [5.0, 10.0],
        "avg_bandwidth_mbps": 7.5,
        "direction": "downlink_heavy",      # 下行为主
        "downlink_ratio": 0.95,             # 95% 下行
        "burst_pattern": "sustained",       # 持续高带宽
        "latency_sensitivity": "low",       # 对延迟不敏感
        "typical_session_min": [5, 60],     # 5-60 分钟/会话
        "typical_traffic_mb_per_session": [50, 500],
        "categories": ["Photo & Video", "Entertainment", "Music"],
    },
    TRAFFIC_PATTERN_SOCIAL: {
        "name": "社交通信",
        "name_en": "Social & Messaging",
        "description": "微信、微博、QQ等社交应用",
        "bandwidth_range_mbps": [0.5, 2.0],
        "avg_bandwidth_mbps": 1.0,
        "direction": "balanced",            # 上下均衡
        "downlink_ratio": 0.6,              # 60% 下行
        "burst_pattern": "intermittent",    # 间歇性突发
        "latency_sensitivity": "medium",    # 中等延迟敏感
        "typical_session_min": [1, 30],
        "typical_traffic_mb_per_session": [1, 20],
        "categories": ["Social Networking", "Lifestyle", "Infant & Mom"],
    },
    TRAFFIC_PATTERN_GAMING: {
        "name": "在线游戏",
        "name_en": "Online Gaming",
        "description": "王者荣耀、和平精英等游戏应用",
        "bandwidth_range_mbps": [1.0, 3.0],
        "avg_bandwidth_mbps": 2.0,
        "direction": "balanced",            # 上下均衡
        "downlink_ratio": 0.55,             # 55% 下行
        "burst_pattern": "constant_low",    # 恒定低带宽
        "latency_sensitivity": "high",      # 高延迟敏感
        "typical_session_min": [15, 120],
        "typical_traffic_mb_per_session": [10, 100],
        "categories": ["Games", "Sports"],
    },
    TRAFFIC_PATTERN_BROWSING: {
        "name": "网页浏览",
        "name_en": "Web Browsing",
        "description": "新闻、购物、工具类应用",
        "bandwidth_range_mbps": [2.0, 5.0],
        "avg_bandwidth_mbps": 3.0,
        "direction": "downlink_moderate",   # 中等下行
        "downlink_ratio": 0.85,             # 85% 下行
        "burst_pattern": "bursty",          # 突发模式
        "latency_sensitivity": "medium",
        "typical_session_min": [1, 15],
        "typical_traffic_mb_per_session": [2, 30],
        "categories": [
            "News", "Shopping", "Books", "Education", "References",
            "Business", "Finance", "Health & Fitness", "Travel",
            "Navigation", "Utilities", "Weather"
        ],
    },
}


# ==========================================
# 工具函数
# ==========================================

def get_traffic_pattern(app_category):
    """根据 APP 类别获取流量模式"""
    return CATEGORY_TO_PATTERN.get(app_category, TRAFFIC_PATTERN_BROWSING)


def get_traffic_model(app_category):
    """根据 APP 类别获取完整的流量特征模型"""
    pattern = get_traffic_pattern(app_category)
    return TRAFFIC_MODELS[pattern]


def classify_app_records(trajectory_records):
    """
    对轨迹记录中的 APP 使用进行流量分类统计。

    Args:
        trajectory_records: 轨迹记录列表，每条记录为14字段数组
            [timestamp, lon, lat, base_id, base_key, place_type,
             movement_state, app_id, app_name, app_category,
             traffic_mb, signal_dbm, session_duration_min, distance_m]

    Returns:
        dict: 按流量模式分类的统计信息
    """
    stats = {
        TRAFFIC_PATTERN_VIDEO: {"count": 0, "total_traffic_mb": 0, "total_duration_min": 0},
        TRAFFIC_PATTERN_SOCIAL: {"count": 0, "total_traffic_mb": 0, "total_duration_min": 0},
        TRAFFIC_PATTERN_GAMING: {"count": 0, "total_traffic_mb": 0, "total_duration_min": 0},
        TRAFFIC_PATTERN_BROWSING: {"count": 0, "total_traffic_mb": 0, "total_duration_min": 0},
    }

    for record in trajectory_records:
        if len(record) < 14:
            continue
        app_category = record[9]   # app_category 字段
        traffic_mb = record[10]    # traffic_mb 字段
        duration_min = record[12]  # session_duration_min 字段

        pattern = get_traffic_pattern(app_category)
        stats[pattern]["count"] += 1
        stats[pattern]["total_traffic_mb"] += traffic_mb if isinstance(traffic_mb, (int, float)) else 0
        stats[pattern]["total_duration_min"] += duration_min if isinstance(duration_min, (int, float)) else 0

    return stats


def get_app_category_summary():
    """返回所有 APP 类别及其流量模式分类的摘要（供 API 使用）"""
    summary = {}
    for category, pattern in CATEGORY_TO_PATTERN.items():
        model = TRAFFIC_MODELS[pattern]
        summary[category] = {
            "pattern": pattern,
            "pattern_name": model["name"],
            "pattern_name_en": model["name_en"],
            "avg_bandwidth_mbps": model["avg_bandwidth_mbps"],
            "direction": model["direction"],
            "latency_sensitivity": model["latency_sensitivity"],
        }
    return summary
