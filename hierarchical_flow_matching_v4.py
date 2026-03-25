"""
Hierarchical Flow Matching with Mamba/SSM Backbone (V4) - Generative Version
============================================================================

Architecture: Pure Diffusion/Flow Matching (No GANs).
Fusion Method: Generative (Implicit alignment via conditional generation).

Core improvements over V3:
1. Three-level cascaded Flow Matching architecture.
2. Multi-modal spatial context encoding.
3. Long-sequence modeling backbone.
4. Explicit Peak Conditioning.
5. Physical Constraints (Non-negative output enforced).

Author: Optimization Team
Date: 2026-01-21
"""

import os
import sys
import math
import numpy as np
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


# =============================================================================
# Mamba/SSM Backbone for Long Sequence Modeling
# =============================================================================

@dataclass
class MambaConfig:
    """Configuration for Mamba block."""
    d_model: int = 256
    d_state: int = 64
    d_conv: int = 4
    expand: int = 2
    dt_rank: str = "auto"
    dt_min: float = 0.001
    dt_max: float = 0.1
    dt_init: str = "random"
    dt_scale: float = 1.0
    dt_init_floor: float = 1e-4
    bias: bool = True
    conv_bias: bool = True
    pscan: bool = True
    use_cuda: bool = True


def _selective_scan_diagonal(
    log_a: torch.Tensor,  # [B, L, N]
    b: torch.Tensor,      # [B, L, N]
) -> torch.Tensor:
    """
    Parallel (vectorized) diagonal linear recurrence:
        h_t = a_t * h_{t-1} + b_t,  h_{-1}=0
    where a_t = exp(log_a_t), computed without Python loops.
    """
    # log_p[t] = sum_{i<=t} log_a[i]
    log_p = torch.cumsum(log_a, dim=1)  # [B, L, N]
    inv_p = torch.exp(-log_p)
    s = torch.cumsum(b * inv_p, dim=1)  # [B, L, N]
    h = torch.exp(log_p) * s
    return h


class Mamba(nn.Module):
    """
    Mamba block for efficient long-sequence modeling.

    Based on: "Mamba: Linear-Time Sequence Modeling with Selective State Spaces"
    Pure-PyTorch implementation (vectorized diagonal selective scan) for traffic
    sequence generation (no external kernels / dependencies).
    """

    def __init__(self, config: MambaConfig):
        super().__init__()
        self.config = config

        d_model = config.d_model
        d_state = config.d_state
        d_conv = config.d_conv
        expand = config.expand

        self.d_inner = int(expand * d_model)

        # (1) Input projection: x -> (u, gate)
        self.in_proj = nn.Linear(d_model, 2 * self.d_inner, bias=config.bias)

        # (2) Depthwise conv for short-range mixing (Mamba-style local context)
        self.dwconv = nn.Conv1d(
            in_channels=self.d_inner,
            out_channels=self.d_inner,
            kernel_size=d_conv,
            padding=d_conv - 1,
            groups=self.d_inner,
            bias=config.conv_bias,
        )

        # (3) Input-dependent SSM parameters (B, C, dt)
        self.B_proj = nn.Linear(self.d_inner, d_state, bias=False)
        self.C_proj = nn.Linear(self.d_inner, d_state, bias=False)
        self.dt_proj = nn.Linear(self.d_inner, d_state, bias=True)

        # Diagonal A (negative, stable)
        self.A_log = nn.Parameter(torch.zeros(d_state))

        # Skip connection from u (Mamba "D" term)
        self.D = nn.Parameter(torch.ones(self.d_inner))

        # (4) State -> inner -> model projections
        self.out_state_proj = nn.Linear(d_state, self.d_inner, bias=False)
        self.out_proj = nn.Linear(self.d_inner, d_model, bias=config.bias)

        # Initialize FiLM-like stability: start close to identity
        nn.init.zeros_(self.A_log)
        nn.init.zeros_(self.dt_proj.weight)
        nn.init.constant_(self.dt_proj.bias, math.log(math.expm1(0.01)))  # softplus^-1
        nn.init.zeros_(self.out_state_proj.weight)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: [B, L, D] input sequence
        Returns:
            y: [B, L, D] output sequence
        """
        B, L, _ = x.shape

        # Input projection
        u, gate = self.in_proj(x).chunk(2, dim=-1)  # [B, L, d_inner] each

        # Depthwise conv (causal-ish via padding then crop)
        u_conv = self.dwconv(u.transpose(1, 2))[:, :, :L].transpose(1, 2)  # [B, L, d_inner]
        u_conv = F.silu(u_conv)

        # Input-dependent SSM params
        dt = F.softplus(self.dt_proj(u_conv))  # [B, L, d_state]
        dt = dt.clamp(min=self.config.dt_min, max=self.config.dt_max)

        B_t = self.B_proj(u_conv)  # [B, L, d_state]
        C_t = self.C_proj(u_conv)  # [B, L, d_state]

        # Diagonal state transition: a_t = exp(A * dt)
        A = -torch.exp(self.A_log).view(1, 1, -1)  # [1, 1, d_state]
        log_a = A * dt  # [B, L, d_state]
        b = B_t * dt    # [B, L, d_state]

        # Selective scan (vectorized)
        h = _selective_scan_diagonal(log_a, b)  # [B, L, d_state]

        # Output from states
        y_state = h * C_t
        y_inner = self.out_state_proj(y_state)  # [B, L, d_inner]

        # Skip + gate (Mamba-style)
        y_inner = y_inner + u_conv * self.D.view(1, 1, -1)
        y_inner = y_inner * torch.sigmoid(gate)

        return self.out_proj(y_inner)


# =============================================================================
# Multi-Scale Dilated Convolution Backbone
# =============================================================================

class MultiScaleDilatedConv(nn.Module):
    """
    Multi-scale dilated convolution for capturing temporal patterns at different scales.

    Receptive fields:
    - Scale 1 (dilation=1): Daily patterns (24 hours)
    - Scale 2 (example): Weekly patterns (7 days) -> hourly would be dilation=168
    - Scale 3 (example): Longer cycles (e.g., 28 days) -> hourly would be dilation=672
    """

    def __init__(
        self,
        channels: int,
        kernel_size: int = 3,
        dilations: Optional[List[int]] = None,
        dropout: float = 0.0,
    ):
        super().__init__()
        if dilations is None:
            dilations = [1, 4, 16]
        self.channels = channels
        self.kernel_size = kernel_size
        self.dilations = [int(d) for d in dilations if int(d) >= 1]
        self.dropout = nn.Dropout(dropout) if dropout > 0 else nn.Identity()

        padding_base = (kernel_size - 1) // 2

        # Depthwise-separable conv branches
        self.branches = nn.ModuleList()
        for d in self.dilations:
            self.branches.append(
                nn.Sequential(
                    nn.Conv1d(
                        channels,
                        channels,
                        kernel_size,
                        dilation=d,
                        padding=padding_base * d,
                        groups=channels,
                        bias=True,
                    ),
                    nn.GELU(),
                    nn.Conv1d(channels, channels, kernel_size=1, bias=True),
                )
            )

        # Fusion (token-wise MLP)
        self.fusion = nn.Sequential(
            nn.Linear(channels * len(self.dilations), channels * 2),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(channels * 2, channels),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: [B, L, C] input
        Returns:
            y: [B, L, C] output
        """
        x_t = x.transpose(1, 2)  # [B, C, L]
        outs = []
        for branch in self.branches:
            outs.append(branch(x_t).transpose(1, 2))  # [B, L, C]
        y = torch.cat(outs, dim=-1)  # [B, L, C * n_scales]
        y = self.fusion(y)
        return self.dropout(y)


# =============================================================================
# Hybrid Backbone: Mamba + Multi-Scale Dilated Conv
# =============================================================================

class HybridLongSequenceBackbone(nn.Module):
    """
    Hybrid backbone combining Mamba/SSM and multi-scale dilated convolutions.

    Designed for efficient long-sequence modeling with multi-scale temporal patterns.
    """

    def __init__(
        self,
        d_model: int = 256,
        n_layers: int = 4,
        d_state: int = 64,
        use_mamba: bool = True,
        use_dilated_conv: bool = True,
        dilations: Optional[List[int]] = None,
        cond_dim: Optional[int] = None,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.d_model = d_model
        self.n_layers = n_layers
        self.d_state = d_state
        self.use_dilated_conv = use_dilated_conv
        self.use_mamba = use_mamba
        self.cond_dim = cond_dim

        if dilations is None:
            dilations = [1, 4, 16]

        self.blocks = nn.ModuleList()
        for _ in range(n_layers):
            self.blocks.append(
                _HybridBlock(
                    d_model=d_model,
                    d_state=d_state,
                    use_mamba=use_mamba,
                    use_dilated_conv=use_dilated_conv,
                    dilations=dilations,
                    cond_dim=cond_dim,
                    dropout=dropout,
                )
            )

    def forward(
        self,
        x: torch.Tensor,
        t_emb: Optional[torch.Tensor] = None,     # [B, D]
        cond: Optional[torch.Tensor] = None,      # [B, C]
    ) -> torch.Tensor:
        """
        Args:
            x: [B, L, D] input sequence
        Returns:
            y: [B, L, D] output sequence
        """
        for block in self.blocks:
            x = block(x, t_emb=t_emb, cond=cond)
        return x


def _valid_num_groups(channels: int, requested: int) -> int:
    g = min(requested, channels)
    while g > 1 and (channels % g) != 0:
        g -= 1
    return max(g, 1)


class _HybridBlock(nn.Module):
    def __init__(
        self,
        d_model: int,
        d_state: int,
        use_mamba: bool,
        use_dilated_conv: bool,
        dilations: List[int],
        cond_dim: Optional[int],
        dropout: float,
    ):
        super().__init__()
        self.use_mamba = use_mamba
        self.use_dilated_conv = use_dilated_conv
        self.cond_dim = cond_dim

        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.norm3 = nn.LayerNorm(d_model)

        self.mamba = (
            Mamba(MambaConfig(d_model=d_model, d_state=d_state))
            if use_mamba
            else nn.Identity()
        )
        self.conv = (
            MultiScaleDilatedConv(
                channels=d_model,
                kernel_size=3,
                dilations=dilations,
                dropout=dropout,
            )
            if use_dilated_conv
            else nn.Identity()
        )

        self.ffn = nn.Sequential(
            nn.Linear(d_model, d_model * 4),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model * 4, d_model),
        )

        self.dropout = nn.Dropout(dropout)

        self.film = FiLMModulation(d_model, cond_dim) if cond_dim is not None else None
        self.ada_gn = AdaptiveGroupNorm(d_model, cond_dim) if cond_dim is not None else None

    def _cond(self, h: torch.Tensor, cond: Optional[torch.Tensor]) -> torch.Tensor:
        if cond is None or self.film is None or self.ada_gn is None:
            return h
        h = self.film(h, cond)
        h = self.ada_gn(h, cond)
        return h

    def forward(
        self,
        x: torch.Tensor,                     # [B, L, D]
        t_emb: Optional[torch.Tensor] = None,  # [B, D]
        cond: Optional[torch.Tensor] = None,   # [B, C]
    ) -> torch.Tensor:
        # Mamba/SSM
        h = self.norm1(x)
        if t_emb is not None:
            h = h + t_emb.unsqueeze(1)
        h = self._cond(h, cond)
        h = self.mamba(h)
        x = x + self.dropout(h)

        # Multi-scale dilated conv
        if self.use_dilated_conv:
            h = self.norm2(x)
            if t_emb is not None:
                h = h + 0.5 * t_emb.unsqueeze(1)
            h = self._cond(h, cond)
            h = self.conv(h)
            x = x + self.dropout(h)

        # FFN
        h = self.norm3(x)
        if t_emb is not None:
            h = h + 0.5 * t_emb.unsqueeze(1)
        h = self._cond(h, cond)
        h = self.ffn(h)
        x = x + self.dropout(h)
        return x


# =============================================================================
# FiLM Modulation for Condition Injection
# =============================================================================

class FiLMModulation(nn.Module):
    """
    Feature-wise Linear Modulation (FiLM) for adaptive condition injection.

    Dynamically modulates intermediate features based on spatial context.
    """

    def __init__(self, d_model: int, cond_dim: int):
        super().__init__()

        self.gamma_proj = nn.Linear(cond_dim, d_model)
        self.beta_proj = nn.Linear(cond_dim, d_model)

        # Start near identity modulation
        nn.init.zeros_(self.gamma_proj.weight)
        nn.init.zeros_(self.gamma_proj.bias)
        nn.init.zeros_(self.beta_proj.weight)
        nn.init.zeros_(self.beta_proj.bias)

    def forward(self, x: torch.Tensor, cond: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: [B, L, D] features
            cond: [B, C] condition
        Returns:
            y: [B, L, D] modulated features
        """
        gamma = self.gamma_proj(cond).unsqueeze(1)  # [B, 1, D]
        beta = self.beta_proj(cond).unsqueeze(1)    # [B, 1, D]
        return x * (1.0 + gamma) + beta


# =============================================================================
# Adaptive Group Normalization
# =============================================================================

class AdaptiveGroupNorm(nn.Module):
    """
    Adaptive Group Normalization (AdaGN) for condition-aware normalization.
    """

    def __init__(self, d_model: int, cond_dim: int, num_groups: int = 32):
        super().__init__()
        self.num_groups = _valid_num_groups(d_model, num_groups)
        self.group_norm = nn.GroupNorm(self.num_groups, d_model, affine=False)

        self.weight_proj = nn.Linear(cond_dim, d_model)
        self.bias_proj = nn.Linear(cond_dim, d_model)
        nn.init.zeros_(self.weight_proj.weight)
        nn.init.zeros_(self.weight_proj.bias)
        nn.init.zeros_(self.bias_proj.weight)
        nn.init.zeros_(self.bias_proj.bias)

    def forward(self, x: torch.Tensor, cond: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: [B, L, D] features
            cond: [B, C] condition
        Returns:
            y: [B, L, D] normalized features
        """
        # Group norm
        x_norm = self.group_norm(x.transpose(1, 2)).transpose(1, 2)  # [B, L, D]

        # Adaptive scaling
        weight = self.weight_proj(cond).unsqueeze(1)  # [B, 1, D]
        bias = self.bias_proj(cond).unsqueeze(1)  # [B, 1, D]

        return x_norm * (1.0 + weight) + bias


class FourierTimeEmbedding(nn.Module):
    """Gaussian Fourier features for diffusion/FM time t in [0,1]."""

    def __init__(self, d_model: int, n_freqs: int = 64):
        super().__init__()
        self.n_freqs = n_freqs
        self.W = nn.Parameter(torch.randn(n_freqs) * 10.0)
        self.proj = nn.Sequential(
            nn.Linear(2 * n_freqs, d_model),
            nn.GELU(),
            nn.Linear(d_model, d_model),
        )

    def forward(self, t: torch.Tensor) -> torch.Tensor:
        # t: [B, 1]
        t = t.clamp(0.0, 1.0)
        w = self.W.view(1, 1, -1)  # [1, 1, F]
        angles = 2 * math.pi * t.unsqueeze(-1) * w  # [B, 1, F]
        emb = torch.cat([torch.sin(angles), torch.cos(angles)], dim=-1).squeeze(1)
        return self.proj(emb)  # [B, D]


def sinusoidal_positional_embedding(
    length: int,
    dim: int,
    device: torch.device,
    dtype: torch.dtype,
) -> torch.Tensor:
    """Standard sinusoidal positional embeddings [L, D]."""
    position = torch.arange(length, device=device, dtype=dtype).unsqueeze(1)  # [L, 1]
    div_term = torch.exp(
        torch.arange(0, dim, 2, device=device, dtype=dtype) * (-math.log(10000.0) / dim)
    )  # [D/2]
    pe = torch.zeros(length, dim, device=device, dtype=dtype)
    pe[:, 0::2] = torch.sin(position * div_term)
    pe[:, 1::2] = torch.cos(position * div_term)
    return pe


# =============================================================================
# Level 1: Daily Pattern Flow Matching
# =============================================================================

class DailyPatternFM(nn.Module):
    """
    Level 1: Daily Pattern Flow Matching.

    Learns to generate day-type templates for hourly traffic:
    - weekday template (24 hours)
    - weekend template (24 hours)

    Output is a concatenation of two 24-hour patterns: [weekday | weekend] -> 48 dims.
    """

    def __init__(self, spatial_dim: int = 192, hidden_dim: int = 256, steps_per_day: int = 24):
        super().__init__()
        self.spatial_dim = spatial_dim
        self.hidden_dim = hidden_dim
        self.steps_per_day = steps_per_day
        self.daytype_len = 2 * steps_per_day  # weekday + weekend

        self.time_embed = FourierTimeEmbedding(hidden_dim)

        self.in_proj = nn.Linear(1, hidden_dim)
        self.backbone = HybridLongSequenceBackbone(
            d_model=hidden_dim,
            n_layers=3,
            d_state=64,
            use_mamba=True,
            use_dilated_conv=True,
            dilations=[1, 2, 4, 8, 16],
            cond_dim=spatial_dim,
            dropout=0.1,
        )
        self.out_proj = nn.Linear(hidden_dim, 1)

    def forward(
        self,
        x: torch.Tensor,
        t: torch.Tensor,
        spatial_cond: torch.Tensor,
    ) -> torch.Tensor:
        """
        Args:
            x: [B, 48] day-type templates = [weekday(24), weekend(24)]
            t: [B, 1] time step
            spatial_cond: [B, spatial_dim] spatial context
        Returns:
            v: [B, 48] velocity field
        """
        B, L = x.shape
        assert L == self.daytype_len, f"DailyPatternFM expects L={self.daytype_len}, got {L}"

        t_emb = self.time_embed(t)  # [B, hidden_dim]
        pos = sinusoidal_positional_embedding(L, self.hidden_dim, x.device, x.dtype)  # [L, D]

        h = self.in_proj(x.unsqueeze(-1))  # [B, L, D]
        h = h + pos.unsqueeze(0)
        h = self.backbone(h, t_emb=t_emb, cond=spatial_cond)
        v = self.out_proj(h).squeeze(-1)  # [B, L]
        return v


# =============================================================================
# Level 2: Weekly Pattern Flow Matching
# =============================================================================

class WeeklyPatternFM(nn.Module):
    """
    Level 2: Weekly Pattern Flow Matching.

    Learns to generate a weekly periodic pattern at hourly resolution:
    weekly_pattern: 7 days × 24 hours = 168 time steps.

    This level is conditioned on day-type templates from Level 1.
    """

    def __init__(self, spatial_dim: int = 192, hidden_dim: int = 256, steps_per_day: int = 24):
        super().__init__()
        self.spatial_dim = spatial_dim
        self.hidden_dim = hidden_dim
        self.steps_per_day = steps_per_day
        self.week_len = 7 * steps_per_day
        self.daytype_len = 2 * steps_per_day

        self.time_embed = FourierTimeEmbedding(hidden_dim)

        self.in_proj = nn.Linear(1, hidden_dim)
        self.daily_token_proj = nn.Linear(1, hidden_dim)

        self.daily_to_weekly_attn = nn.MultiheadAttention(
            embed_dim=hidden_dim,
            num_heads=8,
            dropout=0.1,
            batch_first=True,
        )

        self.backbone = HybridLongSequenceBackbone(
            d_model=hidden_dim,
            n_layers=3,
            d_state=64,
            use_mamba=True,
            use_dilated_conv=True,
            dilations=[1, 2, 4],
            cond_dim=spatial_dim,
            dropout=0.1,
        )
        self.out_proj = nn.Linear(hidden_dim, 1)

    def forward(
        self,
        x: torch.Tensor,
        t: torch.Tensor,
        daily_pattern: torch.Tensor,
        spatial_cond: torch.Tensor,
    ) -> torch.Tensor:
        """
        Args:
            x: [B, 168] weekly pattern
            t: [B, 1] time step
            daily_pattern: [B, 48] day-type templates (from Level 1)
            spatial_cond: [B, spatial_dim] spatial context
        Returns:
            v: [B, 168] velocity field
        """
        B, Lw = x.shape
        assert Lw == self.week_len, f"WeeklyPatternFM expects L={self.week_len}, got {Lw}"
        Bd, Ld = daily_pattern.shape
        assert Bd == B and Ld == self.daytype_len, (
            f"WeeklyPatternFM expects daily_pattern [B,{self.daytype_len}], got {daily_pattern.shape}"
        )

        t_emb = self.time_embed(t)  # [B, D]

        pos_w = sinusoidal_positional_embedding(Lw, self.hidden_dim, x.device, x.dtype)
        pos_d = sinusoidal_positional_embedding(Ld, self.hidden_dim, x.device, x.dtype)

        week_tokens = self.in_proj(x.unsqueeze(-1)) + pos_w.unsqueeze(0)  # [B, 168, D]
        day_tokens = self.daily_token_proj(daily_pattern.unsqueeze(-1)) + pos_d.unsqueeze(0)  # [B, 48, D]

        # Explicitly condition on S^d via cross-attention (decouples day/week)
        attn_out, _ = self.daily_to_weekly_attn(week_tokens, day_tokens, day_tokens)
        week_tokens = week_tokens + attn_out

        h = self.backbone(week_tokens, t_emb=t_emb, cond=spatial_cond)
        v = self.out_proj(h).squeeze(-1)  # [B, 168]
        return v


# =============================================================================
# Level 3: Long-term Residual Flow Matching
# =============================================================================

class LongTermResidualFM(nn.Module):
    """
    Level 3: Long-term Residual Flow Matching.

    Learns to generate fine residuals for the full sequence (672 time steps).
    Uses Mamba + multi-scale dilated convolutions for efficient long-sequence modeling.

    Explicitly conditioned on peak hour location to force peak generation.
    """

    def __init__(
        self,
        spatial_dim: int = 192,
        hidden_dim: int = 256,
        n_layers: int = 6,
        steps_per_day: int = 24,
    ):
        super().__init__()
        self.spatial_dim = spatial_dim
        self.hidden_dim = hidden_dim
        self.steps_per_day = steps_per_day
        self.week_len = 7 * steps_per_day
        self.daytype_len = 2 * steps_per_day

        self.time_embed = FourierTimeEmbedding(hidden_dim)
        
        # Explicit Peak Position Encoding
        # Maps 0-23 hours to a hidden vector to serve as a strong condition
        self.peak_embed = nn.Embedding(24, hidden_dim)

        # Token-wise projection of multi-channel inputs
        self.in_proj = nn.Linear(4, hidden_dim)

        # Main backbone (Mamba + multi-scale dilated conv) for long sequences
        self.backbone = HybridLongSequenceBackbone(
            d_model=hidden_dim,
            n_layers=n_layers,
            d_state=128,
            use_mamba=True,
            use_dilated_conv=True,
            # (local, daily, weekly) receptive fields at hourly resolution
            dilations=[1, 2, 4, 8, 16, 24, 48, 168],
            cond_dim=spatial_dim,
            dropout=0.1,
        )
        self.out_proj = nn.Linear(hidden_dim, 1)

    def _repeat_to_length(self, pattern: torch.Tensor, target_len: int) -> torch.Tensor:
        # pattern: [B, P]
        B, P = pattern.shape
        reps = (target_len + P - 1) // P
        tiled = pattern.repeat(1, reps)
        return tiled[:, :target_len]

    def _repeat_daytype_to_length(self, daytype: torch.Tensor, target_len: int) -> torch.Tensor:
        """
        Expand day-type templates (weekday/weekend) to a full 28-day hourly sequence.

        Assumption (consistent with plot_traffic_decomposition*.py): sequence starts on Monday.
        """
        B, L = daytype.shape
        assert L == self.daytype_len, f"Expected daytype_len={self.daytype_len}, got {L}"
        steps = self.steps_per_day
        weekday = daytype[:, :steps]
        weekend = daytype[:, steps:]

        n_days = target_len // steps
        parts = []
        for d in range(n_days):
            dow = d % 7
            parts.append(weekday if dow < 5 else weekend)
        seq = torch.cat(parts, dim=1)  # [B, n_days*steps]
        if seq.shape[1] < target_len:
            pad = torch.zeros(B, target_len - seq.shape[1], device=seq.device, dtype=seq.dtype)
            seq = torch.cat([seq, pad], dim=1)
        return seq[:, :target_len]

    def forward(
        self,
        x: torch.Tensor,
        t: torch.Tensor,
        coarse_signal: torch.Tensor,
        daily_pattern: torch.Tensor,
        weekly_trend: torch.Tensor,
        spatial_cond: torch.Tensor,
        peak_hour: torch.Tensor,  
    ) -> torch.Tensor:
        """
        Args:
            x: [B, 672] residual sequence
            t: [B, 1] time step
            coarse_signal: [B, 672] periodic component (tiled weekly pattern)
            daily_pattern: [B, 48] day-type templates
            weekly_trend: [B, 168] weekly pattern
            spatial_cond: [B, spatial_dim] spatial context
            peak_hour: [B] Integer tensor (0-23) indicating explicit peak location
        Returns:
            v: [B, 672] velocity field
        """
        B, L = x.shape
        assert coarse_signal.shape == (B, L)
        assert daily_pattern.shape == (B, self.daytype_len)
        assert weekly_trend.shape == (B, self.week_len)

        # Fuse Time Embedding with Peak Embedding
        t_emb = self.time_embed(t)  # [B, D]
        peak_cond = self.peak_embed(peak_hour)  # [B, D]
        
        # Combine: Global time context + "Peak Attention" bias
        global_cond = t_emb + peak_cond

        pos = sinusoidal_positional_embedding(L, self.hidden_dim, x.device, x.dtype)

        daily_rep = self._repeat_daytype_to_length(daily_pattern, L)  # [B, L]
        # weekly_trend is weekly pattern here: tile 168 -> 672 (4 weeks)
        weekly_rep = self._repeat_to_length(weekly_trend, L)  # [B, L]
        weekly_delta = coarse_signal - daily_rep  # [B, L]

        # Token features: [residual, periodic, repeated_daytype, weekly_delta]
        feats = torch.stack([x, coarse_signal, daily_rep, weekly_delta], dim=-1)  # [B, L, 4]
        h = self.in_proj(feats) + pos.unsqueeze(0)
        
        # Pass combined global condition
        h = self.backbone(h, t_emb=global_cond, cond=spatial_cond)
        
        v = self.out_proj(h).squeeze(-1)  # [B, L]
        return v


# =============================================================================
# Complete Hierarchical Flow Matching Model
# =============================================================================

class HierarchicalFlowMatchingV4(nn.Module):
    """
    Complete Hierarchical Flow Matching model with three-level cascaded architecture.

    Level 1: Daily Pattern FM
    Level 2: Weekly Pattern FM (with daily conditioning)
    Level 3: Long-term Residual FM (with daily + weekly conditioning + explicit peak)
    """

    def __init__(
        self,
        spatial_dim: int = 192,
        hidden_dim: int = 256,
        n_layers_level3: int = 6,
        steps_per_day: int = 24,
    ):
        super().__init__()
        self.spatial_dim = spatial_dim
        self.hidden_dim = hidden_dim
        self.steps_per_day = steps_per_day
        self.week_len = 7 * steps_per_day
        self.daytype_len = 2 * steps_per_day
        # This repo's 672-length traffic is hourly: 28 days = 4 weeks.
        self.seq_len = 672
        self.n_weeks = self.seq_len // self.week_len

        # Three-level FM
        self.level1_fm = DailyPatternFM(spatial_dim, hidden_dim, steps_per_day=steps_per_day)
        self.level2_fm = WeeklyPatternFM(spatial_dim, hidden_dim, steps_per_day=steps_per_day)
        self.level3_fm = LongTermResidualFM(
            spatial_dim, hidden_dim, n_layers_level3, steps_per_day=steps_per_day
        )

    def forward(
        self,
        x: torch.Tensor,
        t: torch.Tensor,
        spatial_cond: torch.Tensor,
        level: int = 1,
        daily_pattern: Optional[torch.Tensor] = None,
        weekly_trend: Optional[torch.Tensor] = None,
        coarse_signal: Optional[torch.Tensor] = None,
        peak_hour: Optional[torch.Tensor] = None, 
    ) -> torch.Tensor:
        """
        Forward pass for a specific level.
        """
        if level == 1:
            return self.level1_fm(x, t, spatial_cond)

        elif level == 2:
            assert daily_pattern is not None, "daily_pattern required for level 2"
            return self.level2_fm(x, t, daily_pattern, spatial_cond)

        elif level == 3:
            assert daily_pattern is not None, "daily_pattern required for level 3"
            assert weekly_trend is not None, "weekly_trend required for level 3"
            assert coarse_signal is not None, "coarse_signal required for level 3"
            assert peak_hour is not None, "peak_hour required for level 3 (Explicit Peak Conditioning)"
            return self.level3_fm(x, t, coarse_signal, daily_pattern, weekly_trend, spatial_cond, peak_hour)

        else:
            raise ValueError(f"Invalid level: {level}")

    # =========================================================================
    # Generation Methods (ODE Solve)
    # =========================================================================

    def _unpack_level_conditions(
        self,
        spatial_cond: torch.Tensor | Dict[str, torch.Tensor],
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        if isinstance(spatial_cond, dict):
            return (
                spatial_cond["level1_cond"],
                spatial_cond["level2_cond"],
                spatial_cond["level3_cond"],
            )
        return spatial_cond, spatial_cond, spatial_cond

    def generate_daily_pattern(
        self,
        spatial_cond: torch.Tensor | Dict[str, torch.Tensor],
        n_steps: int = 50,
    ) -> torch.Tensor:
        """
        Generate day-type templates (Level 1).
        """
        spatial_cond_level1, _, _ = self._unpack_level_conditions(spatial_cond)
        B = spatial_cond_level1.shape[0]
        device = spatial_cond_level1.device

        x = torch.randn(B, self.daytype_len, device=device)
        dt = 1.0 / n_steps

        for step in range(n_steps):
            t = torch.full((B, 1), step / n_steps, device=device)
            v = self.level1_fm(x, t, spatial_cond_level1)
            v = torch.clamp(v, -10.0, 10.0)
            x = x + dt * v
            x = torch.clamp(x, -10.0, 10.0)

        return x

    def generate_weekly_trend(
        self,
        daily_pattern: torch.Tensor,
        spatial_cond: torch.Tensor | Dict[str, torch.Tensor],
        n_steps: int = 50,
    ) -> torch.Tensor:
        """
        Generate weekly pattern (Level 2).
        """
        _, spatial_cond_level2, _ = self._unpack_level_conditions(spatial_cond)
        B = spatial_cond_level2.shape[0]
        device = spatial_cond_level2.device

        x = torch.randn(B, self.week_len, device=device)
        dt = 1.0 / n_steps

        for step in range(n_steps):
            t = torch.full((B, 1), step / n_steps, device=device)
            v = self.level2_fm(x, t, daily_pattern, spatial_cond_level2)
            v = torch.clamp(v, -10.0, 10.0)
            x = x + dt * v
            x = torch.clamp(x, -10.0, 10.0)

        return x

    def generate_residual(
        self,
        coarse_signal: torch.Tensor,
        daily_pattern: torch.Tensor,
        weekly_trend: torch.Tensor,
        spatial_cond: torch.Tensor | Dict[str, torch.Tensor],
        peak_hour: torch.Tensor,  
        n_steps: int = 50,
    ) -> torch.Tensor:
        """
        Generate fine residual (Level 3).
        Requires peak_hour for explicit conditioning.
        """
        _, _, spatial_cond_level3 = self._unpack_level_conditions(spatial_cond)
        B = spatial_cond_level3.shape[0]
        device = spatial_cond_level3.device

        x = 0.1 * torch.randn_like(coarse_signal, device=device)
        dt = 1.0 / n_steps

        for step in range(n_steps):
            t = torch.full((B, 1), step / n_steps, device=device)
            # Pass peak_hour
            v = self.level3_fm(
                x, t, coarse_signal, daily_pattern, weekly_trend, spatial_cond_level3, peak_hour
            )
            v = torch.clamp(v, -5.0, 5.0)
            x = x + dt * v
            x = torch.clamp(x, -5.0, 5.0)

        return x

    def generate_hierarchical(
        self,
        spatial_cond: torch.Tensor | Dict[str, torch.Tensor],
        peak_hour: torch.Tensor, # Required input
        n_steps_per_level: int = 50,
    ) -> Tuple[torch.Tensor, Dict]:
        """
        Full hierarchical generation.
        """
        spatial_cond_level1, spatial_cond_level2, spatial_cond_level3 = self._unpack_level_conditions(
            spatial_cond
        )
        B = spatial_cond_level3.shape[0]
        device = spatial_cond_level3.device

        # Level 1: Generate day-type templates
        daily_pattern = self.generate_daily_pattern(spatial_cond_level1, n_steps_per_level)
        daily_pattern = torch.clamp(daily_pattern, -10.0, 10.0)

        # Level 2: Generate weekly pattern (168 hours)
        weekly_pattern = self.generate_weekly_trend(
            daily_pattern, spatial_cond_level2, n_steps_per_level
        )
        weekly_pattern = torch.clamp(weekly_pattern, -10.0, 10.0)

        # Construct periodic component for 4 weeks (672 hours)
        coarse_signal = weekly_pattern.repeat(1, self.n_weeks)  # [B, 672]
        coarse_signal = torch.clamp(coarse_signal, -10.0, 10.0)

        # Level 3: Generate fine residual
        # Pass peak_hour to residual generator
        residual = self.generate_residual(
            coarse_signal,
            daily_pattern,
            weekly_pattern,
            spatial_cond_level3,
            peak_hour=peak_hour, 
            n_steps=n_steps_per_level,
        )
        residual = torch.clamp(residual, -5.0, 5.0)

        # Final output
        generated = coarse_signal + residual
        
        # =========================================================================
        # [MODIFIED] Physical Constraint: Enforce non-negative traffic
        # Previously was: generated = torch.clamp(generated, -10.0, 10.0)
        # =========================================================================
        generated = torch.clamp(generated, min=0.0, max=10.0) 

        intermediates = {
            'daily_pattern': daily_pattern,
            'weekly_pattern': weekly_pattern,
            'coarse_signal': coarse_signal,
            'residual': residual,
        }

        return generated, intermediates