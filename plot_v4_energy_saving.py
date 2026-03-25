import argparse
import re
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1.inset_locator import inset_axes


def load_samples(npz_path: Path):
    data = np.load(npz_path, allow_pickle=True)
    pattern = re.compile(r"sample_(\d+)_(real|gen)$")
    samples = {}
    for key in data.files:
        m = pattern.match(key)
        if not m:
            continue
        sid = int(m.group(1))
        kind = m.group(2)
        samples.setdefault(sid, {})[kind] = data[key].astype(float)
    samples = {sid: v for sid, v in samples.items() if "real" in v and "gen" in v}
    if not samples:
        raise ValueError("No valid sample_*_(real|gen) arrays found in the npz file")
    return samples


def rolling_std(x, window):
    w = int(window)
    if w <= 1:
        return np.zeros_like(x)
    pad_left = w // 2
    pad_right = w - 1 - pad_left
    xpad = np.pad(x, (pad_left, pad_right), mode="reflect")
    kernel = np.ones(w, dtype=float) / w
    mean = np.convolve(xpad, kernel, mode="valid")
    mean_sq = np.convolve(xpad ** 2, kernel, mode="valid")
    var = np.maximum(mean_sq - mean ** 2, 0.0)
    return np.sqrt(var)


def prune_short_true(mask, min_len):
    if min_len <= 1:
        return mask
    out = mask.copy()
    n = len(out)
    i = 0
    while i < n:
        if out[i]:
            j = i + 1
            while j < n and out[j]:
                j += 1
            if j - i < min_len:
                out[i:j] = False
            i = j
        else:
            i += 1
    return out


def segments(mask):
    n = len(mask)
    i = 0
    while i < n:
        if mask[i]:
            j = i + 1
            while j < n and mask[j]:
                j += 1
            yield i, j
            i = j
        else:
            i += 1


def build_decision(real, gen, window, quantile, min_len):
    vol = rolling_std(real, window)
    thr = np.quantile(vol, quantile)
    mask = vol >= thr
    mask = prune_short_true(mask, min_len)
    decision = np.where(mask, gen, real)
    return decision, mask, vol, thr


def compute_metrics(real, decision):
    saving = 1.0 - (decision.sum() / (real.sum() + 1e-8))
    qoe_loss = np.maximum(real - decision, 0.0).sum() / (real.sum() + 1e-8)
    qoe_satisfaction = 1.0 - qoe_loss
    cum_saving = np.cumsum(real - decision)
    return saving, qoe_loss, qoe_satisfaction, cum_saving


def score_sample(real, decision):
    saving = 1.0 - (decision.sum() / (real.sum() + 1e-8))
    qoe_loss = np.maximum(real - decision, 0.0).sum() / (real.sum() + 1e-8)
    return saving - 0.5 * qoe_loss


def pick_top_k(samples, args, k=4):
    scored = []
    for sid, v in samples.items():
        real = v["real"]
        gen = v["gen"]
        decision, _, _, _ = build_decision(
            real, gen, args.vol_window, args.vol_quantile, args.min_vol_len
        )
        scored.append((score_sample(real, decision), sid))
    scored.sort(reverse=True)
    return [sid for _, sid in scored[:k]]


def main():
    ap = argparse.ArgumentParser(description="Gen-driven dynamic BS control visualization")
    ap.add_argument("--npz", default="v4_traffic_data_generated.npz")
    ap.add_argument("--out", default="v4_energy_saving_visualization.png")
    ap.add_argument("--sample", type=int, default=None, help="single sample id to plot")
    ap.add_argument("--mode", choices=["single", "grid"], default="grid", help="plot mode")
    ap.add_argument("--k", type=int, default=4, help="number of samples for grid mode")
    ap.add_argument("--vol_window", type=int, default=24, help="rolling window for volatility")
    ap.add_argument("--vol_quantile", type=float, default=0.7, help="quantile for high volatility")
    ap.add_argument("--min_vol_len", type=int, default=6, help="minimum length of volatile segments")
    ap.add_argument("--dpi", type=int, default=300)
    args = ap.parse_args()

    samples = load_samples(Path(args.npz))
    sids = sorted(samples.keys())
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9,
        "legend.fontsize": 8,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "axes.linewidth": 0.8,
        "grid.alpha": 0.2,
        "grid.linestyle": "--",
    })

    if args.mode == "grid":
        if args.sample is None:
            sample_ids = pick_top_k(samples, args, k=args.k)
        else:
            if args.sample not in samples:
                raise ValueError(f"sample id {args.sample} not found. available: {sids}")
            sample_ids = [args.sample]

        ncols = len(sample_ids)
        fig, axes = plt.subplots(
            2,
            ncols,
            figsize=(2.9 * ncols, 3.0),
            sharex=True,
            constrained_layout=False,
        )
        axes = np.array(axes)
        if axes.ndim == 1:
            axes = axes.reshape(2, 1)

        legend_top_handles = None
        legend_top_labels = None
        legend_bottom_handles = None
        legend_bottom_labels = None

        for col, sid in enumerate(sample_ids):
            ax_top = axes[0, col]
            ax_bottom = axes[1, col]
            real = samples[sid]["real"]
            gen = samples[sid]["gen"]
            t = np.arange(len(real))
            decision, mask, _, _ = build_decision(
                real, gen, args.vol_window, args.vol_quantile, args.min_vol_len
            )
            saving, _, qoe_satisfaction, _ = compute_metrics(real, decision)
            gen_masked = np.where(mask, gen, np.nan)
            delta = decision - real

            ax_top.plot(t, real, color="#1f77b4", linewidth=1.0, label="Observed")
            ax_top.plot(t, decision, color="#d62728", linewidth=1.0, linestyle="--",
                        label="Control target")
            ax_top.plot(t, gen_masked, color="#9467bd", linewidth=0.9, alpha=0.9,
                        label="Generated (volatile only)")
            for s, e in segments(mask):
                ax_top.axvspan(s, e, color="#d9d9d9", alpha=0.16, lw=0)
            ax_top.fill_between(t, decision, real, where=(decision < real),
                                color="#2ca02c", alpha=0.16)
            ax_top.fill_between(t, decision, real, where=(decision > real),
                                color="#d62728", alpha=0.10)
            if col == 0:
                ax_top.set_ylabel("Load")
            ax_top.grid(True)
            ax_top.tick_params(labelbottom=False)
            ax_top.text(
                0.02,
                0.84,
                f"Save {saving*100:.1f}%, QoE {qoe_satisfaction*100:.1f}%",
                transform=ax_top.transAxes,
                ha="left",
                va="top",
                fontsize=6.5,
                color="#303030",
                wrap=False,
                bbox=dict(boxstyle="round,pad=0.15", facecolor="white", alpha=0.7, edgecolor="none"),
            )

            ax_bottom.axhline(0.0, color="black", linewidth=0.8)
            for s, e in segments(mask):
                ax_bottom.axvspan(s, e, color="#d9d9d9", alpha=0.08, lw=0)
            ax_bottom.fill_between(t, 0, delta, where=(delta < 0),
                                   color="#2ca02c", alpha=0.22, label="Power reduction")
            ax_bottom.fill_between(t, 0, delta, where=(delta > 0),
                                   color="#d62728", alpha=0.18, label="Power increase")
            ax_bottom.plot(t, delta, color="#4c4c4c", linewidth=0.8, alpha=0.7,
                           label="_nolegend_")
            ax_bottom.set_xlabel("Hour")
            if col == 0:
                ax_bottom.set_ylabel("Control minus observed")
            ax_bottom.grid(True)

            if legend_top_handles is None:
                legend_top_handles, legend_top_labels = ax_top.get_legend_handles_labels()
            if legend_bottom_handles is None:
                legend_bottom_handles, legend_bottom_labels = ax_bottom.get_legend_handles_labels()

        combined_handles = []
        combined_labels = []
        if legend_top_handles:
            combined_handles.extend(legend_top_handles)
            combined_labels.extend(legend_top_labels)
        if legend_bottom_handles:
            combined_handles.extend(legend_bottom_handles)
            combined_labels.extend(legend_bottom_labels)

        if combined_handles:
            legend_ncol = max(len(combined_labels), 1)
            fig.legend(
                combined_handles,
                combined_labels,
                loc="lower center",
                ncol=legend_ncol,
                frameon=False,
                bbox_to_anchor=(0.5, 0.0),
                borderaxespad=0.0,
            )
        fig.subplots_adjust(top=0.90, bottom=0.18, wspace=0.28, hspace=0.18)
        fig.savefig(args.out, dpi=args.dpi, bbox_inches="tight")
        print(f"Saved figure to {args.out}")
        return

    if args.sample is None:
        sample_id = pick_top_k(samples, args, k=1)[0]
    else:
        if args.sample not in samples:
            raise ValueError(f"sample id {args.sample} not found. available: {sids}")
        sample_id = args.sample

    real = samples[sample_id]["real"]
    gen = samples[sample_id]["gen"]
    t = np.arange(len(real))

    decision, mask, vol, thr = build_decision(
        real, gen, args.vol_window, args.vol_quantile, args.min_vol_len
    )

    delta = decision - real
    saving, qoe_loss, qoe_satisfaction, cum_saving = compute_metrics(real, decision)

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(7.2, 6.4), constrained_layout=True)

    # Panel 1: decision uses generated only in high-volatility windows
    ax1.plot(t, real, color="#1f77b4", linewidth=1.2, label="Observed traffic")
    ax1.plot(t, decision, color="#d62728", linewidth=1.1, linestyle="--",
             label="Control target")
    gen_masked = np.where(mask, gen, np.nan)
    ax1.plot(t, gen_masked, color="#9467bd", linewidth=1.0, alpha=0.9,
             label="Generated decision (volatile only)")
    first = True
    for s, e in segments(mask):
        ax1.axvspan(s, e, color="#d9d9d9", alpha=0.18,
                    label="High-volatility window" if first else None)
        first = False
    ax1.fill_between(t, decision, real, where=(decision < real),
                     color="#2ca02c", alpha=0.18, label="Power reduction")
    ax1.fill_between(t, decision, real, where=(decision > real),
                     color="#d62728", alpha=0.12, label="Power increase")
    ax1.set_title("Time-series comparison with selective gen-driven control")
    ax1.set_xlabel("Hour")
    ax1.set_ylabel("Normalized load")
    ax1.grid(True)
    ax1.legend(loc="upper right", ncol=2, frameon=False)

    # Panel 2: volatility and decision regions
    ax2.plot(t, vol, color="#4c4c4c", linewidth=1.0, label="Rolling volatility")
    ax2.axhline(thr, color="#d62728", linewidth=0.9, linestyle="--", label="Volatility threshold")
    for s, e in segments(mask):
        ax2.axvspan(s, e, color="#d9d9d9", alpha=0.12, lw=0)
    ax2.set_title("Volatility-aware decision regions")
    ax2.set_xlabel("Hour")
    ax2.set_ylabel("Rolling std")
    ax2.grid(True)
    ax2.legend(loc="upper right", ncol=2, frameon=False)

    # Panel 3: dynamic adjustment signal and cumulative saving
    ax3.axhline(0.0, color="black", linewidth=0.8)
    for s, e in segments(mask):
        ax3.axvspan(s, e, color="#d9d9d9", alpha=0.08, lw=0)
    ax3.fill_between(t, 0, delta, where=(delta < 0), color="#2ca02c", alpha=0.22,
                     label="Power reduction")
    ax3.fill_between(t, 0, delta, where=(delta > 0), color="#d62728", alpha=0.18,
                     label="Power increase")
    ax3.plot(t, delta, color="#4c4c4c", linewidth=0.8, alpha=0.7)
    ax3.set_title("Dynamic power adjustment and cumulative saving")
    ax3.set_xlabel("Hour")
    ax3.set_ylabel("Control minus observed")
    ax3.grid(True)

    ax3b = ax3.twinx()
    ax3b.plot(t, cum_saving, color="#1f77b4", linewidth=1.0, alpha=0.8, label="Cumulative saving")
    ax3b.set_ylabel("Cumulative saving")
    ax3b.tick_params(axis="y", labelsize=8, colors="#1f77b4")

    handles1, labels1 = ax3.get_legend_handles_labels()
    handles2, labels2 = ax3b.get_legend_handles_labels()
    ax3.legend(handles1 + handles2, labels1 + labels2, loc="upper right", ncol=2, frameon=False)
    ax3.text(0.02, 0.92,
             f"Energy saving {saving*100:.1f}%\nQoE satisfaction {qoe_satisfaction*100:.1f}%",
             transform=ax3.transAxes, ha="left", va="top", fontsize=8)

    fig.savefig(args.out, dpi=args.dpi)

    print(f"Saved figure to {args.out}")
    print(f"Sample {sample_id} saving {saving*100:.2f}% qoe {qoe_satisfaction*100:.2f}%")
