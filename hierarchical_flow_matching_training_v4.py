"""
Hierarchical Flow Matching Training Framework (V4) - Generative Fusion
======================================================================

Complete training pipeline with:
1. Three-level cascaded Flow Matching losses
2. Hierarchical multi-periodic supervision
3. Temporal structure preservation
4. Adaptive learning rate scheduling

[FUSION] Generative Mode: Implicit alignment via conditional flow matching.
         Enhanced with explicit peak conditioning and auxiliary classification.
         Physical Boundary Loss & Bias Correction.
"""

import os
import json
import numpy as np
from typing import Dict, Optional, Tuple, Literal
from tqdm import tqdm

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torch.optim.lr_scheduler import CosineAnnealingLR

from hierarchical_flow_matching_v4 import HierarchicalFlowMatchingV4
from multimodal_spatial_encoder_v4 import MultiModalSpatialEncoderV4


# =============================================================================
# Hierarchical Multi-Periodic Loss Functions
# =============================================================================

class HierarchicalFlowMatchingLoss(nn.Module):
    """
    Hierarchical Flow Matching loss with multi-periodic supervision.

    Combines:
    1. Level 1 (Daily) Flow Matching loss
    2. Level 2 (Weekly) Flow Matching loss
    3. Level 3 (Residual) Flow Matching loss [Peak Conditioned]
    4. Temporal structure preservation loss
    5. Multi-periodic consistency loss
    6. Peak Hour Classification Loss
    7. Physical Boundary Loss (No-Negative Constraint)
    8. Bias Correction Loss (Global Mean Alignment)
    """

    def __init__(self):
        super().__init__()

    # Helper: Physical Constraint
    def compute_boundary_loss(self, predicted_x1: torch.Tensor) -> torch.Tensor:
        """
        Penalize negative values in the estimated traffic.
        Loss = ReLU(-x).mean() * scale
        """
        return F.relu(-predicted_x1).mean() * 10.0

    # Helper: Bias Constraint
    def compute_bias_loss(self, generated: torch.Tensor, real: torch.Tensor) -> torch.Tensor:
        """
        Fix 'Parallel Lines' issue by forcing global mean alignment.
        """
        gen_mean = generated.mean(dim=1)  # [B]
        real_mean = real.mean(dim=1)      # [B]
        return F.l1_loss(gen_mean, real_mean) * 20.0

    def compute_level1_loss(
        self,
        model: HierarchicalFlowMatchingV4,
        real_traffic: torch.Tensor,
        spatial_cond_level1: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor]: # [MODIFIED] Returns tuple
        """
        Level 1 (Day-Type Templates) Flow Matching loss.
        """
        B = real_traffic.shape[0]
        device = real_traffic.device

        # 672 hourly samples = 28 days * 24 hours
        steps_per_day = 24
        n_days = 28
        real_reshaped = real_traffic.reshape(B, n_days, steps_per_day)  # [B, 28, 24]

        # Assume sequence starts on Monday
        day_of_week = torch.arange(n_days, device=device) % 7
        weekday_idx = torch.where(day_of_week < 5)[0]
        weekend_idx = torch.where(day_of_week >= 5)[0]

        weekday_pattern = real_reshaped.index_select(1, weekday_idx).mean(dim=1)  # [B, 24]
        weekend_pattern = real_reshaped.index_select(1, weekend_idx).mean(dim=1)  # [B, 24]

        # Target is concatenation: [weekday(24), weekend(24)] -> [B, 48]
        x1 = torch.cat([weekday_pattern, weekend_pattern], dim=1)

        # Sample noise
        x0 = torch.randn_like(x1)

        # Sample time
        t = torch.rand(B, 1, device=device)

        # Interpolation
        x_t = t * x1 + (1 - t) * x0

        # Target velocity
        v_target = x1 - x0

        # Predict velocity
        v_pred = model(x_t, t, spatial_cond_level1, level=1)

        # Flow Matching loss
        loss_fm = F.mse_loss(v_pred, v_target)

        # Boundary Loss for Level 1
        x1_est = x_t + (1 - t) * v_pred
        loss_boundary = self.compute_boundary_loss(x1_est)

        return loss_fm, loss_boundary

    def compute_level2_loss(
        self,
        model: HierarchicalFlowMatchingV4,
        real_traffic: torch.Tensor,
        spatial_cond_level2: torch.Tensor,
        spatial_cond_level1: torch.Tensor,
        daily_pattern: Optional[torch.Tensor] = None,
        use_teacher_forcing: bool = True,
        n_steps_generate: int = 10,
    ) -> Tuple[torch.Tensor, torch.Tensor]: # [MODIFIED] Returns tuple
        """
        Level 2 (Weekly Pattern, 168 hours) Flow Matching loss.
        """
        B = real_traffic.shape[0]
        device = real_traffic.device

        steps_per_day = 24
        n_days = 28
        n_weeks = 4
        real_reshaped = real_traffic.reshape(B, n_days, steps_per_day)  # [B, 28, 24]

        # Weekly pattern ground truth
        weekly_days = []
        for dow in range(7):
            idx = torch.tensor([dow + 7 * w for w in range(n_weeks)], device=device, dtype=torch.long)
            weekly_days.append(real_reshaped.index_select(1, idx).mean(dim=1))  # [B, 24]
        weekly_pattern = torch.stack(weekly_days, dim=1).reshape(B, 7 * steps_per_day)  # [B, 168]

        x1 = weekly_pattern  # target weekly pattern

        # Get day-type templates (weekday/weekend)
        if daily_pattern is None or not use_teacher_forcing:
            with torch.no_grad():
                daily_pattern = model.generate_daily_pattern(
                    spatial_cond_level1, n_steps=n_steps_generate
                )
        else:
            # Teacher forcing
            day_of_week = torch.arange(n_days, device=device) % 7
            weekday_idx = torch.where(day_of_week < 5)[0]
            weekend_idx = torch.where(day_of_week >= 5)[0]
            weekday_pattern = real_reshaped.index_select(1, weekday_idx).mean(dim=1)  # [B, 24]
            weekend_pattern = real_reshaped.index_select(1, weekend_idx).mean(dim=1)  # [B, 24]
            daily_pattern = torch.cat([weekday_pattern, weekend_pattern], dim=1)  # [B, 48]

        # Sample noise
        x0 = torch.randn_like(x1)

        # Sample time
        t = torch.rand(B, 1, device=device)

        # Interpolation
        x_t = t * x1 + (1 - t) * x0

        # Target velocity
        v_target = x1 - x0

        # Predict velocity
        v_pred = model(x_t, t, spatial_cond_level2, level=2, daily_pattern=daily_pattern)

        # Flow Matching loss
        loss_fm = F.mse_loss(v_pred, v_target)

        # Boundary Loss for Level 2
        x1_est = x_t + (1 - t) * v_pred
        loss_boundary = self.compute_boundary_loss(x1_est)

        return loss_fm, loss_boundary

    def compute_level3_loss(
        self,
        model: HierarchicalFlowMatchingV4,
        real_traffic: torch.Tensor,
        spatial_cond_level3: torch.Tensor,
        spatial_cond_level2: torch.Tensor,
        spatial_cond_level1: torch.Tensor,
        peak_hour_gt: torch.Tensor,  # Explicit Peak GT
        daily_pattern: Optional[torch.Tensor] = None,
        weekly_trend: Optional[torch.Tensor] = None,
        use_teacher_forcing: bool = True,
        n_steps_generate: int = 10,
    ) -> Tuple[torch.Tensor, torch.Tensor]: # [MODIFIED] Returns tuple
        """
        Level 3 (Residual over 672 hours) Flow Matching loss.
        Models fine-grained hourly fluctuations after removing periodic trends.
        """
        B = real_traffic.shape[0]
        device = real_traffic.device

        steps_per_day = 24
        n_days = 28
        n_weeks = 4
        real_reshaped = real_traffic.reshape(B, n_days, steps_per_day)  # [B, 28, 24]

        # Ground-truth weekly pattern (168)
        weekly_days = []
        for dow in range(7):
            idx = torch.tensor([dow + 7 * w for w in range(n_weeks)], device=device, dtype=torch.long)
            weekly_days.append(real_reshaped.index_select(1, idx).mean(dim=1))  # [B, 24]
        weekly_pattern_gt = torch.stack(weekly_days, dim=1).reshape(B, 7 * steps_per_day)  # [B, 168]
        
        # Get daily pattern and weekly trend
        if use_teacher_forcing:
            # Teacher forcing
            day_of_week = torch.arange(n_days, device=device) % 7
            weekday_idx = torch.where(day_of_week < 5)[0]
            weekend_idx = torch.where(day_of_week >= 5)[0]
            weekday_pattern = real_reshaped.index_select(1, weekday_idx).mean(dim=1)  # [B, 24]
            weekend_pattern = real_reshaped.index_select(1, weekend_idx).mean(dim=1)  # [B, 24]
            daily_pattern = torch.cat([weekday_pattern, weekend_pattern], dim=1)  # [B, 48]
            weekly_trend = weekly_pattern_gt
        else:
            if daily_pattern is None:
                with torch.no_grad():
                    daily_pattern = model.generate_daily_pattern(
                        spatial_cond_level1, n_steps=n_steps_generate
                    )

            if weekly_trend is None:
                with torch.no_grad():
                    weekly_trend = model.generate_weekly_trend(
                        daily_pattern, spatial_cond_level2, n_steps=n_steps_generate
                    )

        # Construct periodic component (coarse signal) from weekly pattern
        coarse_signal = weekly_trend.repeat(1, n_weeks)  # [B, 672]

        # Target residual
        x1 = real_traffic - coarse_signal  # [B, 672]

        # Sample noise
        x0 = 0.1 * torch.randn_like(x1)

        # Sample time
        t = torch.rand(B, 1, device=device)

        # Interpolation
        x_t = t * x1 + (1 - t) * x0

        # Target velocity
        v_target = x1 - x0

        # Predict velocity
        # Pass peak_hour_gt to model
        v_pred = model(
            x_t, t, spatial_cond_level3, level=3,
            daily_pattern=daily_pattern,
            weekly_trend=weekly_trend,
            coarse_signal=coarse_signal,
            peak_hour=peak_hour_gt
        )

        # Flow Matching loss
        loss_fm = F.mse_loss(v_pred, v_target)

        # Boundary Loss for Level 3
        # Ensure that (Coarse + Residual) >= 0
        residual_est = x_t + (1 - t) * v_pred
        final_traffic_est = coarse_signal + residual_est
        loss_boundary = self.compute_boundary_loss(final_traffic_est)

        return loss_fm, loss_boundary

    def compute_temporal_structure_loss(
        self,
        generated: torch.Tensor,
        real: torch.Tensor,
    ) -> torch.Tensor:
        """
        Temporal structure preservation loss.
        """
        d_gen = generated[..., 1:] - generated[..., :-1]
        d_real = real[..., 1:] - real[..., :-1]
        loss_deriv = F.mse_loss(d_gen, d_real)
        return loss_deriv

    def compute_multi_periodic_consistency_loss(
        self,
        generated: torch.Tensor,
        real: torch.Tensor,
    ) -> torch.Tensor:
        """
        Multi-periodic consistency loss.
        """
        B = generated.shape[0]
        device = generated.device

        steps_per_day = 24
        n_days = 28
        n_weeks = 4

        gen_days = generated.reshape(B, n_days, steps_per_day)  # [B, 28, 24]
        real_days = real.reshape(B, n_days, steps_per_day)

        # Daily mean pattern
        gen_daily = gen_days.mean(dim=1)
        real_daily = real_days.mean(dim=1)
        loss_daily = F.mse_loss(gen_daily, real_daily)

        # Weekly pattern
        def weekly_pattern(x_days: torch.Tensor) -> torch.Tensor:
            days = []
            for dow in range(7):
                idx = torch.tensor([dow + 7 * w for w in range(n_weeks)], device=device, dtype=torch.long)
                days.append(x_days.index_select(1, idx).mean(dim=1))  # [B, 24]
            return torch.stack(days, dim=1).reshape(B, 7 * steps_per_day)

        gen_weekly = weekly_pattern(gen_days)
        real_weekly = weekly_pattern(real_days)
        loss_weekly = F.mse_loss(gen_weekly, real_weekly)

        return loss_daily + loss_weekly

    # Pearson Correlation Loss
    def compute_correlation_loss(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """
        Loss = 1 - Correlation. 强迫模型优化波形形状。
        """
        # 1. Center the data
        pred_mean = pred - pred.mean(dim=1, keepdim=True)
        target_mean = target - target.mean(dim=1, keepdim=True)

        # 2. Normalize
        pred_norm = torch.norm(pred_mean, p=2, dim=1) + 1e-8
        target_norm = torch.norm(target_mean, p=2, dim=1) + 1e-8

        # 3. Calculate cosine similarity (i.e., correlation after mean-shifting)
        cosine_sim = (pred_mean * target_mean).sum(dim=1) / (pred_norm * target_norm)

        # 4. Loss = 1 - Correlation
        return 1.0 - cosine_sim.mean()

    def forward(
        self,
        model: HierarchicalFlowMatchingV4,
        real_traffic: torch.Tensor,
        spatial_cond: Dict[str, torch.Tensor] | torch.Tensor,
        fusion_method: str = 'generative',
        lambda_level1: float = 1.0,
        lambda_level2: float = 1.0,
        lambda_level3: float = 1.0,
        lambda_temporal: float = 0.1,
        lambda_periodic: float = 0.1,
        lambda_corr: float = 0.5, 
        lambda_boundary: float = 1.0, 
        lambda_bias: float = 1.0, 
        teacher_forcing_ratio: float = 1.0,
        n_steps_generate: int = 10,
        **kwargs
    ) -> Dict[str, torch.Tensor]:
        """
        Compute combined hierarchical loss.
        """
        if isinstance(spatial_cond, torch.Tensor):
            # Compatibility fallback
            spatial_cond = {
                'level1_cond': spatial_cond,
                'level2_cond': spatial_cond,
                'level3_cond': spatial_cond,
                'pred_peak_logits': None 
            }

        # ---------------------------------------------------------------------
        # 1. Derive Ground Truth Peak Hour
        # ---------------------------------------------------------------------
        # Reshape to [B, days, 24] -> mean daily pattern -> argmax
        B = real_traffic.shape[0]
        avg_daily = real_traffic.reshape(B, -1, 24).mean(dim=1)
        peak_hour_gt = avg_daily.argmax(dim=1) # [B] (0-23)
        
        # 2. Auxiliary Classification Loss
        pred_peak_logits = spatial_cond.get('pred_peak_logits', None)
        if pred_peak_logits is not None:
            loss_peak_cls = F.cross_entropy(pred_peak_logits, peak_hour_gt)
        else:
            loss_peak_cls = torch.tensor(0.0, device=real_traffic.device)

        # Determine teacher forcing
        use_tf = torch.rand(1).item() < teacher_forcing_ratio

        # ---------------------------------------------------------------------
        # 3. Compute Level Losses (FM + Boundary)
        # ---------------------------------------------------------------------
        loss_l1_fm, loss_l1_bound = self.compute_level1_loss(
            model, real_traffic, spatial_cond['level1_cond']
        )
        loss_l2_fm, loss_l2_bound = self.compute_level2_loss(
            model,
            real_traffic,
            spatial_cond_level2=spatial_cond['level2_cond'],
            spatial_cond_level1=spatial_cond['level1_cond'],
            use_teacher_forcing=use_tf,
            n_steps_generate=n_steps_generate,
        )
        # Pass peak_hour_gt
        loss_l3_fm, loss_l3_bound = self.compute_level3_loss(
            model,
            real_traffic,
            spatial_cond_level3=spatial_cond['level3_cond'],
            spatial_cond_level2=spatial_cond['level2_cond'],
            spatial_cond_level1=spatial_cond['level1_cond'],
            peak_hour_gt=peak_hour_gt, # Explicit GT
            use_teacher_forcing=use_tf,
            n_steps_generate=n_steps_generate,
        )

        # ---------------------------------------------------------------------
        # 4. Aux Losses (Temporal, Periodic, Bias)
        # ---------------------------------------------------------------------
        loss_temporal = torch.tensor(0.0, device=real_traffic.device)
        loss_periodic = torch.tensor(0.0, device=real_traffic.device)
        loss_bias = torch.tensor(0.0, device=real_traffic.device)
        loss_corr = torch.tensor(0.0, device=real_traffic.device) 

        # Increase Generation Sampling Frequency
        # If lambda_corr is significant (>0.1), we increase the sampling probability from 30% to 60%
        # This enables more frequent computation of the Correlation Loss
        prob_threshold = 0.6 if lambda_corr > 0.1 else 0.3

        # Only compute generation-based losses occasionally to save time
        should_compute_gen_losses = (lambda_temporal > 0 or lambda_periodic > 0 or lambda_bias > 0 or lambda_corr > 0)
        
        if should_compute_gen_losses and torch.rand(1).item() < 0.3:
            with torch.no_grad():
                # Must provide peak_hour for generation
                generated, _ = model.generate_hierarchical(
                    spatial_cond, 
                    peak_hour=peak_hour_gt, 
                    n_steps_per_level=n_steps_generate
                )
            
            if lambda_corr > 0:
                loss_corr = self.compute_correlation_loss(generated, real_traffic)

            if lambda_temporal > 0:
                loss_temporal = self.compute_temporal_structure_loss(generated, real_traffic)
            
            if lambda_periodic > 0:
                loss_periodic = self.compute_multi_periodic_consistency_loss(generated, real_traffic)
            
            if lambda_bias > 0:
                loss_bias = self.compute_bias_loss(generated, real_traffic)

        # ---------------------------------------------------------------------
        # 5. Combined Loss
        # ---------------------------------------------------------------------
        
        # FM Loss
        loss_fm_total = (
            lambda_level1 * loss_l1_fm +
            lambda_level2 * loss_l2_fm +
            lambda_level3 * loss_l3_fm
        )

        # Boundary Loss
        loss_boundary_total = lambda_boundary * (loss_l1_bound + loss_l2_bound + loss_l3_bound)

        # Bias Loss
        loss_bias_total = lambda_bias * loss_bias

        # Peak Classification Weight (static 0.5 for now)
        lambda_peak = 5.0
        
        total_loss = (
            loss_fm_total +
            loss_boundary_total +
            loss_bias_total +
            lambda_temporal * loss_temporal +
            lambda_periodic * loss_periodic +
            lambda_peak * loss_peak_cls +
            lambda_corr * loss_corr  # 加入总 Loss
        )

        return {
            'loss_level1': loss_l1_fm,
            'loss_level2': loss_l2_fm,
            'loss_level3': loss_l3_fm,
            'loss_boundary': loss_boundary_total, 
            'loss_bias': loss_bias_total,        
            'loss_temporal': loss_temporal,
            'loss_periodic': loss_periodic,
            'loss_peak_cls': loss_peak_cls,       
            'loss_corr': loss_corr,
            'loss_total': total_loss,
        }
    
    


# =============================================================================
# Complete Hierarchical Flow Matching Model with Encoder
# =============================================================================

class HierarchicalFlowMatchingSystemV4(nn.Module):
    """
    Complete system combining:
    - Multi-modal spatial encoder
    - Hierarchical Flow Matching model
    """

    def __init__(
        self,
        spatial_dim: int = 192,
        hidden_dim: int = 256,
        poi_dim: int = 20,
        n_layers_level3: int = 6,
        fusion_method: Literal['generative', 'contrastive'] = 'generative' # Default
    ):
        super().__init__()
        self.fusion_method = fusion_method
        self.spatial_dim = spatial_dim

        # 1. Environment Encoder (Multi-modal)
        self.spatial_encoder = MultiModalSpatialEncoderV4(spatial_dim, poi_dim)
        
        # NOTE: No TrafficCLIPEncoder in Generative Mode
        self.traffic_encoder = None

        # 2. Flow Matching Generative Model
        self.fm_model = HierarchicalFlowMatchingV4(spatial_dim, hidden_dim, n_layers_level3)
        
        # 3. Loss
        self.loss_fn = HierarchicalFlowMatchingLoss()

    def forward(self, batch: Dict, mode: str = 'train', loss_cfg: Optional[Dict] = None) -> Dict:
        """
        Args:
            batch: dict with spatial and traffic data
            mode: 'train' or 'generate'
        Returns:
            outputs: dict with losses or generated samples
        """
        # Encode spatial features
        spatial_cond_dict = self.spatial_encoder(batch)
        loss_cfg = loss_cfg or {}

        if mode == 'train':
            real_traffic = batch['traffic_seq']
            
            # Calculate Losses
            losses = self.loss_fn(
                model=self.fm_model,
                real_traffic=real_traffic,
                spatial_cond=spatial_cond_dict,
                fusion_method=self.fusion_method,
                **loss_cfg
            )
            return {'losses': losses}

        elif mode == 'generate':
            # Inference logic: Explicit Peak Conditioning
            # 1. Use the auxiliary head to predict peak location
            pred_logits = spatial_cond_dict['pred_peak_logits']
            pred_peak_hour = pred_logits.argmax(dim=1) # [B]
            
            # 2. Allow manual override if 'manual_peak_hour' is in batch
            if 'manual_peak_hour' in batch:
                pred_peak_hour = batch['manual_peak_hour']

            # Generate hierarchical samples
            generated, intermediates = self.fm_model.generate_hierarchical(
                spatial_cond_dict,
                peak_hour=pred_peak_hour,
                n_steps_per_level=loss_cfg.get('n_steps_generate', 50),
            )
            return {'generated': generated, 'intermediates': intermediates, 'pred_peak_hour': pred_peak_hour}

        else:
            raise ValueError(f"Unknown mode: {mode}")


# =============================================================================
# Trainer
# =============================================================================

class HierarchicalFlowMatchingTrainerV4:
    """
    Trainer for Hierarchical Flow Matching V4.
    """

    def __init__(
        self,
        model: HierarchicalFlowMatchingSystemV4,
        train_loader: DataLoader,
        val_loader: DataLoader,
        lr: float = 1e-4,
        weight_decay: float = 0.01,
        checkpoint_dir: str = "checkpoints_hfm_v4",
        lambda_level1: float = 1.0,
        lambda_level2: float = 1.0,
        lambda_level3: float = 1.0,
        lambda_temporal: float = 0.1,
        lambda_periodic: float = 0.1,
        lambda_boundary: float = 1.0, 
        lambda_bias: float = 1.0,     
        lambda_corr: float = 0.5, 
        warmup_epochs: int = 5,
    ):
        self.model = model
        self.train_loader = train_loader
        self.val_loader = val_loader
        self.checkpoint_dir = checkpoint_dir

        # Loss weights
        self.loss_cfg = {
            'lambda_level1': lambda_level1,
            'lambda_level2': lambda_level2,
            'lambda_level3': lambda_level3,
            'lambda_temporal': lambda_temporal,
            'lambda_periodic': lambda_periodic,
            'lambda_boundary': lambda_boundary, 
            'lambda_bias': lambda_bias,        
            'lambda_corr': lambda_corr, 
            'teacher_forcing_ratio': 1.0,
            'n_steps_generate': 10
        }

        # Warmup
        self.warmup_epochs = warmup_epochs
        self.base_lr = lr

        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model = self.model.to(self.device)

        # Optimizer
        self.optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=lr,
            weight_decay=weight_decay,
            betas=(0.9, 0.99),
        )

        os.makedirs(checkpoint_dir, exist_ok=True)

        # Training history
        self.history = {
            'train_loss': [],
            'val_loss': [],
            'train_loss_level1': [],
            'train_loss_level2': [],
            'train_loss_level3': [],
            'train_loss_temporal': [],
            'train_loss_periodic': [],
            'train_loss_peak_cls': [], 
            'train_loss_boundary': [], 
            'train_loss_bias': [],     
            'train_loss_corr': [], 
            'val_mae': [],
            'val_corr': [],
            'val_var_ratio': [],
            'lr': [],
        }

    def get_lr_scale(self, epoch: int, total_epochs: int) -> float:
        """Get learning rate scale with warmup and cosine decay."""
        if epoch < self.warmup_epochs:
            return (epoch + 1) / self.warmup_epochs
        else:
            progress = (epoch - self.warmup_epochs) / (total_epochs - self.warmup_epochs)
            return 0.5 * (1 + np.cos(np.pi * progress))

    def set_lr(self, scale: float):
        """Set learning rate."""
        for param_group in self.optimizer.param_groups:
            param_group['lr'] = self.base_lr * scale

    def train_epoch(self, epoch: int, total_epochs: int) -> Dict[str, float]:
        """Train one epoch."""
        self.model.train()

        # Set learning rate
        lr_scale = self.get_lr_scale(epoch, total_epochs)
        self.set_lr(lr_scale)
        current_lr = self.optimizer.param_groups[0]['lr']

        # Teacher forcing ratio
        self.loss_cfg['teacher_forcing_ratio'] = max(0.5, 1.0 - epoch / (2 * total_epochs))

        total_loss = 0.0
        loss_level1 = 0.0
        loss_level2 = 0.0
        loss_level3 = 0.0
        loss_temporal = 0.0
        loss_periodic = 0.0
        loss_peak_cls = 0.0 
        loss_boundary = 0.0 
        loss_bias = 0.0     
        loss_corr = 0.0 

        pbar = tqdm(self.train_loader, desc=f"Epoch {epoch + 1} [Train]")
        for batch in pbar:
            batch = {
                k: v.to(self.device) if isinstance(v, torch.Tensor) else v
                for k, v in batch.items()
            }

            # Forward pass
            self.optimizer.zero_grad()
            output = self.model(
                batch,
                mode='train',
                loss_cfg=self.loss_cfg,
            )
            losses = output['losses']

            # Total loss
            total_batch_loss = losses['loss_total']

            # Backward pass
            total_batch_loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
            self.optimizer.step()

            # Accumulate losses
            total_loss += total_batch_loss.item()
            loss_level1 += losses['loss_level1'].item()
            loss_level2 += losses['loss_level2'].item()
            loss_level3 += losses['loss_level3'].item()
            loss_temporal += losses.get('loss_temporal', torch.tensor(0.0)).item()
            loss_periodic += losses.get('loss_periodic', torch.tensor(0.0)).item()
            loss_peak_cls += losses.get('loss_peak_cls', torch.tensor(0.0)).item()
            loss_boundary += losses.get('loss_boundary', torch.tensor(0.0)).item()
            loss_bias += losses.get('loss_bias', torch.tensor(0.0)).item()
            loss_corr += losses.get('loss_corr', torch.tensor(0.0)).item() 

            # Update progress bar
            pbar.set_postfix({
                'loss': total_loss / (len(pbar) + 1),
                'corr': loss_corr / (len(pbar) + 1),
                'peak': loss_peak_cls / (len(pbar) + 1),
                'bnd': loss_boundary / (len(pbar) + 1),
                'bias': loss_bias / (len(pbar) + 1),
                'lr': f'{current_lr:.2e}',
            })

        n_batches = len(self.train_loader)
        return {
            'loss_total': total_loss / n_batches,
            'loss_level1': loss_level1 / n_batches,
            'loss_level2': loss_level2 / n_batches,
            'loss_level3': loss_level3 / n_batches,
            'loss_temporal': loss_temporal / n_batches,
            'loss_periodic': loss_periodic / n_batches,
            'loss_peak_cls': loss_peak_cls / n_batches,
            'loss_boundary': loss_boundary / n_batches,
            'loss_bias': loss_bias / n_batches,
            'loss_corr': loss_corr / n_batches, 
            'lr': current_lr,
        }

    @torch.no_grad()
    def validate(self, epoch: int) -> Dict[str, float]:
        """Validate."""
        self.model.eval()

        total_loss = 0.0
        all_mae = []
        all_corr = []
        all_var_ratio = []

        pbar = tqdm(self.val_loader, desc=f"Epoch {epoch + 1} [Val]")
        for batch in pbar:
            batch = {
                k: v.to(self.device) if isinstance(v, torch.Tensor) else v
                for k, v in batch.items()
            }

            # Loss
            output = self.model(
                batch,
                mode='train',
                loss_cfg=self.loss_cfg,
            )
            losses = output['losses']
            total_loss += losses['loss_total'].item()

            # Generate samples
            # Note: generate now internally handles peak_hour logic in System.forward
            gen_output = self.model(
                batch,
                mode='generate',
                loss_cfg={'n_steps_generate': 50},
            )
            real = batch['traffic_seq'].cpu().numpy()
            generated = gen_output['generated'].cpu().numpy()

            # Metrics
            mae = np.mean(np.abs(real - generated))
            all_mae.append(mae)

            # Variance ratio
            real_var = np.var(real, axis=1).mean()
            gen_var = np.var(generated, axis=1).mean()
            var_ratio = gen_var / (real_var + 1e-8)
            all_var_ratio.append(var_ratio)

            # Correlation
            for i in range(len(real)):
                r_std = np.std(real[i])
                g_std = np.std(generated[i])
                if r_std > 1e-6 and g_std > 1e-6:
                    corr = np.corrcoef(real[i], generated[i])[0, 1]
                    if not np.isnan(corr):
                        all_corr.append(corr)

        n_batches = len(self.val_loader)
        return {
            'loss_total': total_loss / n_batches,
            'mae': np.mean(all_mae),
            'correlation': np.mean(all_corr) if all_corr else 0.0,
            'var_ratio': np.mean(all_var_ratio),
        }

    def train(self, epochs: int):
        """Full training loop."""
        print("=" * 80)
        print("Hierarchical Flow Matching V4 - Training")
        print(f"Fusion Method: {self.model.fusion_method}")
        print("=" * 80)
        print(f"Device: {self.device}")
        print(f"Epochs: {epochs}")
        print(f"Base learning rate: {self.base_lr:.2e}")
        print("=" * 80)

        # [修改 1] 初始化两个最佳指标跟踪变量
        best_val_loss = float('inf')
        best_val_corr = -1.0  # 初始化相关性为 -1

        for epoch in range(epochs):
            # Train
            train_losses = self.train_epoch(epoch, epochs)

            # Validate
            val_losses = self.validate(epoch)

            # Print summary
            print(f"\nEpoch {epoch + 1}/{epochs}")
            print(f"  Train Loss: {train_losses['loss_total']:.6f}")
            print(f"  Peak Cls Loss: {train_losses['loss_peak_cls']:.6f}")
            print(f"  Boundary Loss: {train_losses['loss_boundary']:.6f}")
            print(f"  Bias Loss: {train_losses['loss_bias']:.6f}")
            print(f"  Val Loss: {val_losses['loss_total']:.6f}")
            print(f"  Val MAE: {val_losses['mae']:.4f}")
            print(f"  Val Correlation: {val_losses['correlation']:.4f}")
            print(f"  Val Var Ratio: {val_losses['var_ratio']:.4f}")

            # Save history
            self.history['train_loss'].append(train_losses['loss_total'])
            self.history['val_loss'].append(val_losses['loss_total'])
            self.history['train_loss_level1'].append(train_losses['loss_level1'])
            self.history['train_loss_level2'].append(train_losses['loss_level2'])
            self.history['train_loss_level3'].append(train_losses['loss_level3'])
            self.history['train_loss_temporal'].append(train_losses['loss_temporal'])
            self.history['train_loss_periodic'].append(train_losses['loss_periodic'])
            self.history['train_loss_peak_cls'].append(train_losses['loss_peak_cls'])
            self.history['train_loss_boundary'].append(train_losses['loss_boundary'])
            self.history['train_loss_bias'].append(train_losses['loss_bias'])
            self.history['val_mae'].append(val_losses['mae'])
            self.history['val_corr'].append(val_losses['correlation'])
            self.history['val_var_ratio'].append(val_losses['var_ratio'])
            self.history['lr'].append(train_losses['lr'])
            
            # Logic A: Save the model with the lowest loss (as the mathematically optimal fallback)
            if val_losses['loss_total'] < best_val_loss:
                best_val_loss = val_losses['loss_total']
                self.save_checkpoint(epoch, val_losses, filename='best_loss_model.pt')
                print(f"  ✓ [Best Loss model saved! Loss: {best_val_loss:.4f}]")

            # Logic B: Save the model with the highest correlation (as the business-practical best)
            if val_losses['correlation'] > best_val_corr:
                best_val_corr = val_losses['correlation']
                self.save_checkpoint(epoch, val_losses, filename='best_corr_model.pt')
                print(f"  ★ [Best Correlation model saved! Corr: {best_val_corr:.4f}]")

            # Always save the latest version
            self.save_checkpoint(epoch, val_losses, filename='latest_model.pt')

        # Save history
        self.save_history()

        print("\n" + "=" * 80)
        print("Training Completed!")
        print(f"Best validation loss: {best_val_loss:.6f}")
        print(f"Best validation corr: {best_val_corr:.4f}") # 打印最佳相关性
        print(f"Checkpoints saved to: {self.checkpoint_dir}")
        print("=" * 80)

    def save_checkpoint(self, epoch: int, losses: Dict, filename: str = 'best_model.pt'):
        """Save checkpoint."""
        checkpoint = {
            'epoch': epoch,
            'model_state_dict': self.model.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'losses': losses,
            'history': self.history,
        }

        path = os.path.join(self.checkpoint_dir, filename)
        torch.save(checkpoint, path)

    def save_history(self):
        """Save training history."""
        path = os.path.join(self.checkpoint_dir, 'training_history.json')

        history_serializable = {}
        for key, values in self.history.items():
            history_serializable[key] = [
                float(v) if isinstance(v, (np.floating, np.integer)) else v
                for v in values
            ]

        with open(path, 'w') as f:
            json.dump(history_serializable, f, indent=2)