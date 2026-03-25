import os
import torch
import math
import numpy as np
import requests
import random
import base64
import matplotlib
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
from io import BytesIO
from PIL import Image

# Import V4 Model System 
from hierarchical_flow_matching_training_v4 import HierarchicalFlowMatchingSystemV4
from plot_v4_energy_saving import build_decision, compute_metrics

# =============================================================================
# Config
# =============================================================================
MAPBOX_ACCESS_TOKEN = os.environ.get('MAPBOX_ACCESS_TOKEN', 'YOUR_MAPBOX_TOKEN_HERE') 
MAPBOX_ZOOM = 15  
FETCH_SIZE = 256  
IMAGE_SIZE = 64   
SEED = 42

SPATIAL_DIM = 192
HIDDEN_DIM = 256
POI_DIM = 20
N_LAYERS_LEVEL3 = 6
N_STEPS = 50      


class MapboxSatelliteFetcher:
    """
    Dynamically fetches satellite imagery, strictly aligning with 
    the image preprocessing logic used during training.
    """
    def __init__(self, access_token=MAPBOX_ACCESS_TOKEN, zoom=MAPBOX_ZOOM, fetch_size=FETCH_SIZE, target_size=IMAGE_SIZE):
        self.access_token = access_token
        self.zoom = zoom
        self.fetch_size = fetch_size
        self.target_size = target_size

    def fetch(self, lon, lat, station_id=None, return_pil=False): 
        """ Fetches static satellite map centered at [lon, lat] """
        url = f"https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/{lon},{lat},{self.zoom},0,0/{self.fetch_size}x{self.fetch_size}?access_token={self.access_token}"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            img = Image.open(BytesIO(response.content)).convert("RGB")
            original_pil = img.copy() # Store high-res original for micro-grid slicing
            
            # Resize to model input size (64x64)
            img_resized = img.resize((self.target_size, self.target_size), Image.BILINEAR)
            arr = np.asarray(img_resized, dtype=np.float32) / 255.0
            
            # Convert HWC to CHW format
            chw = arr.transpose(2, 0, 1)
            tensor_np = np.clip(chw, 0.0, 1.0).astype(np.float32, copy=False)
            
            if return_pil:
                return tensor_np, original_pil
            return tensor_np
            
        except Exception as e:
            print(f"[Mapbox Fetcher Error] Station {station_id}: {e}")
            fallback_np = np.zeros((3, self.target_size, self.target_size), dtype=np.float32)
            if return_pil:
                return fallback_np, Image.new('RGB', (self.fetch_size, self.fetch_size), color='black')
            return fallback_np


class TrafficPredictor:
    """Traffic generation model predictor and site selection analyzer"""
    def __init__(self, model_path, spatial_path, traffic_path, local_sat_dir="real_spatial_data/satellite_png", device=None):
        self.device = device if device else torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.local_sat_dir = local_sat_dir
        
        # Load spatial features cache
        if os.path.exists(spatial_path):
            self.data_cache = np.load(spatial_path, allow_pickle=True)
        else:
            raise FileNotFoundError(f"Spatial path {spatial_path} not found!")

        # Load traffic records for validation comparison
        if os.path.exists(traffic_path):
            self.traffic_data = np.load(traffic_path, allow_pickle=True)['bs_record']
        else:
            self.traffic_data = None

        # ==========================================
        # Strictly simulate Dataset length truncation to ensure 
        # normalization extrema are 100% aligned with training.
        # ==========================================
        n_traffic = len(self.traffic_data) if self.traffic_data is not None else float('inf')
        n_poi = len(self.data_cache['poi_distributions'])
        n_coords = len(self.data_cache['coordinates'])
        self.n_valid = min(n_traffic, n_poi, n_coords)

        # Calculate coordinate bounds for normalization
        raw_coords_valid = self.data_cache['coordinates'][:self.n_valid].astype(np.float32)
        self.coord_min = raw_coords_valid.min(axis=0)
        self.coord_max = raw_coords_valid.max(axis=0)

        self.satellite_fetcher = MapboxSatelliteFetcher()
        self.model = self._load_model(model_path)

    def _load_model(self, model_path):
        print(f"Loading V4 Model on {self.device}...")
        model = HierarchicalFlowMatchingSystemV4(
            spatial_dim=SPATIAL_DIM, 
            hidden_dim=HIDDEN_DIM, 
            poi_dim=POI_DIM, 
            n_layers_level3=N_LAYERS_LEVEL3
        ).to(self.device)

        if os.path.exists(model_path):
            ckpt = torch.load(model_path, map_location=self.device, weights_only=False)
            state_dict = ckpt['model_state_dict'] if 'model_state_dict' in ckpt else ckpt
            model.load_state_dict(state_dict)
            print(f"Checkpoint loaded successfully from {model_path}.")
        else:
            raise FileNotFoundError(f"Model checkpoint not found at {model_path}")
        
        model.eval()
        return model

    def compute_energy_control_data(self, real_seq, gen_seq):
        real = np.array(real_seq)
        gen = np.array(gen_seq)
        decision, mask, vol, thr = build_decision(real, gen, window=24, quantile=0.7, min_len=6)
        delta = decision - real
        saving, qoe_loss, qoe_satisfaction, cum_saving = compute_metrics(real, decision)
        return {
            "decision": decision.tolist(),
            "delta": delta.tolist(),
            "saving_rate": float(saving),
            "qoe_rate": float(qoe_satisfaction)
        }

    def predict(self, idx, use_local_img_for_debug=False):
        """Generates traffic predictions and performs LSI spatial analysis"""
        try:
            torch.manual_seed(SEED)
            idx = int(idx)

            # 1. Process POI distributions
            raw_poi = self.data_cache['poi_distributions'][idx].astype(np.float32).copy()
            raw_poi = np.clip(raw_poi, 0.0, None)
            poi_sum = float(raw_poi.sum())
            if poi_sum > 1e-8:
                raw_poi = raw_poi / poi_sum
            else:
                raw_poi = np.zeros_like(raw_poi)
            poi_tensor = torch.from_numpy(raw_poi).unsqueeze(0).to(self.device)

            # 2. Process Geographical Coordinates
            raw_loc = self.data_cache['coordinates'][idx].astype(np.float32)
            lon, lat = raw_loc[0], raw_loc[1] 
            
            # Fetch Satellite Image (Local Debug vs. Remote API)
            if use_local_img_for_debug and os.path.exists(f"{self.local_sat_dir}/{idx}.png"):
                img = Image.open(f"{self.local_sat_dir}/{idx}.png").convert("RGB")
                original_pil = img.copy()
            else:
                _, original_pil = self.satellite_fetcher.fetch(lon, lat, station_id=str(idx), return_pil=True)

            # 3. LSI Heatmap Generation (Location Stability Index)
            lsi_grid, best_idx, best_traffic = self.generate_lsi_heatmap(original_pil, lat, lon, poi_tensor, grid_size=3)
            site_map_b64 = self.create_site_map_base64(original_pil, lsi_grid, best_idx)

            # 4. Map Projections: Convert grid indices back to physical Lat/Lon
            grid_size = 3
            best_row, best_col = best_idx
            
            # Calculate spans based on Web Mercator projection at specific zoom
            lon_span = 360.0 / (2 ** MAPBOX_ZOOM)
            lat_span = lon_span * math.cos(math.radians(lat))
            step_lon = lon_span / grid_size
            step_lat = lat_span / grid_size

            # Offset from base center
            best_lat = lat - (best_row - grid_size // 2) * step_lat
            best_lon = lon + (best_col - grid_size // 2) * step_lon
            best_loc = [float(best_lon), float(best_lat)]

            # 5. Multidimensional NLG (Natural Language Generation) Engine
            best_lsi_value = float(lsi_grid[best_idx])
            avg_lsi_value = float(np.mean(lsi_grid))
            min_lsi_value = float(np.min(lsi_grid))
            
            # Core Performance Metrics
            improvement_avg = ((best_lsi_value - avg_lsi_value) / avg_lsi_value) * 100 if avg_lsi_value > 0 else 0
            spatial_contrast = ((best_lsi_value - min_lsi_value) / min_lsi_value) * 100 if min_lsi_value > 0 else 0

            # Feature A: POI Semantic Mapping
            poi_idx = int(torch.argmax(poi_tensor[0]))
            poi_categories = [
                "Commercial/Retail", "Residential Complex", "Transit Hub", 
                "Corporate/Office", "Public/Recreational", "Industrial Zone", 
                "Mixed-Use Urban", "Educational/Campus"
            ]
            dominant_poi = poi_categories[poi_idx % len(poi_categories)]

            # Feature B: Temporal Tide Analysis (Extract daily peak from 672-hour sequence)
            daily_pattern = best_traffic.reshape(-1, 24).mean(axis=0)
            peak_hour = int(np.argmax(daily_pattern))
            
            if 7 <= peak_hour <= 10: 
                peak_type = "Morning Rush (07:00-10:00)"
            elif 16 <= peak_hour <= 19: 
                peak_type = "Evening Rush (16:00-19:00)"
            elif 11 <= peak_hour <= 15: 
                peak_type = "Midday Active (11:00-15:00)"
            else: 
                peak_type = "Night/Off-peak Active"

            # Load description based on average volume
            avg_load = float(np.mean(best_traffic))
            if avg_load > 6.0: load_desc = "High-Capacity"
            elif avg_load > 3.0: load_desc = "Moderate-Load"
            else: load_desc = "Baseline/Sparse"

            # Dynamic Text Assembly (4-Stage Structure)
            # Stage 1: Spatial Environment Diagnosis
            if spatial_contrast > 40:
                p1 = f"Spatial scan detects a highly heterogeneous {dominant_poi} sector with steep traffic gradients. "
            else:
                p1 = f"Spatial scan indicates a relatively uniform {dominant_poi} matrix. "

            # Stage 2: Temporal Characteristics
            p2 = f"Flow Matching model projects a {load_desc} demand curve, heavily anchored by a {peak_type} signature. "

            # Stage 3: Decision Output
            p3 = f"Micro-grid ({best_row}, {best_col}) is isolated as the topological optimum, yielding a peak Location Stability Index (LSI) of {best_lsi_value:.2f}. "

            # Stage 4: Business Value Assessment
            if improvement_avg > 15:
                p4 = f"Deploying infrastructure here intercepts peak volatility, providing a {improvement_avg:.1f}% structural stability gain over the regional average."
            else:
                p4 = f"This precise coordinate offers a marginal yet critical {improvement_avg:.1f}% variance reduction, ensuring optimal load-balancing."

            explanation_text = p1 + p2 + p3 + p4
            # ===============================================

            # Finalize output sequence
            gen_seq_real = np.clip(best_traffic, 0.0, 10.0)
            real_seq = self.traffic_data[idx].tolist() if self.traffic_data is not None else []

            energy_control_data = None
            if len(real_seq) > 0:
                energy_control_data = self.compute_energy_control_data(real_seq, gen_seq_real.tolist())

            return {
                "station_id": idx,
                "prediction": gen_seq_real.tolist(),
                "real": real_seq,
                "site_map_b64": site_map_b64, 
                "best_loc": best_loc, 
                "explanation": explanation_text,
                "energy_control": energy_control_data,  # <--- 新增这一行，将数据传给前端
                "status": "success"
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e), "status": "failed"}
        
    @torch.no_grad()
    def generate_lsi_heatmap(self, img_pil, base_lat, base_lon, poi_tensor, grid_size=3):
        w, h = img_pil.size
        patch_w, patch_h = w // grid_size, h // grid_size
        
        patches = []
        coords = []
        
        # Calculate precise Lat/Lon spans for 256x256 image area
        lon_span = 360.0 / (2 ** MAPBOX_ZOOM)
        lat_span = lon_span * math.cos(math.radians(base_lat))
        step_lon = lon_span / grid_size
        step_lat = lat_span / grid_size
        
        for i in range(grid_size):
            for j in range(grid_size):
                # Slice and resize patches for model
                box = (j * patch_w, i * patch_h, (j+1) * patch_w, (i+1) * patch_h)
                patch = img_pil.crop(box).resize((IMAGE_SIZE, IMAGE_SIZE), Image.BILINEAR).convert("RGB")
                arr = np.array(patch).transpose(2,0,1) / 255.0
                patches.append(torch.tensor(arr, dtype=torch.float32))
                
                # Normalize coordinates for the model
                offset_lat = base_lat - (i - grid_size//2) * step_lat
                offset_lon = base_lon + (j - grid_size//2) * step_lon
                raw_coord = np.array([offset_lon, offset_lat], dtype=np.float32)
                norm_coord = (raw_coord - self.coord_min) / (self.coord_max - self.coord_min + 1e-8)
                coords.append(torch.tensor(norm_coord, dtype=torch.float32))

        batch_size = grid_size ** 2
        # Assemble GPU Batch
        batch_gpu = {
            'satellite_img': torch.stack(patches).to(self.device),
            'poi_dist': poi_tensor.repeat(batch_size, 1),
            'coords': torch.stack(coords).to(self.device),
            'traffic_seq': torch.zeros(batch_size, 672, dtype=torch.float32).to(self.device) 
        }
        
        # Batch Inference (Computes 9 regions simultaneously)
        output = self.model(batch_gpu, mode='generate', loss_cfg={'n_steps_generate': N_STEPS})
        outputs = output['generated'].cpu().numpy() # [9, 672]
        
        ## LSI Calculation: 1 / (std + epsilon)
        # Higher LSI means lower variance (more stable traffic)
        stds = outputs.std(axis=1)
        lsis = 1.0 / (stds + 1e-6)
        lsi_grid = lsis.reshape(grid_size, grid_size)
        
        # Find the most stable coordinate
        best_idx = np.unravel_index(np.argmax(lsi_grid), lsi_grid.shape)
        best_traffic = outputs[best_idx[0] * grid_size + best_idx[1]]
        
        return lsi_grid, best_idx, best_traffic


    def create_site_map_base64(self, img_pil, lsi_grid, best_idx):
        """Generates heatmap overlay visualization and encodes to Base64"""
        img_arr = np.array(img_pil)
        h, w, _ = img_arr.shape
        grid_h, grid_w = lsi_grid.shape
        
        fig, ax = plt.subplots(figsize=(4, 4), dpi=120)
        
        # Overlay heatmap on satellite image
        ax.imshow(img_arr)
        im = ax.imshow(lsi_grid, cmap='RdYlGn', alpha=0.45, extent=[0, w, h, 0], interpolation='bicubic')
        
        cell_w, cell_h = w / grid_w, h / grid_h
        best_row, best_col = best_idx
        center_x = best_col * cell_w + cell_w / 2
        center_y = best_row * cell_h + cell_h / 2
        
        # Draw target star and LSI indicator
        ax.plot(center_x, center_y, marker='*', color='red', markersize=20, markeredgecolor='white', markeredgewidth=1.5)
        best_lsi = lsi_grid[best_idx]
        ax.annotate(f"LSI: {best_lsi:.2f}", xy=(center_x, center_y), xytext=(10, 10),
                    textcoords='offset points', color='white', fontweight='bold',
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="red", alpha=0.8, edgecolor="white"))
        
        ax.axis('off')
        plt.tight_layout()
        
        # Convert to Base64 for API transmission
        buf = BytesIO()
        fig.savefig(buf, format="png", bbox_inches='tight', transparent=True)
        plt.close(fig)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

if __name__ == "__main__":
    MODEL_PATH = "best_corr_model.pt"
    SPATIAL_PATH = "data/spatial_features.npz"
    TRAFFIC_PATH = "data/bs_record_energy_normalized_sampled.npz"

    predictor = TrafficPredictor(
        model_path=MODEL_PATH,
        spatial_path=SPATIAL_PATH,
        traffic_path=TRAFFIC_PATH
    )

    test_id = 277
    result = predictor.predict(test_id, use_local_img_for_debug=False)
    
    if result.get("status") == "success":
        print(f"Prediction successful for Station {test_id}!")
    else:
        print(f"Prediction failed: {result.get('error')}")