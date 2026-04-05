"""
DataManager - 统一数据访问层
负责加载和管理所有数据：基站、用户轨迹、用户画像。
"""

import os
import json
import time
import math
import numpy as np
from collections import defaultdict

from app_models import classify_app_records, get_app_category_summary, TRAFFIC_MODELS


class DataManager:
    """统一数据管理器，封装基站 + 用户数据的加载和访问。"""

    def __init__(self, data_dir, user_data_dir=None, model_path=None):
        """
        Args:
            data_dir: 基站数据目录 (含 base2info_extended.json, *.npz)
            user_data_dir: 用户数据目录 (含 trajectories.json, user_profiles_en.json, profiles_txt/)
            model_path: AI 模型路径
        """
        self.data_dir = data_dir
        self.user_data_dir = user_data_dir
        self.model_path = model_path

        # 基站数据
        self.json_path = os.path.join(data_dir, 'base2info_extended.json')
        self.traffic_path = os.path.join(data_dir, 'bs_record_energy_normalized_sampled.npz')
        self.spatial_path = os.path.join(data_dir, 'spatial_features.npz')

        # 缓存
        self.npz_data = None          # NPZ 原始数据缓存
        self.base_json = None         # base2info_extended.json 完整内容
        self.station_list = []        # 合并后的基站列表（供 API 返回）
        self.stats_height = {}
        self.stats_color = {}

        # 用户数据
        self.user_profiles = {}       # user_id -> profile dict
        self.user_trajectories = {}   # user_id -> list of trajectory records
        self.user_roles = defaultdict(list)  # role -> [user_id, ...]
        self.base_to_users = defaultdict(set)  # base_id(numeric) -> {user_id, ...}

        # 状态
        self._loaded_stations = False
        self._loaded_users = False

    # ==========================================
    # 基站数据加载（保持现有逻辑）
    # ==========================================

    def load_station_data(self):
        """加载基站数据（NPZ + JSON），返回合并后的列表"""
        print("[DataManager] Loading station data...")
        t0 = time.time()

        if not os.path.exists(self.json_path) or not os.path.exists(self.traffic_path):
            print("[DataManager] Error: Station data files not found.")
            print(f"   - JSON: {self.json_path} (exists: {os.path.exists(self.json_path)})")
            print(f"   - NPZ:  {self.traffic_path} (exists: {os.path.exists(self.traffic_path)})")
            return []

        # Load NPZ
        self.npz_data = np.load(self.traffic_path)
        print(f"[DataManager] NPZ loaded: {list(self.npz_data.files)[:5]}...")

        # Load JSON
        with open(self.json_path, 'r', encoding='utf-8') as f:
            self.base_json = json.load(f)

        # Merge NPZ + JSON
        raw_bs_ids = self.npz_data['bs_id']
        bs_ids = [x.decode('utf-8') if isinstance(x, bytes) else str(x) for x in raw_bs_ids]
        num_stations = len(bs_ids)

        excluded_attrs = {
            'bs_record', 'hours_in_weekday', 'hours_in_weekend',
            'days_in_weekday', 'days_in_weekend',
            'days_in_weekday_residual', 'days_in_weekend_residual',
            'hours_in_weekday_patterns', 'hours_in_weekend_patterns',
            'days_in_weekday_patterns', 'days_in_weekend_patterns',
            'days_in_weekday_residual_patterns', 'days_in_weekend_residual_patterns',
            'weeks_in_month_residual'
        }
        station_attributes = []
        for key in self.npz_data.files:
            if key == 'bs_id' or key in excluded_attrs:
                continue
            if self.npz_data[key].shape[0] == num_stations:
                station_attributes.append(key)

        merged_data = []
        match_count = 0

        for i in range(num_stations):
            current_id = bs_ids[i]
            json_key = f"Base_{current_id}"
            if json_key in self.base_json:
                match_count += 1
                entry = {
                    "id": current_id,
                    "npz_index": i,
                    "loc": self.base_json[json_key]["loc"]
                }
                for attr in station_attributes:
                    val = self.npz_data[attr][i]
                    entry[attr] = self._convert_numpy(val)
                merged_data.append(entry)

        self.station_list = merged_data
        self.stats_height, self.stats_color = self._calculate_stats()
        self._loaded_stations = True

        elapsed = time.time() - t0
        print(f"[DataManager] Stations loaded: {match_count}/{num_stations} matched in {elapsed:.1f}s")
        return merged_data

    def _calculate_stats(self):
        """计算基站统计分布"""
        bs_record = self.npz_data.get('bs_record')
        if bs_record is None:
            return {}, {}

        avgs = []
        stds = []
        for item in self.station_list:
            idx = item.get('npz_index', 0)
            if idx < bs_record.shape[0]:
                records = bs_record[idx]
                avg = float(records.mean())
                std = float(records.std())
            else:
                avg, std = 0, 0
            avgs.append(avg)
            stds.append(std)

        def percentiles(values):
            values_sorted = sorted(values)
            n = len(values_sorted)
            if n == 0:
                return {k: 0 for k in ['min', 'max', 't1', 't2', 't3', 't4']}
            return {
                "min": values_sorted[0], "max": values_sorted[-1],
                "t1": values_sorted[int(n * 0.2)], "t2": values_sorted[int(n * 0.4)],
                "t3": values_sorted[int(n * 0.6)], "t4": values_sorted[int(n * 0.8)]
            }

        return percentiles(avgs), percentiles(stds)

    # ==========================================
    # 用户数据加载
    # ==========================================

    def load_user_data(self):
        """加载用户画像和轨迹数据（全量加载到内存）"""
        if not self.user_data_dir:
            print("[DataManager] No user data directory configured, skipping.")
            return

        profiles_path = os.path.join(self.user_data_dir, 'user_profiles_en.json')
        trajectories_path = os.path.join(self.user_data_dir, 'trajectories.json')

        if not os.path.exists(profiles_path):
            print(f"[DataManager] Warning: {profiles_path} not found.")
            return

        # 1. 加载用户画像
        print("[DataManager] Loading user profiles...")
        t0 = time.time()
        with open(profiles_path, 'r', encoding='utf-8') as f:
            profiles_data = json.load(f)

        for profile in profiles_data.get('profiles', []):
            uid = profile['user_id']
            self.user_profiles[uid] = profile
            # 按职业索引
            role = profile.get('role', 'unknown')
            self.user_roles[role].append(uid)
            # 按基站索引
            for key in ('home_base_id', 'work_base_id', 'leisure_base_id'):
                bid = profile.get(key)
                if bid is not None:
                    self.base_to_users[bid].add(uid)

        elapsed = time.time() - t0
        print(f"[DataManager] Profiles loaded: {len(self.user_profiles)} users in {elapsed:.1f}s")

        # 2. 加载轨迹数据
        if os.path.exists(trajectories_path):
            print(f"[DataManager] Loading trajectories ({os.path.getsize(trajectories_path) / 1024 / 1024:.0f}MB)...")
            t0 = time.time()
            with open(trajectories_path, 'r', encoding='utf-8') as f:
                traj_data = json.load(f)

            # 轨迹数据结构: {"metadata": {...}, "users": [{"user_id": ..., "trajectory": [...]}]}
            users_section = traj_data.get('users', [])
            for udata in users_section:
                uid = udata.get('user_id', '')
                records = udata.get('trajectory', [])
                self.user_trajectories[uid] = records
                # 建立基站-用户索引（从轨迹中）
                for record in records:
                    if len(record) >= 4:
                        base_id_numeric = record[3]
                        self.base_to_users[base_id_numeric].add(uid)

            elapsed = time.time() - t0
            print(f"[DataManager] Trajectories loaded: {len(self.user_trajectories)} users, "
                  f"{sum(len(r) for r in self.user_trajectories.values())} records in {elapsed:.1f}s")
        else:
            print(f"[DataManager] Warning: {trajectories_path} not found, trajectories not loaded.")

        self._loaded_users = True

    # ==========================================
    # 基站数据访问接口
    # ==========================================

    def get_station_locations(self):
        """返回轻量级基站位置列表（用于地图显示）"""
        bs_record = self.npz_data.get('bs_record') if self.npz_data else None
        result = []
        for item in self.station_list:
            idx = item.get('npz_index', 0)
            if bs_record is not None and idx < bs_record.shape[0]:
                records = bs_record[idx]
                avg = float(records.mean())
                std = float(records.std())
            else:
                avg, std = 0, 0
            result.append({
                "id": item['id'],
                "loc": item['loc'],
                "val_h": avg,
                "val_c": std,
            })
        return {
            "stats_height": self.stats_height,
            "stats_color": self.stats_color,
            "stations": result,
        }

    def get_station_detail(self, station_id):
        """返回单个基站的详细信息"""
        for item in self.station_list:
            if str(item['id']) == str(station_id):
                records = self.get_bs_record(item)
                avg = sum(records) / len(records) if records else 0
                std = self._std_dev(records, avg)
                response = item.copy()
                response['stats'] = {"avg": avg, "std": std}
                response['bs_record'] = records

                # 扩展基站属性（从 base_json）
                json_key = f"Base_{item['id']}"
                if self.base_json and json_key in self.base_json:
                    ext = self.base_json[json_key]
                    for k in ('antenna', 'capacity', 'monitoring', 'spatial_features'):
                        if k in ext:
                            response[k] = ext[k]

                # 关联用户数（如果有用户数据）
                if self._loaded_users:
                    numeric_id = ext.get('id') if self.base_json and json_key in self.base_json else None
                    if numeric_id is not None:
                        connected_users = self.base_to_users.get(numeric_id, set())
                        response['connected_user_count'] = len(connected_users)

                return response
        return None

    def get_bs_record(self, item):
        """获取基站的流量记录"""
        if self.npz_data is None:
            return []
        idx = item.get('npz_index', 0)
        if 'bs_record' in self.npz_data and idx < self.npz_data['bs_record'].shape[0]:
            return self.npz_data['bs_record'][idx].tolist()
        return []

    def get_station_extended_info(self, station_id):
        """获取扩展基站属性（天线、容量、监控、空间特征）"""
        json_key = f"Base_{station_id}"
        if self.base_json and json_key in self.base_json:
            ext = self.base_json[json_key]
            return {
                "antenna": ext.get("antenna"),
                "capacity": ext.get("capacity"),
                "monitoring": ext.get("monitoring"),
                "spatial_features": ext.get("spatial_features"),
            }
        return None

    # ==========================================
    # 用户数据访问接口
    # ==========================================

    def get_user_profile(self, user_id):
        """获取单个用户画像"""
        return self.user_profiles.get(user_id)

    def get_user_trajectory(self, user_id):
        """获取单个用户的轨迹数据"""
        return self.user_trajectories.get(user_id)

    def get_user_with_trajectory(self, user_id):
        """获取用户画像 + 轨迹 + APP使用统计"""
        profile = self.user_profiles.get(user_id)
        if not profile:
            return None

        result = {**profile}
        trajectory = self.user_trajectories.get(user_id, [])
        result['trajectory_count'] = len(trajectory)

        # APP 使用分类统计
        if trajectory:
            result['app_usage_stats'] = classify_app_records(trajectory)

        return result

    def get_user_text_profile(self, user_id):
        """获取用户的文本画像"""
        if not self.user_data_dir:
            return None
        txt_path = os.path.join(self.user_data_dir, 'profiles_txt', f'{user_id}.txt')
        if os.path.exists(txt_path):
            with open(txt_path, 'r', encoding='utf-8') as f:
                return f.read()
        return None

    def query_users(self, role=None, base_id=None, page=1, page_size=50):
        """
        查询用户列表（支持按职业、按基站筛选，分页）

        Args:
            role: 职业筛选 (service_worker, office_worker, etc.)
            base_id: 基站ID筛选（数字ID）
            page: 页码（从1开始）
            page_size: 每页数量

        Returns:
            dict: {total, page, page_size, users: [...]}
        """
        # 确定候选用户
        if role and base_id is not None:
            role_users = set(self.user_roles.get(role, []))
            base_users = self.base_to_users.get(int(base_id), set())
            candidate_ids = sorted(role_users & base_users)
        elif role:
            candidate_ids = sorted(self.user_roles.get(role, []))
        elif base_id is not None:
            candidate_ids = sorted(self.base_to_users.get(int(base_id), set()))
        else:
            candidate_ids = sorted(self.user_profiles.keys())

        total = len(candidate_ids)
        start = (page - 1) * page_size
        end = start + page_size
        page_ids = candidate_ids[start:end]

        users = []
        for uid in page_ids:
            profile = self.user_profiles.get(uid, {})
            users.append({
                "user_id": uid,
                "role": profile.get("role"),
                "age_band": profile.get("age_band"),
                "usage_intensity": profile.get("usage_intensity"),
                "home_base_id": profile.get("home_base_id"),
                "work_base_id": profile.get("work_base_id"),
                "trajectory_records": profile.get("trajectory_records", 0),
                "total_traffic_gb": profile.get("total_traffic_gb", 0),
            })

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "users": users,
        }

    def get_users_by_base(self, base_id_numeric):
        """获取连接到某基站的所有用户ID列表"""
        return sorted(self.base_to_users.get(int(base_id_numeric), set()))

    def get_user_stats(self):
        """返回用户数据的全局统计信息"""
        if not self._loaded_users:
            return {"loaded": False}

        role_counts = {role: len(uids) for role, uids in self.user_roles.items()}
        total_traj = sum(len(r) for r in self.user_trajectories.values())

        return {
            "loaded": True,
            "total_users": len(self.user_profiles),
            "total_trajectories": total_traj,
            "roles": role_counts,
            "users_with_trajectories": len(self.user_trajectories),
        }

    # ==========================================
    # 工具函数
    # ==========================================

    @staticmethod
    def _convert_numpy(val):
        if isinstance(val, np.ndarray):
            return val.tolist()
        elif isinstance(val, (np.integer,)):
            return int(val)
        elif isinstance(val, (np.floating,)):
            return float(val)
        elif isinstance(val, bytes):
            return val.decode('utf-8')
        return val

    @staticmethod
    def _std_dev(records, avg):
        if not records or len(records) < 2:
            return 0
        variance = sum((x - avg) ** 2 for x in records) / len(records)
        return math.sqrt(variance)
