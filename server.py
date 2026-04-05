import os
import json
import numpy as np
import math
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS

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
# Data directory path
DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, 'data')) 

# File path configurations
JSON_PATH = os.path.join(DATA_DIR, 'base2info_extended.json')
TRAFFIC_PATH = os.path.join(DATA_DIR, 'bs_record_energy_normalized_sampled.npz')
SPATIAL_PATH = os.path.join(DATA_DIR, 'spatial_features.npz')
MODEL_PATH = os.path.join(BASE_DIR, 'best_corr_model.pt') 

# ==========================================
# Utility Functions
# ==========================================
def calculate_std_dev(records, avg):
    """Calculates standard deviation for a given set of records and their average."""
    if not records or len(records) < 2:
        return 0
    variance = sum((x - avg) ** 2 for x in records) / len(records)
    return math.sqrt(variance)

def calculate_stats(npz_data, data_list):
    """Calculate global statistics for frontend normalization using NPZ data directly"""
    print("Calculating statistical distribution (Avg & Std)...")
    avgs = [] 
    stds = [] 
    
    # Get bs_record directly from NPZ (shape: num_stations x 672)
    bs_record = npz_data.get('bs_record', None)
    if bs_record is not None:
        for item in data_list:
            idx = item.get('npz_index', 0)
            if idx < bs_record.shape[0]:
                records = bs_record[idx].tolist()
                if records:
                    avg = sum(records) / len(records)
                    std = calculate_std_dev(records, avg)
                else:
                    avg = 0
                    std = 0
                avgs.append(avg)
                stds.append(std)
    else:
        print("Warning: bs_record not found in NPZ data")
    
    def get_percentiles(values):
        """Calculates percentiles to create data brackets for visualization."""
        values.sort()
        n = len(values)
        if n == 0: return {k:0 for k in ['min','max','t1','t2','t3','t4']}
        return {
            "min": values[0],
            "max": values[-1],
            "t1": values[int(n * 0.2)],
            "t2": values[int(n * 0.4)],
            "t3": values[int(n * 0.6)],
            "t4": values[int(n * 0.8)]
        }

    stats_h = get_percentiles(avgs) # Statistics for pillar heights
    stats_c = get_percentiles(stds) # Statistics for pillar colors (stability)
    return stats_h, stats_c

def _convert_numpy_type(val):
    if isinstance(val, np.ndarray): return val.tolist()
    elif isinstance(val, (np.integer, np.int64, np.int32, np.int16)): return int(val)
    elif isinstance(val, (np.floating, np.float64, np.float32)): return float(val)
    elif isinstance(val, bytes): return val.decode('utf-8')
    else: return val

def load_and_process_data(json_path, npz_path, npz_data=None):
    print(f"[DataLoader] Loading basic data...")
    print(f"   - JSON: {json_path}")
    print(f"   - Traffic NPZ : {npz_path}")

    if not os.path.exists(json_path) or not os.path.exists(npz_path):
        print("[DataLoader] Error: Input files not found.")
        return []

    try:
        if npz_data is None:
            npz_data = np.load(npz_path)
        with open(json_path, 'r', encoding='utf-8') as f:
            json_map = json.load(f)
    except Exception as e:
        print(f"[DataLoader] Read error: {e}")
        return []

    # Handle binary strings if present in NPZ
    raw_bs_ids = npz_data['bs_id']
    bs_ids = [x.decode('utf-8') if isinstance(x, bytes) else str(x) for x in raw_bs_ids]
    num_stations = len(bs_ids)
    
    # Only load necessary attributes (exclude large arrays)
    # bs_record is (5326, 672) - too large to convert all at once
    excluded_attrs = {'bs_record', 'hours_in_weekday', 'hours_in_weekend', 'days_in_weekday', 
                      'days_in_weekend', 'days_in_weekday_residual', 'days_in_weekend_residual',
                      'hours_in_weekday_patterns', 'hours_in_weekend_patterns', 
                      'days_in_weekday_patterns', 'days_in_weekend_patterns',
                      'days_in_weekday_residual_patterns', 'days_in_weekend_residual_patterns',
                      'weeks_in_month_residual'}
    
    station_attributes = []
    for key in npz_data.files:
        if key == 'bs_id': continue
        if key in excluded_attrs: continue
        if npz_data[key].shape[0] == num_stations:
            station_attributes.append(key)
    
    print(f"[DataLoader] Loading {len(station_attributes)} lightweight attributes...")
    
    merged_data = []
    match_count = 0

    for i in range(num_stations):
        current_id = bs_ids[i]
        json_key = f"Base_{current_id}" 

        if json_key in json_map:
            match_count += 1
            entry = {
                "id": current_id,
                "npz_index": i, # Store original index for prediction lookups
                "loc": json_map[json_key]["loc"]
            }
            for attr in station_attributes:
                val = npz_data[attr][i]
                entry[attr] = _convert_numpy_type(val)
            merged_data.append(entry)
        
        if (i + 1) % 1000 == 0:
            print(f"[DataLoader] Processed {i + 1}/{num_stations} stations...")

    print(f"[DataLoader] Merge complete! Matched: {match_count}/{num_stations}")
    return merged_data

# ==========================================
# Initialization Sequence
# ==========================================

print("Server Initializing...")

# 1. Load basic station data for frontend display
# Also keep NPZ data in memory for on-demand access to large arrays
print("[Init] Loading NPZ data into cache...")
NPZ_DATA_CACHE = np.load(TRAFFIC_PATH)
print(f"[Init] NPZ loaded with files: {list(NPZ_DATA_CACHE.files)[:5]}...")
ALL_DATA = load_and_process_data(JSON_PATH, TRAFFIC_PATH, npz_data=NPZ_DATA_CACHE)

STATS_HEIGHT = {} 
STATS_COLOR = {}  

if ALL_DATA:
    STATS_HEIGHT, STATS_COLOR = calculate_stats(NPZ_DATA_CACHE, ALL_DATA)
else:
    print("⚠️ CRITICAL WARNING: Data list is empty!")

# 2. Initialize AI Predictor with Spatial Features
predictor = None
if TrafficPredictor:
    try:
        print(f"[AI] Initializing Predictor with model: {MODEL_PATH}")
        # Initialize the predictor using the model and spatial feature files
        predictor = TrafficPredictor(
            model_path=MODEL_PATH, 
            spatial_path=SPATIAL_PATH, 
            traffic_path=TRAFFIC_PATH
        )
        print("[AI] Predictor loaded successfully.")
    except Exception as e:
        print(f"[AI] Failed to load predictor: {e}")

# ==========================================
# API Routes
# ==========================================

@app.route('/')
def index():
    """Serves the main dashboard page."""
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    """Serves static assets (JS, CSS, Images)."""
    return send_from_directory('.', path)

def get_bs_record_for_station(item):
    """Get bs_record from NPZ cache for a station"""
    idx = item.get('npz_index', 0)
    if 'bs_record' in NPZ_DATA_CACHE and idx < NPZ_DATA_CACHE['bs_record'].shape[0]:
        return NPZ_DATA_CACHE['bs_record'][idx].tolist()
    return []

@app.route('/api/stations/locations')
def get_station_locations():
    """Returns a lightweight list of station coordinates and statistical summaries."""
    lightweight_data = []
    # Pre-calculate all stats to avoid repeated NPZ access
    bs_record = NPZ_DATA_CACHE.get('bs_record')
    
    for item in ALL_DATA:
        idx = item.get('npz_index', 0)
        if bs_record is not None and idx < bs_record.shape[0]:
            records = bs_record[idx]
            avg = float(records.mean())
            std = float(records.std())
        else:
            avg = 0
            std = 0
            
        lightweight_data.append({
            "id": item['id'],
            "loc": item['loc'],
            "val_h": avg,
            "val_c": std
            # Note: vals removed to reduce response size
        })
    
    return jsonify({
        "stats_height": STATS_HEIGHT,
        "stats_color": STATS_COLOR,
        "stations": lightweight_data
    })

@app.route('/api/stations/detail/<station_id>')
def get_station_detail(station_id):
    """Returns detailed metadata and stats for a specific station."""
    for item in ALL_DATA:
        if str(item['id']) == str(station_id):
            records = get_bs_record_for_station(item)
            avg = sum(records)/len(records) if records else 0
            std = calculate_std_dev(records, avg)
            
            response = item.copy()
            response['stats'] = {"avg": avg, "std": std}
            response['bs_record'] = records
            return jsonify(response)
            
    return jsonify({"error": "Station not found"}), 404

@app.route('/api/predict/<station_id>')
def predict_traffic(station_id):
    """Triggers the ML model to predict future traffic for a specific station."""
    if not predictor:
        return jsonify({"error": "Prediction service not available"}), 503
    
    try:
        target_idx = -1
        
        # Map Station ID to its internal index in the NPZ file
        for item in ALL_DATA:
            if str(item['id']) == str(station_id):
                target_idx = item.get('npz_index', -1)
                break
        
        if target_idx == -1:
            # Fallback: Check if the ID provided is directly a numerical index
            if str(station_id).isdigit():
                target_idx = int(station_id)
            else:
                return jsonify({"error": "Station ID not found in mapping"}), 404

        # Execute prediction through the ML backend
        result = predictor.predict(target_idx)
        
        if "error" in result:
            return jsonify(result), 500
            
        return jsonify(result)

    except Exception as e:
        print(f"Prediction Error: {e}")
        return jsonify({"error": str(e)}), 500

# Local development server
if __name__ == '__main__':
    print(f"Monitoring Data Directory: {DATA_DIR}")
    print("Server running on http://127.0.0.1:5000")
    app.run(debug=True, port=5000)

# FOR ONLINE
# if __name__ == '__main__':
#     print(f"Monitoring Data Directory: {DATA_DIR}")
#     print("Server running on port 7860...")
#     app.run(host='0.0.0.0', port=7860)  