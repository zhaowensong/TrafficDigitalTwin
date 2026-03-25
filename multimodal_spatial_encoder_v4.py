"""
Multi-Modal Spatial Context Encoder (V4)
=========================================

Fuses POI features and satellite imagery into a unified spatial context embedding.

Key components:
1. POI Encoder: MLP with learnable category importance weights
2. Satellite Image Encoder: ResNet-18 with multi-scale features
3. Coordinate Encoder: Fourier features with learnable frequencies
4. Fusion Strategy: Cross-attention + adaptive gating
5. Condition Injection: FiLM/AdaGN modulation
6. [NEW] Auxiliary Head: Peak Hour Classification (Explicit Peak Prediction)

Author: Optimization Team
Date: 2026-01-21
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from typing import Dict, Optional


# =============================================================================
# POI Encoder with Learnable Importance Weights
# =============================================================================

class POIEncoder(nn.Module):
    """
    POI encoder with learnable category importance weights.

    Input: POI count/density vector [B, poi_dim]
    Output: POI embedding [B, spatial_dim]
    """

    def __init__(self, poi_dim: int = 20, spatial_dim: int = 192):
        super().__init__()
        self.poi_dim = poi_dim
        self.spatial_dim = spatial_dim

        # Learnable category importance weights
        self.category_importance = nn.Parameter(torch.ones(poi_dim))

        # Category token embeddings (POI-Enhancer inspired: attention-weighted semantic fusion)
        self.category_embed = nn.Embedding(poi_dim, spatial_dim)

        # Deep encoder with residual connections
        self.encoder = nn.Sequential(
            nn.Linear(poi_dim, 256),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(256, 256),
            nn.GELU(),
            nn.LayerNorm(256),
            nn.Linear(256, spatial_dim),
            nn.LayerNorm(spatial_dim),
        )

        # Attention pooling over category tokens
        self.token_attn = nn.Sequential(
            nn.Linear(spatial_dim, 128),
            nn.GELU(),
            nn.Linear(128, 1),
        )

        # Gate between MLP vector and token-pooled vector
        self.fuse_gate = nn.Sequential(
            nn.Linear(spatial_dim * 2, 1),
            nn.Sigmoid(),
        )

    def forward(self, poi_dist: torch.Tensor, return_tokens: bool = False):
        """
        Args:
            poi_dist: [B, poi_dim] POI distribution
        Returns:
            features: [B, spatial_dim] POI embedding
        """
        # Apply learnable importance weights
        weights = F.softmax(self.category_importance, dim=0)
        weighted_poi = poi_dist * weights

        # Log transform for count data (handles skewed distributions)
        poi_log = torch.log1p(weighted_poi)

        # (1) Global vector via MLP
        features_mlp = self.encoder(poi_log)

        # (2) Category tokens + attention pooling (attention score-weighted merging)
        # token_scale: [B, poi_dim, 1]
        token_scale = poi_log.unsqueeze(-1)
        # tokens: [B, poi_dim, D]
        tokens = token_scale * self.category_embed.weight.unsqueeze(0)
        attn_logits = self.token_attn(tokens).squeeze(-1)  # [B, poi_dim]
        attn = F.softmax(attn_logits, dim=-1).unsqueeze(-1)  # [B, poi_dim, 1]
        features_tok = (tokens * attn).sum(dim=1)  # [B, D]

        # Combine (learned trade-off)
        g = self.fuse_gate(torch.cat([features_mlp, features_tok], dim=-1))  # [B, 1]
        features = g * features_mlp + (1.0 - g) * features_tok

        if return_tokens:
            return features, tokens
        return features


# =============================================================================
# Satellite Image Encoder (ResNet-18 backbone)
# =============================================================================

class ResidualBlock(nn.Module):
    """Basic residual block for ResNet."""

    def __init__(self, in_channels: int, out_channels: int, stride: int = 1):
        super().__init__()
        self.conv1 = nn.Conv2d(in_channels, out_channels, 3, stride=stride, padding=1)
        self.bn1 = nn.BatchNorm2d(out_channels)
        self.relu = nn.ReLU(inplace=True)
        self.conv2 = nn.Conv2d(out_channels, out_channels, 3, padding=1)
        self.bn2 = nn.BatchNorm2d(out_channels)

        self.stride = stride
        if stride != 1 or in_channels != out_channels:
            self.shortcut = nn.Sequential(
                nn.Conv2d(in_channels, out_channels, 1, stride=stride),
                nn.BatchNorm2d(out_channels),
            )
        else:
            self.shortcut = None

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        identity = x
        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)

        if self.shortcut is not None:
            identity = self.shortcut(x)

        out = out + identity
        out = self.relu(out)
        return out


class SatelliteImageEncoder(nn.Module):
    """
    ResNet-18-based satellite image encoder with multi-scale feature extraction.

    Input: Satellite image [B, 3, 64, 64]
    Output: Image embedding [B, spatial_dim]
    """

    def __init__(self, spatial_dim: int = 192, n_heads: int = 8, token_layers: int = 2):
        super().__init__()
        self.spatial_dim = spatial_dim

        # Initial layer
        self.conv1 = nn.Sequential(
            nn.Conv2d(3, 64, 7, stride=2, padding=3),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(3, stride=2, padding=1),
        )

        # ResNet blocks
        self.layer1 = self._make_layer(64, 64, 2, stride=1)
        self.layer2 = self._make_layer(64, 128, 2, stride=2)
        self.layer3 = self._make_layer(128, 256, 2, stride=2)
        self.layer4 = self._make_layer(256, 512, 2, stride=2)

        # Multi-scale feature aggregation
        self.pool1 = nn.AdaptiveAvgPool2d(1)
        self.pool2 = nn.AdaptiveAvgPool2d(1)
        self.pool3 = nn.AdaptiveAvgPool2d(1)
        self.pool4 = nn.AdaptiveAvgPool2d(1)

        # Learnable scale weights
        self.scale_weights = nn.Parameter(torch.tensor([1.0, 1.0, 1.0, 1.0]))

        # Final projection
        self.proj = nn.Sequential(
            nn.Linear(64 + 128 + 256 + 512, 384),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(384, spatial_dim),
            nn.LayerNorm(spatial_dim),
        )

        # Region-level tokens (RemoteCLIP-inspired: patch/region awareness)
        self.token_proj3 = nn.Linear(256, spatial_dim)
        self.token_proj4 = nn.Linear(512, spatial_dim)
        self.img_cls = nn.Parameter(torch.zeros(1, 1, spatial_dim))
        enc_layer = nn.TransformerEncoderLayer(
            d_model=spatial_dim,
            nhead=n_heads,
            dim_feedforward=spatial_dim * 4,
            dropout=0.1,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.token_mixer = nn.TransformerEncoder(enc_layer, num_layers=int(token_layers))

    def _make_layer(self, in_channels: int, out_channels: int, blocks: int, stride: int):
        layers = []
        layers.append(ResidualBlock(in_channels, out_channels, stride))
        for _ in range(1, blocks):
            layers.append(ResidualBlock(out_channels, out_channels, 1))
        return nn.Sequential(*layers)

    def forward(self, x: torch.Tensor, return_tokens: bool = False):
        """
        Args:
            x: [B, 3, 64, 64] satellite image
        Returns:
            features: [B, spatial_dim] image embedding
        """
        x = self.conv1(x)  # [B, 64, 16, 16]

        x1 = self.layer1(x)  # [B, 64, 16, 16]
        x2 = self.layer2(x1)  # [B, 128, 8, 8]
        x3 = self.layer3(x2)  # [B, 256, 4, 4]
        x4 = self.layer4(x3)  # [B, 512, 2, 2]

        # Multi-scale pooling
        f1 = self.pool1(x1).flatten(1)  # [B, 64]
        f2 = self.pool2(x2).flatten(1)  # [B, 128]
        f3 = self.pool3(x3).flatten(1)  # [B, 256]
        f4 = self.pool4(x4).flatten(1)  # [B, 512]

        # Weighted fusion
        weights = F.softmax(self.scale_weights, dim=0)
        fused = torch.cat([
            f1 * weights[0],
            f2 * weights[1],
            f3 * weights[2],
            f4 * weights[3],
        ], dim=-1)

        # Final projection
        features = self.proj(fused)

        if not return_tokens:
            return features

        # Build region tokens from intermediate feature maps (4x4 + 2x2 = 20 tokens)
        t3 = x3.flatten(2).transpose(1, 2)  # [B, 16, 256]
        t4 = x4.flatten(2).transpose(1, 2)  # [B, 4, 512]
        t3 = self.token_proj3(t3)  # [B, 16, D]
        t4 = self.token_proj4(t4)  # [B, 4, D]
        tokens = torch.cat([t3, t4], dim=1)  # [B, 20, D]

        # Mix tokens with a tiny Transformer, include a [CLS] token
        cls = self.img_cls.expand(tokens.shape[0], -1, -1)
        tokens_with_cls = torch.cat([cls, tokens], dim=1)  # [B, 21, D]
        tokens_with_cls = self.token_mixer(tokens_with_cls)

        # tokens_with_cls[:, 0] is CLS; keep both CLS and spatial tokens
        cls_out = tokens_with_cls[:, 0]  # [B, D]
        spatial_tokens = tokens_with_cls[:, 1:]  # [B, 20, D]

        # Blend CLS with pooled global feature for stability
        feat = 0.5 * features + 0.5 * cls_out
        return feat, spatial_tokens


# =============================================================================
# Coordinate Encoder with Learnable Fourier Features
# =============================================================================

class CoordinateEncoder(nn.Module):
    """
    Coordinate encoder with learnable Fourier frequencies.

    Input: Coordinates [B, 2] (latitude, longitude)
    Output: Coordinate embedding [B, spatial_dim]
    """

    def __init__(self, coord_dim: int = 2, spatial_dim: int = 192):
        super().__init__()
        self.coord_dim = coord_dim
        self.spatial_dim = spatial_dim

        # Multi-scale learnable Fourier frequencies
        n_freqs = 64
        init_freqs = 2 ** torch.linspace(0, 8, n_freqs)
        self.freqs = nn.Parameter(init_freqs)

        fourier_dim = coord_dim * n_freqs * 2

        # Deep encoder
        self.encoder = nn.Sequential(
            nn.Linear(fourier_dim + coord_dim, 512),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(512, 384),
            nn.GELU(),
            nn.LayerNorm(384),
            nn.Linear(384, spatial_dim),
            nn.LayerNorm(spatial_dim),
        )

    def forward(self, coords: torch.Tensor) -> torch.Tensor:
        """
        Args:
            coords: [B, 2] coordinates
        Returns:
            features: [B, spatial_dim] coordinate embedding
        """
        # Fourier features with learnable frequencies
        coords_scaled = coords.unsqueeze(-1) * self.freqs  # [B, 2, n_freqs]
        fourier = torch.cat([
            torch.sin(coords_scaled * np.pi),
            torch.cos(coords_scaled * np.pi),
        ], dim=-1).flatten(-2)  # [B, fourier_dim]

        # Combine with raw coordinates
        combined = torch.cat([coords, fourier], dim=-1)

        # Encode
        features = self.encoder(combined)

        return features


# =============================================================================
# Cross-Attention Fusion Module
# =============================================================================

class CrossAttentionFusion(nn.Module):
    """
    Cross-attention fusion for multi-modal conditioning.

    Fuses POI, satellite, and coordinate embeddings via multi-head attention.
    """

    def __init__(self, spatial_dim: int = 192, n_heads: int = 8):
        super().__init__()
        self.spatial_dim = spatial_dim
        self.n_heads = n_heads

        # Two rounds of cross-attention (vector mode: 3 tokens; token mode: CLS->context)
        self.cross_attn1 = nn.MultiheadAttention(
            spatial_dim, num_heads=n_heads, dropout=0.1, batch_first=True
        )
        self.cross_attn2 = nn.MultiheadAttention(
            spatial_dim, num_heads=n_heads, dropout=0.1, batch_first=True
        )

        # Layer norms
        self.norm1 = nn.LayerNorm(spatial_dim)
        self.norm2 = nn.LayerNorm(spatial_dim)
        self.norm3 = nn.LayerNorm(spatial_dim)
        self.norm4 = nn.LayerNorm(spatial_dim)

        # Feed-forward networks
        self.ffn1 = nn.Sequential(
            nn.Linear(spatial_dim, spatial_dim * 4),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(spatial_dim * 4, spatial_dim),
        )
        self.ffn2 = nn.Sequential(
            nn.Linear(spatial_dim, spatial_dim * 4),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(spatial_dim * 4, spatial_dim),
        )

        # Adaptive gating for modality importance
        self.gate = nn.Sequential(
            nn.Linear(spatial_dim * 3, 256),
            nn.GELU(),
            nn.Linear(256, 3),
            nn.Softmax(dim=-1),
        )

        # Token-mode: learnable fusion token
        self.fusion_cls = nn.Parameter(torch.zeros(1, 1, spatial_dim))
        self.token_out_gate = nn.Sequential(
            nn.Linear(spatial_dim * 2, 1),
            nn.Sigmoid(),
        )

    def forward(
        self,
        sat_feat: torch.Tensor,
        poi_feat: torch.Tensor,
        coord_feat: torch.Tensor,
        sat_tokens: Optional[torch.Tensor] = None,
        poi_tokens: Optional[torch.Tensor] = None,
        coord_token: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """
        Args:
            sat_feat: [B, spatial_dim] satellite embedding
            poi_feat: [B, spatial_dim] POI embedding
            coord_feat: [B, spatial_dim] coordinate embedding
        Returns:
            fused: [B, spatial_dim] fused embedding
        """
        # ---------------------------------------------------------------------
        # (A) Vector mode (backward-compatible): treat each modality as 1 token.
        # ---------------------------------------------------------------------
        if sat_tokens is None and poi_tokens is None and coord_token is None:
            # Stack as sequence [B, 3, D]
            modalities = torch.stack([sat_feat, poi_feat, coord_feat], dim=1)

            # First round of cross-attention
            attn_out1, _ = self.cross_attn1(modalities, modalities, modalities)
            modalities = self.norm1(modalities + attn_out1)
            ffn_out1 = self.ffn1(modalities)
            modalities = self.norm2(modalities + ffn_out1)

            # Second round
            attn_out2, _ = self.cross_attn2(modalities, modalities, modalities)
            modalities = self.norm3(modalities + attn_out2)
            ffn_out2 = self.ffn2(modalities)
            modalities = self.norm4(modalities + ffn_out2)

            # Unpack
            sat_out, poi_out, coord_out = modalities.unbind(dim=1)

            # Adaptive gating
            concat = torch.cat([sat_out, poi_out, coord_out], dim=-1)
            weights = self.gate(concat)  # [B, 3]

            # Weighted fusion
            fused = (
                weights[:, 0:1] * sat_out +
                weights[:, 1:2] * poi_out +
                weights[:, 2:3] * coord_out
            )

            return fused

        # ---------------------------------------------------------------------
        # (B) Token mode: CLS attends over (sat tokens + poi tokens + coord token).
        # RemoteCLIP-inspired region tokens + POI-Enhancer-inspired semantic tokens.
        # ---------------------------------------------------------------------
        B = sat_feat.shape[0]
        context = []
        if sat_tokens is not None:
            context.append(sat_tokens)
        else:
            context.append(sat_feat.unsqueeze(1))

        if poi_tokens is not None:
            context.append(poi_tokens)
        else:
            context.append(poi_feat.unsqueeze(1))

        if coord_token is not None:
            context.append(coord_token.unsqueeze(1))
        else:
            context.append(coord_feat.unsqueeze(1))

        context_tokens = torch.cat(context, dim=1)  # [B, L, D]
        cls = self.fusion_cls.expand(B, -1, -1)  # [B, 1, D]

        # Two rounds of CLS->context attention + FFN (Transformer-like)
        attn1, _ = self.cross_attn1(cls, context_tokens, context_tokens)
        cls = self.norm1(cls + attn1)
        cls = self.norm2(cls + self.ffn1(cls))

        attn2, _ = self.cross_attn2(cls, context_tokens, context_tokens)
        cls = self.norm3(cls + attn2)
        cls = self.norm4(cls + self.ffn2(cls))

        cls_vec = cls.squeeze(1)  # [B, D]

        # Keep the original adaptive gating as a global shortcut, then learn to mix.
        concat = torch.cat([sat_feat, poi_feat, coord_feat], dim=-1)
        weights = self.gate(concat)
        gated = (
            weights[:, 0:1] * sat_feat +
            weights[:, 1:2] * poi_feat +
            weights[:, 2:3] * coord_feat
        )
        mix = self.token_out_gate(torch.cat([cls_vec, gated], dim=-1))  # [B, 1]
        fused = mix * cls_vec + (1.0 - mix) * gated
        return fused


# =============================================================================
# Multi-Scale Condition Generator
# =============================================================================

class MultiScaleConditionGenerator(nn.Module):
    """
    Generate stage-specific multi-scale conditions.

    Produces different condition embeddings for each hierarchical level.
    """

    def __init__(self, spatial_dim: int = 192):
        super().__init__()

        # Level 1 (daily): global patterns
        self.level1_proj = nn.Sequential(
            nn.Linear(spatial_dim, 256),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(256, spatial_dim),
            nn.LayerNorm(spatial_dim),
        )

        # Level 2 (weekly): periodic structure
        self.level2_proj = nn.Sequential(
            nn.Linear(spatial_dim, 256),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(256, spatial_dim),
            nn.LayerNorm(spatial_dim),
        )

        # Level 3 (residual): fine details
        self.level3_proj = nn.Sequential(
            nn.Linear(spatial_dim, 384),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(384, spatial_dim),
            nn.LayerNorm(spatial_dim),
        )

    def forward(self, base_condition: torch.Tensor) -> Dict[str, torch.Tensor]:
        """Generate stage-specific conditions."""
        return {
            'level1_cond': self.level1_proj(base_condition),
            'level2_cond': self.level2_proj(base_condition),
            'level3_cond': self.level3_proj(base_condition),
        }


# =============================================================================
# Complete Multi-Modal Spatial Encoder
# =============================================================================

class MultiModalSpatialEncoderV4(nn.Module):
    """
    Complete multi-modal spatial encoder combining:
    - POI features
    - Satellite imagery
    - Geographic coordinates
    - Cross-attention fusion
    - Multi-scale condition generation
    - [NEW] Auxiliary Peak Hour Classification
    """

    def __init__(self, spatial_dim: int = 192, poi_dim: int = 20):
        super().__init__()
        self.spatial_dim = spatial_dim
        self.poi_dim = poi_dim

        # Individual encoders
        self.poi_encoder = POIEncoder(poi_dim, spatial_dim)
        self.satellite_encoder = SatelliteImageEncoder(spatial_dim)
        self.coord_encoder = CoordinateEncoder(2, spatial_dim)

        # Multi-modal fusion
        self.fusion = CrossAttentionFusion(spatial_dim, n_heads=8)

        # Multi-scale condition generation
        self.multiscale_generator = MultiScaleConditionGenerator(spatial_dim)
        
        # [NEW] Auxiliary Head: Peak Hour Prediction
        # Predicts which hour (0-23) has the maximum traffic
        self.peak_hour_classifier = nn.Sequential(
            nn.Linear(spatial_dim, 128),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(128, 24)  # 24 hours classification
        )

    def forward(self, batch: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        """
        Args:
            batch: dict with keys:
                - 'satellite_img': [B, 3, 64, 64]
                - 'poi_dist': [B, poi_dim]
                - 'coords': [B, 2]
        Returns:
            outputs: dict with conditions and predicted peak logits
        """
        # Encode each modality (token-aware for stronger multi-modal fusion)
        sat_feat, sat_tokens = self.satellite_encoder(batch['satellite_img'], return_tokens=True)
        poi_feat, poi_tokens = self.poi_encoder(batch['poi_dist'], return_tokens=True)
        coord_feat = self.coord_encoder(batch['coords'])

        # Fuse modalities (CLS attends to region tokens + semantic tokens)
        base_condition = self.fusion(
            sat_feat,
            poi_feat,
            coord_feat,
            sat_tokens=sat_tokens,
            poi_tokens=poi_tokens,
            coord_token=coord_feat,
        )

        # Generate multi-scale conditions
        stage_conditions = self.multiscale_generator(base_condition)
        
        # [NEW] Predict peak hour
        pred_peak_logits = self.peak_hour_classifier(base_condition)

        outputs = {
            'base_condition': base_condition,
            'pred_peak_logits': pred_peak_logits, # Auxiliary output
            **stage_conditions,
        }

        return outputs


if __name__ == "__main__":
    # Test the encoder
    B = 4
    spatial_dim = 192
    poi_dim = 20

    encoder = MultiModalSpatialEncoderV4(spatial_dim, poi_dim)

    # Create dummy batch
    batch = {
        'satellite_img': torch.randn(B, 3, 64, 64),
        'poi_dist': torch.randn(B, poi_dim),
        'coords': torch.randn(B, 2),
    }

    # Forward pass
    outputs = encoder(batch)

    print("Multi-Modal Spatial Encoder V4 Test:")
    print(f"  Base condition shape: {outputs['base_condition'].shape}")
    print(f"  Peak Logits shape: {outputs['pred_peak_logits'].shape}")
    print(f"  Level 1 condition shape: {outputs['level1_cond'].shape}")
    print(f"  Level 2 condition shape: {outputs['level2_cond'].shape}")
    print(f"  Level 3 condition shape: {outputs['level3_cond'].shape}")

    print("\nEncoder test passed!")