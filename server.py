import os
import json
import numpy as np
import math
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS

from data_manager import DataManager
from app_models import get_app_category_summary, TRAFFIC_MODELS

# Import the custom prediction backend module
try:
    from prediction_backend import TrafficPredictor
except ImportError:
    print("Warning: prediction_backend.py not found. Prediction features will be disabled.")
    TrafficPredictor = None
except Exception as e:
    print(f"Warning: Failed to import prediction_backend: {e}")
    TrafficPredictor = None

# ==========================================
# Flask Server
# ==========================================
app = Flask(__name__, static_folder='.')
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, 'data'))
MODEL_PATH = os.path.join(BASE_DIR, 'best_corr_model.pt')

# 用户数据目录（可通过环境变量配置）
USER_DATA_DIR = os.environ.get(
    'USER_DATA_DIR',
    os.path.abspath(os.path.join(BASE_DIR, '..', 'user_data_shanghai_v1'))
)

# ==========================================
# Initialization via DataManager
# ==========================================
print("Server Initializing...")

dm = DataManager(
    data_dir=DATA_DIR,
    user_data_dir=USER_DATA_DIR if os.path.isdir(USER_DATA_DIR) else None,
    model_path=MODEL_PATH,
)

# 1. Load station data
ALL_DATA = dm.load_station_data()
STATS_HEIGHT = dm.stats_height
STATS_COLOR = dm.stats_color
NPZ_DATA_CACHE = dm.npz_data

if not ALL_DATA:
    print("⚠️ CRITICAL WARNING: Station data list is empty!")

# 2. Load user data (if available)
dm.load_user_data()
user_stats = dm.get_user_stats()
if user_stats.get('loaded'):
    print(f"[Init] User data ready: {user_stats['total_users']} users, "
          f"{user_stats['total_trajectories']} trajectory records")
else:
    print("[Init] User data not loaded (directory not found or empty)")

# 3. Initialize AI Predictor
predictor = None
if TrafficPredictor:
    try:
        print(f"[AI] Initializing Predictor with model: {MODEL_PATH}")
        predictor = TrafficPredictor(
            model_path=MODEL_PATH,
            spatial_path=dm.spatial_path,
            traffic_path=dm.traffic_path
        )
        print("[AI] Predictor loaded successfully.")
    except Exception as e:
        print(f"[AI] Failed to load predictor: {e}")

# ==========================================
# Utility (kept for backward compat)
# ==========================================
def calculate_std_dev(records, avg):
    if not records or len(records) < 2:
        return 0
    variance = sum((x - avg) ** 2 for x in records) / len(records)
    return math.sqrt(variance)

def get_bs_record_for_station(item):
    return dm.get_bs_record(item)

# ==========================================
# Static File Routes
# ==========================================
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

# ==========================================
# Station API Routes (existing)
# ==========================================
@app.route('/api/stations/locations')
def get_station_locations():
    """Returns a lightweight list of station coordinates and statistical summaries."""
    return jsonify(dm.get_station_locations())

@app.route('/api/stations/detail/<station_id>')
def get_station_detail(station_id):
    """Returns detailed metadata and stats for a specific station."""
    result = dm.get_station_detail(station_id)
    if result:
        return jsonify(result)
    return jsonify({"error": "Station not found"}), 404

@app.route('/api/predict/<station_id>')
def predict_traffic(station_id):
    """Triggers the ML model to predict future traffic for a specific station."""
    if not predictor:
        return jsonify({"error": "Prediction service not available"}), 503

    try:
        target_idx = -1
        for item in ALL_DATA:
            if str(item['id']) == str(station_id):
                target_idx = item.get('npz_index', -1)
                break

        if target_idx == -1:
            if str(station_id).isdigit():
                target_idx = int(station_id)
            else:
                return jsonify({"error": "Station ID not found in mapping"}), 404

        result = predictor.predict(target_idx)
        if "error" in result:
            return jsonify(result), 500
        return jsonify(result)

    except Exception as e:
        print(f"Prediction Error: {e}")
        return jsonify({"error": str(e)}), 500

# ==========================================
# User Data API Routes (new)
# ==========================================
@app.route('/api/users/stats')
def get_user_stats():
    """返回用户数据全局统计"""
    return jsonify(dm.get_user_stats())

@app.route('/api/users/list')
def get_user_list():
    """
    查询用户列表（分页），支持筛选。
    Query params: role, base_id, page(default=1), page_size(default=50)
    """
    role = request.args.get('role')
    base_id = request.args.get('base_id', type=int)
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 50, type=int)
    page_size = min(page_size, 200)  # 限制最大每页数量

    result = dm.query_users(role=role, base_id=base_id, page=page, page_size=page_size)
    return jsonify(result)

@app.route('/api/users/<user_id>')
def get_user_detail(user_id):
    """获取单个用户的详细信息（画像 + APP 使用统计）"""
    result = dm.get_user_with_trajectory(user_id)
    if result:
        return jsonify(result)
    return jsonify({"error": "User not found"}), 404

@app.route('/api/users/<user_id>/trajectory')
def get_user_trajectory(user_id):
    """
    获取单个用户的轨迹数据。
    Query params: limit(default=all) - 限制返回记录数
    """
    trajectory = dm.get_user_trajectory(user_id)
    if trajectory is None:
        return jsonify({"error": "User trajectory not found"}), 404

    limit = request.args.get('limit', type=int)
    if limit and limit > 0:
        trajectory = trajectory[:limit]

    return jsonify({
        "user_id": user_id,
        "total_records": len(dm.get_user_trajectory(user_id) or []),
        "returned_records": len(trajectory),
        "trajectory": trajectory,
    })

@app.route('/api/users/<user_id>/profile_text')
def get_user_profile_text(user_id):
    """获取用户的英文文本画像"""
    text = dm.get_user_text_profile(user_id)
    if text:
        return jsonify({"user_id": user_id, "profile_text": text})
    return jsonify({"error": "Profile text not found"}), 404

@app.route('/api/users/by_base/<int:base_id>')
def get_users_by_base(base_id):
    """获取连接到某基站的用户列表"""
    user_ids = dm.get_users_by_base(base_id)
    users = []
    for uid in user_ids[:100]:  # 最多返回100个
        profile = dm.get_user_profile(uid)
        if profile:
            users.append({
                "user_id": uid,
                "role": profile.get("role"),
                "age_band": profile.get("age_band"),
                "usage_intensity": profile.get("usage_intensity"),
            })
    return jsonify({
        "base_id": base_id,
        "total_users": len(user_ids),
        "users": users,
    })

@app.route('/api/users/roles')
def get_user_roles():
    """返回所有职业分布"""
    return jsonify({
        role: len(uids) for role, uids in dm.user_roles.items()
    })

# ==========================================
# APP Model API Routes (new)
# ==========================================
@app.route('/api/app_models')
def get_app_models():
    """返回 APP 流量分类模型定义"""
    return jsonify(TRAFFIC_MODELS)

@app.route('/api/app_models/categories')
def get_app_categories():
    """返回所有 APP 类别及其流量模式映射"""
    return jsonify(get_app_category_summary())

# ==========================================
# Server Startup
# ==========================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Monitoring Data Directory: {DATA_DIR}")
    if dm.user_data_dir:
        print(f"User Data Directory: {dm.user_data_dir}")
    print(f"Server running on http://127.0.0.1:{port}")
    app.run(debug=True, port=port)

# FOR ONLINE
# if __name__ == '__main__':
#     print(f"Monitoring Data Directory: {DATA_DIR}")
#     print("Server running on port 7860...")
#     app.run(host='0.0.0.0', port=7860)
