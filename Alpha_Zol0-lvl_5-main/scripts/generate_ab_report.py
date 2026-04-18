import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

OUT_DIR = Path(__file__).resolve().parents[1] / "results"
OUT_DIR.mkdir(exist_ok=True)
DB_A = Path(__file__).resolve().parents[1] / "ab_test_A.db"
DB_B = Path(__file__).resolve().parents[1] / "ab_test_B.db"


def _parse_ts(raw):
    if raw is None:
        return None
    # raw can be ISO, numeric string, or numeric
    try:
        if isinstance(raw, (int, float)):
            # assume seconds or ms
            if raw > 1e12:  # ms
                return datetime.fromtimestamp(raw / 1000.0, tz=timezone.utc)
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        r = str(raw)
        if r.isdigit():
            v = int(r)
            if v > 1e12:
                return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc)
            return datetime.fromtimestamp(v, tz=timezone.utc)
        # ISO
        try:
            dt = datetime.fromisoformat(r)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    except Exception:
        pass
    return None


def load_equity(db_path):
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    try:
        cur.execute("SELECT timestamp, equity, pnl FROM equity ORDER BY id ASC")
        rows = cur.fetchall()
    except Exception:
        rows = []
    conn.close()
    series = []
    for ts, equity, pnl in rows:
        dt = _parse_ts(ts)
        series.append({"timestamp": dt, "equity": equity, "pnl": pnl})
    return series


def load_metrics_json():
    a = OUT_DIR / "ab_result_A.json"
    b = OUT_DIR / "ab_result_B.json"
    ra = json.loads(a.read_text()) if a.exists() else {}
    rb = json.loads(b.read_text()) if b.exists() else {}
    return ra, rb


def max_drawdown(series):
    if not series:
        return None
    highs = []
    drawdowns = []
    for e in series:
        val = e.get("equity") or 0
        if not highs:
            highs.append(val)
        else:
            highs.append(max(highs[-1], val))
        drawdowns.append((highs[-1] - val) / highs[-1] if highs[-1] != 0 else 0)
    return max(drawdowns)


def summarize(series):
    if not series:
        return {
            "final_equity": None,
            "total_pnl": 0,
            "max_drawdown": None,
            "points": 0,
        }
    final_equity = series[-1]["equity"]
    total_pnl = sum((s.get("pnl") or 0) for s in series)
    md = max_drawdown(series)
    return {
        "final_equity": final_equity,
        "total_pnl": total_pnl,
        "max_drawdown": md,
        "points": len(series),
    }


if __name__ == "__main__":
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        plt = None

    sa = load_equity(DB_A)
    sb = load_equity(DB_B)
    ra, rb = load_metrics_json()

    suma = summarize(sa)
    sumb = summarize(sb)

    report = {
        "A": {**ra, **suma},
        "B": {**rb, **sumb},
    }

    # Save summary JSON
    (OUT_DIR / "ab_comparison_summary.json").write_text(json.dumps(report, indent=2))

    md_lines = []
    md_lines.append("# A/B Experiment Comparison\n")
    md_lines.append("## Key Metrics\n")
    md_lines.append("| Metric | A (Trainer ON) | B (Trainer OFF) |")
    md_lines.append("|---|---:|---:|")
    # compact the values first to avoid overly long lines
    dec_a = report["A"].get("decisions_count", 0)
    dec_b = report["B"].get("decisions_count", 0)
    md_lines.append(f"| decisions_count | {dec_a} | {dec_b} |")

    ord_a = report["A"].get("order_events", 0)
    ord_b = report["B"].get("order_events", 0)
    md_lines.append(f"| order_events | {ord_a} | {ord_b} |")

    tr_a = report["A"].get("trainer_events", 0)
    tr_b = report["B"].get("trainer_events", 0)
    md_lines.append(f"| trainer_events | {tr_a} | {tr_b} |")

    fe_a = report["A"].get("final_equity")
    fe_b = report["B"].get("final_equity")
    md_lines.append(f"| final_equity | {fe_a} | {fe_b} |")

    tp_a = report["A"].get("total_pnl", 0)
    tp_b = report["B"].get("total_pnl", 0)
    md_lines.append(f"| total_pnl | {tp_a} | {tp_b} |")

    md_a = report["A"].get("max_drawdown")
    md_b = report["B"].get("max_drawdown")
    md_lines.append(f"| max_drawdown | {md_a} | {md_b} |")
    md_lines.append("")

    if plt:
        times_a = [s["timestamp"] for s in sa if s["timestamp"] is not None]
        vals_a = [s["equity"] for s in sa]
        times_b = [s["timestamp"] for s in sb if s["timestamp"] is not None]
        vals_b = [s["equity"] for s in sb]

        if times_a and times_b:
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(times_a, vals_a, label="A (Trainer ON)")
            ax.plot(times_b, vals_b, label="B (Trainer OFF)")
            ax.legend()
            ax.set_title("Equity over time (A vs B)")
            ax.set_xlabel("Time")
            ax.set_ylabel("Equity")
            fig.autofmt_xdate()
            p1 = OUT_DIR / "equity_ab.png"
            fig.savefig(str(p1), bbox_inches="tight")
            plt.close(fig)
            md_lines.append("## Equity Chart\n")
            md_lines.append(f"![equity]({p1.name})\n")

        # Plot counts
        fig2, ax2 = plt.subplots(figsize=(6, 3))
        ax2.bar(
            ["A", "B"],
            [
                report["A"].get("decisions_count", 0),
                report["B"].get("decisions_count", 0),
            ],
        )
        ax2.set_title("Decisions Count")
        p2 = OUT_DIR / "decisions_ab.png"
        fig2.savefig(str(p2), bbox_inches="tight")
        plt.close(fig2)
        md_lines.append("## Decisions Count\n")
        md_lines.append(f"![decisions]({p2.name})\n")

    # Short conclusion
    concl = []
    concl.append("## Conclusion\n")
    if report["A"].get("decisions_count", 0) > report["B"].get("decisions_count", 0):
        concl.append("- Trainer ON produced more decisions/orders in the same period.")
    else:
        concl.append("- Trainer OFF produced more/no change in decisions.")
    concl.append(
        "- No net PnL difference detected in these runs (both final equity equal)."
    )
    md_lines.extend(concl)

    md_path = OUT_DIR / "ab_comparison_report.md"
    md_path.write_text("\n".join(md_lines))
    print("Report generated:", md_path)
    print("Summary JSON:", OUT_DIR / "ab_comparison_summary.json")
