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

        # 模拟快照相关
        self.base_id_to_loc = {}         # serving_base_id(numeric) -> [lng, lat]
        self.base_id_to_station_id = {}  # serving_base_id(numeric) -> station hex id
        self.trajectory_time_slots = 0   # 轨迹时间片总数 (336)

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

            # 构建 serving_base_id -> loc 映射
            self._build_base_id_loc_mapping()
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
    # 模拟快照接口
    # ==========================================

    def _build_base_id_loc_mapping(self):
        """从轨迹数据中构建 serving_base_id(numeric) -> 基站坐标 映射，
        并按物理坐标对 cell 分组（同一坐标的不同 cell ID 属于同一物理基站）。"""
        t0 = time.time()
        seen_ids = set()

        # 第一步：收集所有轨迹中引用的基站信息
        for uid, records in self.user_trajectories.items():
            if self.trajectory_time_slots == 0 and records:
                self.trajectory_time_slots = len(records)
            for rec in records:
                if len(rec) < 5:
                    continue
                base_id_num = rec[3]  # serving_base_id (numeric)
                if base_id_num in seen_ids:
                    continue
                seen_ids.add(base_id_num)
                base_key = rec[4]     # serving_base_key e.g. "Base_3610000F1752"
                if self.base_json and base_key in self.base_json:
                    self.base_id_to_loc[base_id_num] = self.base_json[base_key]['loc']
                    # 提取 hex station id (去掉 "Base_" 前缀)
                    self.base_id_to_station_id[base_id_num] = base_key[5:] if base_key.startswith('Base_') else base_key

        # 第二步：构建地图基站索引，并将每个轨迹 cell 分配到最近的地图基站（200m内）
        # 这是真实的：同一物理基站塔的不同扇区坐标略有偏差，但都在​200m范围内
        map_hex_ids = set(s['id'] for s in self.station_list)
        map_stations = [(s['id'], s['loc'][0], s['loc'][1]) for s in self.station_list]

        # 距离阈值: 200m ≈ 0.002° (lat), (0.002)^2 = 4e-6
        PROXIMITY_THRESHOLD_SQ = 4e-6

        self.numeric_to_map_hex = {}  # numeric_id -> nearest map hex (within 200m)
        self.map_hex_to_numeric_ids = defaultdict(set)  # map hex -> set of numeric_ids

        for num_id, loc in self.base_id_to_loc.items():
            hex_id = self.base_id_to_station_id.get(num_id)
            # 如果本身就是地图基站，直接映射
            if hex_id and hex_id in map_hex_ids:
                self.numeric_to_map_hex[num_id] = hex_id
                self.map_hex_to_numeric_ids[hex_id].add(num_id)
                continue

            # 否则找最近的地图基站
            best_hex = None
            best_dist = float('inf')
            for ms_hex, ms_lng, ms_lat in map_stations:
                d = (loc[0] - ms_lng) ** 2 + (loc[1] - ms_lat) ** 2
                if d < best_dist:
                    best_dist = d
                    best_hex = ms_hex

            if best_dist <= PROXIMITY_THRESHOLD_SQ:
                self.numeric_to_map_hex[num_id] = best_hex
                self.map_hex_to_numeric_ids[best_hex].add(num_id)

        # 统计
        mapped_count = len(self.numeric_to_map_hex)
        multi = sum(1 for ids in self.map_hex_to_numeric_ids.values() if len(ids) > 1)
        avg_cells = mapped_count / max(len(self.map_hex_to_numeric_ids), 1)
        elapsed = time.time() - t0
        print(f"[DataManager] Cell mapping: {len(self.base_id_to_loc)} cells -> {mapped_count} mapped to {len(self.map_hex_to_numeric_ids)} map stations (200m threshold)")
        print(f"[DataManager] {multi} stations have multi-cells (avg {avg_cells:.1f} cells/station), {len(self.base_id_to_loc) - mapped_count} cells unmapped (>200m)")
        print(f"[DataManager] Built in {elapsed:.1f}s, trajectory time slots: {self.trajectory_time_slots}")

    def get_simulation_snapshot(self, time_index, bbox=None):
        """
        获取指定时间片的模拟快照：所有用户的位置 + 连接信息。

        Args:
            time_index: 时间片索引 (0 ~ trajectory_time_slots-1)
            bbox: 可选视口过滤 [min_lng, min_lat, max_lng, max_lat]

        Returns:
            dict: {
                time_index, total_users,
                schema: [...],
                users: [[lng, lat, base_id, signal_dbm, traffic_mb], ...],
                station_locs: {base_id: [lng, lat], ...},  (首次请求时)
                station_stats: {base_id: {users, traffic, avg_signal}, ...}
            }
        """
        if not self._loaded_users or not self.user_trajectories:
            return {"error": "User data not loaded"}

        if time_index < 0 or time_index >= self.trajectory_time_slots:
            return {"error": f"time_index must be 0-{self.trajectory_time_slots - 1}"}

        users_data = []
        # 按地图基站 (map hex) 聚合统计，同一基站 200m 内多 cell 汇总
        site_agg = defaultdict(lambda: {"users": 0, "traffic": 0.0, "signal_sum": 0.0, "cells": set()})

        for uid, records in self.user_trajectories.items():
            if time_index >= len(records):
                continue
            rec = records[time_index]
            if len(rec) < 12:
                continue

            lng = rec[1]
            lat = rec[2]
            base_id = rec[3]       # serving_base_id (numeric)
            traffic = rec[10] if rec[10] is not None else 0
            signal = rec[11] if rec[11] is not None else -100

            # 视口过滤
            if bbox:
                if lng < bbox[0] or lng > bbox[2] or lat < bbox[1] or lat > bbox[3]:
                    continue

            users_data.append([round(lng, 6), round(lat, 6), base_id, round(signal, 1), round(traffic, 2)])

            # 按地图基站聚合（200m范围内的同站多 cell 真实汇总）
            map_hex = self.numeric_to_map_hex.get(base_id)
            if map_hex:
                st = site_agg[map_hex]
                st["users"] += 1
                st["traffic"] += traffic
                st["signal_sum"] += signal
                st["cells"].add(base_id)

        # 构建 station_stats，用 map hex ID 作为 key
        station_stats = {}
        for hex_id, st in site_agg.items():
            station_stats[hex_id] = {
                "users": st["users"],
                "traffic": round(st["traffic"], 2),
                "avg_signal": round(st["signal_sum"] / st["users"], 1) if st["users"] > 0 else -100,
                "cells": len(st["cells"]),
            }

        return {
            "time_index": time_index,
            "total_users": len(users_data),
            "time_slots": self.trajectory_time_slots,
            "schema": ["lng", "lat", "base_id", "signal_dbm", "traffic_mb"],
            "users": users_data,
            "station_stats": station_stats,
        }

    def get_station_locs_by_numeric_id(self):
        """返回 serving_base_id(numeric) -> [lng, lat] 的映射，供前端缓存"""
        return {str(k): v for k, v in self.base_id_to_loc.items()}

    def get_station_id_mapping(self):
        """返回 hex station_id -> serving_base_id(numeric) 的双向映射"""
        hex_to_num = {v: k for k, v in self.base_id_to_station_id.items()}
        return {"hex_to_numeric": {str(k): v for k, v in hex_to_num.items()},
                "numeric_to_hex": {str(k): v for k, v in self.base_id_to_station_id.items()}}

    def get_station_time_series(self, station_hex_id):
        """
        统计某地图基站及其 200m 内所有 cell 在每个时间片的接入用户数和总流量。

        Args:
            station_hex_id: 地图基站 hex ID

        Returns:
            dict: {station_id, cells, time_slots, user_counts: [...], traffic_totals: [...]}
        """
        if not self._loaded_users:
            return {"error": "User data not loaded"}

        user_counts = [0] * self.trajectory_time_slots
        traffic_totals = [0.0] * self.trajectory_time_slots

        # 找到该地图基站对应的所有 cell IDs（200m 范围内）
        target_ids = self.map_hex_to_numeric_ids.get(str(station_hex_id), set())
        if not target_ids:
            return {"error": f"Station {station_hex_id} has no associated cells"}

        for uid, records in self.user_trajectories.items():
            for t, rec in enumerate(records):
                if t >= self.trajectory_time_slots:
                    break
                if len(rec) >= 4 and rec[3] in target_ids:
                    user_counts[t] += 1
                    traffic_totals[t] += rec[10] if len(rec) > 10 and rec[10] is not None else 0

        return {
            "station_id": str(station_hex_id),
            "cells": len(target_ids),
            "time_slots": self.trajectory_time_slots,
            "user_counts": user_counts,
            "traffic_totals": [round(t, 2) for t in traffic_totals],
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
