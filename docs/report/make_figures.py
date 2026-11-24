#!/usr/bin/env python3
"""Report figures for the Phase-I report, read from the saved analysis files (no number is typed in).

  figs/wesad_balacc.pdf     WESAD stress vs rest, balanced accuracy with 95% interval per model
                            (wesad_evaluation.txt, section 3, PRIMARY)
  figs/rmssd_timing_fix.pdf dual03 finger RMSSD before (5-15 Hz peak) and after (tp3) the timing
                            fix, chest tp3 as reference; causal filter as on the phone
                            (fiducial_..._v2.txt row 'bp'; tp3_own_recordings.txt row 'tp3')

Usage: ./make_figures.py [--analysis DIR] [--wesad FILE] [--out DIR]
"""
import argparse
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]                       # docs/report -> repo root
DUAL03 = "fiducial_20260929_163314_dual03_both3wire_c3chest_wroomfinger_v2.txt"

# reference palette (dataviz skill, light mode): one series, so one hue
BLUE, BLUE_LIGHT = "#2a78d6", "#86b6ef"
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df"


def style():
    # STIX ships with matplotlib as TrueType: a Times face like the report's mathptmx, embeds cleanly
    plt.rcParams.update({
        "font.family": "serif", "font.serif": ["STIXGeneral"], "mathtext.fontset": "stix",
        "font.size": 8, "axes.labelsize": 8, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
        "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK,
        "axes.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0,
        "axes.spines.top": False, "axes.spines.right": False,
        "pdf.fonttype": 42, "savefig.dpi": 300, "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
    })


# ---------------------------------------------------------------- parsing
NUM = r"([\d.]+)"
CI = r"\[\s*" + NUM + r"-\s*" + NUM + r"\]"


def wesad_primary(path):
    """Rows of section 3 (PRIMARY): model -> dict(balacc, lo, hi, rej_stress, rej_neg, n_stress, n_neg)."""
    text = Path(path).read_text().splitlines()
    start = next(i for i, l in enumerate(text) if l.startswith("== 3. PRIMARY"))
    row = re.compile(r"^  (\S.*?)\s{2,}" + NUM + r" " + CI + r"\s+" + NUM + r" " + CI + r"\s+" + NUM
                     + r"\s+" + NUM + r" " + CI + r".*\|\s+" + NUM + r"\s+" + NUM + r"\s+\|\s+(\d+)\s+(\d+)\s*$")
    out = {}
    for l in text[start + 2:]:
        if not l.strip():
            break
        m = row.match(l)
        if not m:
            raise SystemExit(f"unparsed WESAD row: {l!r}")
        g = m.groups()
        out[g[0].strip()] = dict(balacc=float(g[8]), lo=float(g[9]), hi=float(g[10]),
                                 rej_stress=float(g[11]), rej_neg=float(g[12]),
                                 n_stress=int(g[13]), n_neg=int(g[14]))
    return out


def fiducial_bp_causal(path):
    """Row 'bp' under '=== causal filter ===': chest and finger RMSSD (cleaned NN), n, drops."""
    lines = Path(path).read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("=== causal filter ==="))
    for l in lines[start:]:
        if l.startswith("bp "):
            mid = l.split("|")[2].split()      # '23.2ms 36.7 +13.4 174 2/3'
            return dict(chest=float(mid[0].rstrip("ms")), finger=float(mid[1]), n=int(mid[3]),
                        drop_finger=int(mid[4].split("/")[1]))
    raise SystemExit("no causal 'bp' row in " + str(path))


def tp3_dual03_causal(path):
    """dual03 block, 'causal filter' table, row 'tp3': RMSSD and coverage per site."""
    lines = Path(path).read_text().splitlines()
    i = next(i for i, l in enumerate(lines) if l.startswith("=== dual03"))
    i = next(j for j in range(i, len(lines)) if lines[j].startswith("causal filter"))
    for l in lines[i:]:
        if l.strip().startswith("tp3 "):
            m = re.search(r"\|\s+" + NUM + r"ms\s+(\d+)%\s+" + NUM + r"ms\s+(\d+)%", l)
            return dict(chest=float(m[1]), chest_cov=int(m[2]), finger=float(m[3]), finger_cov=int(m[4]))
    raise SystemExit("no dual03 causal tp3 row in " + str(path))


# ---------------------------------------------------------------- figures
LABELS = {"All four": "All four signals", "Wrist-only": "Wrist only", "EDA": "EDA alone",
          "ECG": "ECG alone", "BVP": "BVP alone", "TEMP": "Temperature alone"}


def fig_wesad(rows, out):
    order = sorted(rows, key=lambda k: rows[k]["balacc"])          # best at top
    fig, ax = plt.subplots(figsize=(3.45, 2.15))
    ax.axvline(50, color=MUTED, lw=0.8, ls=(0, (3, 2)), zorder=1)
    ax.text(50.6, len(order) - 0.45, "chance", color=INK2, fontsize=7, va="center")
    for y, k in enumerate(order):
        r = rows[k]
        ax.plot([r["lo"], r["hi"]], [y, y], color=BLUE, lw=2, solid_capstyle="round", zorder=2)
        ax.plot(r["balacc"], y, "o", ms=5.5, color=BLUE, mec="white", mew=1.2, zorder=3)
        ax.text(r["hi"] + 1.0, y, f"{r['balacc']:.1f}", va="center", fontsize=7.5, color=INK)
    names = []
    for k in order:
        r = rows[k]
        name = LABELS.get(k, k)
        if r["rej_stress"] > 0:
            name += f"$^\\ast$"
        names.append(name)
    ax.set_yticks(range(len(order)), names)
    ax.set_ylim(-0.6, len(order) - 0.2)
    ax.set_xlim(40, 105)
    ax.set_xticks(range(40, 101, 10))
    ax.set_xlabel("Balanced accuracy (%), 95% interval over subjects")
    ax.grid(axis="x", color=GRID, lw=0.5, zorder=0)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0, pad=3)
    rej = {(rows[k]["rej_stress"], rows[k]["rej_neg"]) for k in order if rows[k]["rej_stress"] > 0}
    if rej:
        s, n = sorted(rej)[0]
        note = (f"$^\\ast$ classified windows only: {s:.1f}% of stress and {n:.1f}% of baseline "
                f"windows rejected" + ("" if len(rej) == 1 else " (or more)"))
        fig.subplots_adjust(bottom=0.27)
        fig.text(0.0, 0.0, note, fontsize=6.5, color=INK2, ha="left", va="bottom")
    fig.savefig(out)
    plt.close(fig)


def fig_rmssd(before, after, out):
    fig, ax = plt.subplots(figsize=(3.2, 2.1))
    # value labels sit inside the bar tops: the chest line runs just above the tp3 bar
    bars = [("Finger,\n5–15 Hz peak", before["finger"], BLUE_LIGHT, INK,
             f"{before['drop_finger']} intervals dropped"),
            ("Finger,\ntp3 (template)", after["finger"], BLUE, "white",
             f"coverage {after['finger_cov']}%")]
    x = [0, 1]
    for xi, (lab, v, c, tc, sub) in zip(x, bars):
        ax.bar(xi, v, width=0.55, color=c, zorder=2)
        ax.text(xi, v - 1.0, f"{v:.1f} ms", ha="center", va="top", fontsize=7.5, color=tc, zorder=4)
        ax.text(xi, -6.0, sub, ha="center", va="top", fontsize=6.5, color=INK2)
    ch = after["chest"]
    ax.plot([-0.45, 1.45], [ch, ch], color=INK2, lw=1, ls=(0, (4, 2)), zorder=3)
    ax.text(1.5, ch, f"Chest, tp3\n{ch:.1f} ms\ncoverage {after['chest_cov']}%",
            ha="left", va="center", fontsize=6.5, color=INK2)
    ax.set_xticks(x, [b[0] for b in bars])
    ax.tick_params(axis="x", length=0, pad=3)
    ax.set_xlim(-0.5, 2.0)
    ax.spines["bottom"].set_bounds(-0.5, 1.5)
    ymax = 10 * (int(max(before["finger"], ch) / 10) + 1)
    ax.set_ylim(0, ymax)
    ax.set_yticks(range(0, ymax + 1, 10))
    ax.set_ylabel("RMSSD, cleaned NN (ms)")
    ax.grid(axis="y", color=GRID, lw=0.5, zorder=0)
    ax.set_axisbelow(True)
    fig.savefig(out)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--analysis", default=REPO / "analysis", type=Path)
    ap.add_argument("--wesad", default=None, type=Path, help="default: <analysis>/wesad_evaluation.txt")
    ap.add_argument("--out", default=HERE / "figs", type=Path)
    a = ap.parse_args()
    style()

    a.wesad = a.wesad or a.analysis / "wesad_evaluation.txt"
    rows = wesad_primary(a.wesad)
    fig_wesad(rows, a.out / "wesad_balacc.pdf")
    before = fiducial_bp_causal(a.analysis / DUAL03)
    after = tp3_dual03_causal(a.analysis / "tp3_own_recordings.txt")
    fig_rmssd(before, after, a.out / "rmssd_timing_fix.pdf")

    print(f"WESAD ({a.wesad}):")
    for k, r in rows.items():
        print(f"  {k:12s} {r['balacc']:5.1f} [{r['lo']:5.1f}, {r['hi']:5.1f}]  rejected stress {r['rej_stress']}%"
              f" neg {r['rej_neg']}%  n {r['n_stress']}/{r['n_neg']}")
    print(f"RMSSD dual03 causal: finger bp {before['finger']} ms (n {before['n']}, {before['drop_finger']} dropped)"
          f" -> tp3 {after['finger']} ms (cov {after['finger_cov']}%); chest tp3 {after['chest']} ms"
          f" (cov {after['chest_cov']}%); chest bp {before['chest']} ms")
    print("wrote", a.out / "wesad_balacc.pdf", a.out / "rmssd_timing_fix.pdf")


if __name__ == "__main__":
    main()
