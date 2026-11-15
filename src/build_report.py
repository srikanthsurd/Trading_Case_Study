
from pathlib import Path
import json
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, ListFlowable, ListItem
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"

HEADER_BG = colors.HexColor("#244A66")
ROW_ALT = colors.HexColor("#F3F6F8")


def fmt(x, digits=2):
    if pd.isna(x):
        return "n/a"
    if isinstance(x, (int, float)):
        return f"{x:,.{digits}f}"
    return str(x)


def table_style(font_size=8):
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])


def add_docx_table(doc, rows):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Table Grid"
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            cell = table.rows[i].cells[j]
            cell.text = "" if value is None else str(value)
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(9)
                    if i == 0:
                        run.bold = True
                        run.font.color.rgb = RGBColor(255, 255, 255)
        if i == 0:
            for cell in table.rows[i].cells:
                shading = OxmlElement("w:shd")
                shading.set(qn("w:fill"), "244A66")
                shading.set(qn("w:val"), "clear")
                cell._tc.get_or_add_tcPr().append(shading)
    doc.add_paragraph()
    return table


def price_results():
    values = []
    for exp in ["A", "B", "C"]:
        pf = pd.read_csv(OUT / f"portfolio_returns_{exp}.csv")
        values.append(float(((1 + pf["gross_return"]).prod() - 1) * 100))
    return values


def performance_explanation(summary, price_vals, quality):
    a = summary[summary.experiment == "A"].iloc[0]
    b = summary[summary.experiment == "B"].iloc[0]
    c = summary[summary.experiment == "C"].iloc[0]
    winner = "Regime-switching hybrid"
    winner_net = float(c["net_total_return_pct"])
    return [
        (
            "Over the five sessions 10–14 November 2025, all three models finish with a positive net result "
            f"under the assumptions in section 4. Momentum returns {float(a['net_total_return_pct']):.2f}%, "
            f"mean reversion returns {float(b['net_total_return_pct']):.2f}%, and the regime-switching hybrid "
            f"returns {float(c['net_total_return_pct']):.2f}%. The hybrid is the strongest overall result."
        ),
        (
            "That ranking is driven mainly by execution income, not by a large forecast edge. "
            f"The open-to-open price result is {price_vals[0]:.2f}% for momentum, "
            f"{price_vals[1]:.2f}% for mean reversion, and {price_vals[2]:.2f}% for the hybrid. "
            "Momentum loses money on the price move itself. Mean reversion and the hybrid make only a small "
            "price gain. The net profit appears after the half-spread is credited under the passive-fill assumption."
        ),
        (
            f"Fees minus spread credit are {float(a['transaction_cost_bps_nav']):.1f} bps of NAV for momentum, "
            f"{float(b['transaction_cost_bps_nav']):.1f} bps for mean reversion, and "
            f"{float(c['transaction_cost_bps_nav']):.1f} bps for the hybrid. A negative number means the spread "
            "credit is larger than commission, exchange fee and sell-side fee. "
            f"Maximum drawdowns stay below 1% in absolute terms "
            f"({float(a['maximum_drawdown_pct']):.2f}%, {float(b['maximum_drawdown_pct']):.2f}% and "
            f"{float(c['maximum_drawdown_pct']):.2f}%)."
        ),
        (
            "By model: momentum holds longer, about 40 minutes on average, and keeps the highest average gross "
            "exposure. Mean reversion turns over faster, about 19 minutes, and is more sensitive to short-lived "
            "moves. The hybrid copies mean reversion in range-bound conditions and switches toward momentum when "
            "the index is trending. In this sample that mix gives the best net result with fewer trades than "
            "either pure approach. "
            f"The result is conditional on the reconstructed price path, where the median absolute one-minute "
            f"return falls from {quality['raw_equity_one_minute_median_absolute_return_pct']:.1f}% in the raw "
            f"file to {quality['equity_one_minute_median_absolute_return_pct']:.2f}% after reconstruction."
        ),
        (
            f"In short, {winner} is the preferred model for this exercise, with a five-session net return of "
            f"{winner_net:.2f}%. The preference is based on net return after fees and the assumed spread credit, "
            "drawdown, and the ability to switch style by regime. It is not a claim that the same result would "
            "appear in live markets."
        ),
    ]


def assumption_groups():
    return [
        (
            "Price path",
            [
                "The five supplied files are the only source of truth. No external market data is used.",
                "The raw files in data/raw/ are not modified.",
                "Each one-minute bar is internally consistent, but the printed price level is redrawn every minute.",
                "Each ticker-session, including INDEX, is anchored at its first open.",
                "The research path compounds the within-bar open-to-close return and drops the raw gap from one minute's close to the next minute's open.",
                "High, low, bid, ask and adjusted close are scaled with the open, so relative ranges and quoted spreads stay unchanged.",
            ],
        ),
        (
            "Execution and costs",
            [
                "The book supplies liquidity and is assumed filled at its own quote. The file has no queue.",
                "The half-spread is earned on entry and on exit. Crossing slippage is not charged.",
                "Commission is 0.8 bps, the exchange fee is 0.2 bps, and the sell-side fee is 0.1 bps.",
                "Long financing is 80 bps a year. Short borrow is the ticker fee in the metadata.",
                "A new name must be in the tightest 20% of equity quotes at that bar, measured by half-spread.",
                "The signal uses the completed bar. Execution is at the next 15-minute bar open.",
                "Invalid or crossed quotes use the ticker median half-spread, then the global median.",
                "A new trade is opened only after at least 30 completed tight-quote signals, and only when their average result is positive after fees net of the spread credit.",
            ],
        ),
        (
            "Portfolio, risk and events",
            [
                "NAV is 10,000,000 notional units. The file does not specify a currency.",
                "Target gross exposure is 50% long and 50% short.",
                "Caps are 5% of NAV per name, 100% gross and 10% net.",
                "At most 10 names are opened on each side. A name is opened only when its rank newly enters the top or bottom 5%.",
                "An open name keeps its weight while its rank remains in the outer 20%, until 180 minutes have passed, or until the session ends. There are no overnight positions.",
                "A 1% daily loss stop flattens later targets after the loss is realised.",
                "Hard-to-borrow names are not sold short. Locate limits, lot size and the maximum participation rate are applied.",
                "No new position is opened within 15 minutes of a scheduled event, or within 30 minutes of the Breaking News Window. Event labels have no direction and no impact.",
            ],
        ),
    ]


def write_docx(qrows, mrows, rrows, erows, summary, price_vals, quality):
    from docx import Document
    from docx.shared import Inches, Pt

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.75)
    section.right_margin = Inches(0.75)
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)

    doc.add_heading("European Intraday Strategy Lab", level=0)
    doc.add_heading("Trading Desk Case Study Research Report", level=2)
    doc.add_paragraph(
        "Date of materials: 13 November 2026. Research window: 10–14 November 2025. "
        "Universe: 500 equities plus INDEX. Research bars: 15 minutes."
    )

    doc.add_heading("1. Purpose", level=1)
    doc.add_paragraph(
        "This submission builds a clear, reproducible workflow on the five supplied synthetic files and no other data. "
        "The workflow:"
    )
    for item in [
        "ingests and validates the data",
        "designs and implements three intraday trading approaches",
        "simulates execution and costs",
        "produces this concise report with results and risk diagnostics",
    ]:
        doc.add_paragraph(item, style="List Number")
    doc.add_paragraph(
        "Net return in this report is the compounded result for the five sessions in the file. "
        "It is not a daily rate and it is not a yearly rate."
    )

    doc.add_heading("2. Data ingestion and validation", level=1)
    doc.add_paragraph(
        "The price file contains 1-minute bars for 500 tickers plus an index. "
        "Metadata, index weights, the event calendar and the fee schedule complete the source of truth. "
        f"Inside each minute the bars are orderly. Across minutes the printed level is not continuous: "
        f"the median absolute close-to-close equity return is "
        f"{quality['raw_equity_one_minute_median_absolute_return_pct']:.1f}%, and "
        f"{quality['raw_equity_one_minute_fraction_absolute_return_over_20pct']*100:.1f}% of those moves exceed 20%. "
        "The research path therefore rebuilds each ticker-session from the first open by compounding the "
        f"within-bar open-to-close return. After that step the median absolute one-minute return is "
        f"{quality['equity_one_minute_median_absolute_return_pct']:.2f}%."
    )
    add_docx_table(doc, qrows)
    doc.add_paragraph(
        "Exact duplicate (timestamp, ticker) keys keep the last row. Invalid OHLC rows are removed. "
        "Crossed quotes are not used directly for the spread; the ticker median, then the global median, is substituted. "
        "The files in data/raw/ are not modified."
    )

    doc.add_heading("3. Methodology", level=1)
    doc.add_paragraph(
        "Three models are compared on the same cleaned bars, the same portfolio rules and the same cost model."
    )
    doc.add_paragraph(
        "A — Momentum. Cross-sectional rank of the 60-minute return on 15-minute bars. "
        "New longs are the top 5% and new shorts are the bottom 5%, with at most 10 names on each side. "
        "A held name stays on while it remains in the outer 20%."
    )
    doc.add_paragraph(
        "B — Mean reversion. Negative one-bar return divided by the rolling 20-bar standard deviation of one-bar returns. "
        "The entry tail, name cap and hold band match strategy A."
    )
    doc.add_paragraph(
        "C — Regime-switching hybrid. Momentum when the index regime is trending, and mean reversion otherwise. "
        "In a high-volatility regime the target gross exposure is halved."
    )
    doc.add_paragraph(
        "The signal uses the completed bar. The trade is assumed at the next bar open. "
        "The index classifies the regime from an EMA spread over a rolling range, with high volatility defined by a lagged rolling median. "
        "A continuity gate still scores the reconstructed path and would block the backtest if that path were implausible. "
        "The gate thresholds are not relaxed."
    )

    doc.add_heading("4. Assumptions", level=1)
    doc.add_paragraph(
        "The following assumptions are stated separately from the model definitions. "
        "All results in this report are conditional on them."
    )
    for title, items in assumption_groups():
        doc.add_heading(title, level=2)
        for item in items:
            doc.add_paragraph(item, style="List Bullet")

    doc.add_heading("5. Key findings and overall performance", level=1)
    add_docx_table(doc, mrows)
    for paragraph in performance_explanation(summary, price_vals, quality):
        doc.add_paragraph(paragraph)

    doc.add_heading("6. Risk diagnostics", level=1)
    doc.add_paragraph(
        "Risk is summarised by regime, by exposure and by the equity and drawdown paths. "
        "Net return in the regime table is still the five-session contribution of that regime, not a yearly figure."
    )
    add_docx_table(doc, rrows)
    if erows:
        doc.add_heading("Exposure diagnostics", level=2)
        add_docx_table(doc, erows)
    for filename, caption in [
        ("equity_curves.png", "Net equity curves"),
        ("drawdowns.png", "Drawdown paths"),
        ("regime_performance.png", "Net return by classified market regime"),
    ]:
        path = OUT / filename
        if path.exists():
            doc.add_heading(caption, level=2)
            doc.add_picture(str(path), width=Inches(6.2))

    doc.add_heading("7. Limitations", level=1)
    for item in [
        f"The raw close-to-close series is discontinuous. The median absolute one-minute equity return is about {quality['raw_equity_one_minute_median_absolute_return_pct']:.1f}%. Those jumps are not traded.",
        "The research path is a reconstruction from within-bar returns. Rankings are conditional on that reconstruction.",
        "There is no queue. The spread credit assumes every selected order is filled at the posted quote.",
        "The sample is only five synthetic sessions. It cannot establish a long-run edge.",
        "The event calendar has timestamps and labels only. No direction or surprise is provided.",
        "No instrument currency, market-impact model or exchange auction mechanics are supplied.",
        "Trade episodes are contiguous position intervals, not exchange-confirmed fills.",
    ]:
        doc.add_paragraph(item, style="List Bullet")

    doc.add_heading("8. Reproducibility", level=1)
    doc.add_paragraph(
        "From a clean environment, install requirements.txt and run python run_project.py from the project root. "
        "That single command validates the files, runs all three models, writes the tables and figures to outputs/, "
        "and regenerates this report as outputs/research_report.pdf and outputs/research_report.docx. "
        "The run configuration is recorded in outputs/run_config.json."
    )

    destination = OUT / "research_report.docx"
    doc.save(destination)
    print("Wrote", destination)


def build_report(write_pdf=True, write_docx_file=True):
    summary = pd.read_csv(OUT / "strategy_summary.csv")
    regimes = pd.read_csv(OUT / "performance_by_regime.csv")
    quality = json.loads((OUT / "data_quality.json").read_text(encoding="utf-8"))
    price_vals = price_results()

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8, leading=10))
    styles.add(ParagraphStyle(
        name="Warning", parent=styles["BodyText"], fontSize=9, leading=12,
        textColor=colors.darkred, backColor=colors.whitesmoke, borderPadding=7
    ))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], spaceBefore=8, spaceAfter=5))
    styles.add(ParagraphStyle(name="BodyClear", parent=styles["BodyText"], fontSize=9.5, leading=13, spaceAfter=4))

    story = [
        Paragraph("European Intraday Strategy Lab", styles["Title"]),
        Paragraph("Trading Desk Case Study Research Report", styles["Heading2"]),
        Paragraph(
            "Date of materials: 13 November 2026 | Research window: 10–14 November 2025 | "
            "500 equities plus INDEX | 15-minute research bars",
            styles["Small"],
        ),
        Spacer(1, 4 * mm),
        Paragraph("1. Purpose", styles["Section"]),
        Paragraph(
            "This submission builds a clear, reproducible workflow on the five supplied synthetic files and no other data. "
            "The workflow ingests and validates the data, designs and implements three intraday trading approaches, "
            "simulates execution and costs, and produces this concise report with results and risk diagnostics. "
            "Net return below is the compounded result for the five sessions in the file. "
            "It is not a daily rate and it is not a yearly rate.",
            styles["BodyClear"],
        ),
        Paragraph(
            "Key data warning: the raw one-minute levels are not a continuous path. "
            f"The median absolute close-to-close equity return is {quality['raw_equity_one_minute_median_absolute_return_pct']:.1f}%, "
            f"and {quality['raw_equity_one_minute_fraction_absolute_return_over_20pct']*100:.1f}% of those moves exceed 20%. "
            "The research path rebuilds each ticker-session from the first open by compounding the within-bar open-to-close return. "
            f"On that path the median absolute one-minute equity return is {quality['equity_one_minute_median_absolute_return_pct']:.2f}%. "
            "All rankings are conditional on the assumptions in section 4.",
            styles["Warning"],
        ),
        Spacer(1, 3 * mm),
        Paragraph("2. Data ingestion and validation", styles["Section"]),
    ]

    qrows = [
        ["Validation item", "Observed"],
        ["Raw price rows", fmt(quality["raw_rows"], 0)],
        ["Equity tickers / index", f"{quality['raw_equity_tickers']} / {quality['index_rows']} index bars"],
        ["Sessions", f"{quality['raw_sessions']} ({', '.join(quality['sessions'])})"],
        ["Duplicate ticker/timestamp rows", fmt(quality["raw_duplicate_timestamp_ticker_rows"], 0)],
        ["Conflicting duplicate-key groups", fmt(quality["conflicting_duplicate_key_groups"], 0)],
        ["Crossed bid/ask rows", fmt(quality["raw_crossed_quotes"], 0)],
        ["Invalid OHLC rows", fmt(quality["raw_invalid_ohlc_rows"], 0)],
        ["Raw median absolute 1-minute return", f"{quality['raw_equity_one_minute_median_absolute_return_pct']:.2f}%"],
        ["Raw absolute 1-minute returns >20%", f"{quality['raw_equity_one_minute_fraction_absolute_return_over_20pct']*100:.2f}%"],
        ["Reconstructed median absolute 1-minute return", f"{quality['equity_one_minute_median_absolute_return_pct']:.2f}%"],
        ["Reconstructed absolute 1-minute returns >20%", f"{quality['equity_one_minute_fraction_absolute_return_over_20pct']*100:.2f}%"],
        ["Index constituent weight sum", fmt(quality["constituent_weight_sum"], 6)],
        ["Scheduled events", fmt(quality["event_count"], 0)],
    ]
    t = Table(qrows, colWidths=[78 * mm, 92 * mm], repeatRows=1)
    t.setStyle(table_style(8))
    story += [
        t,
        Spacer(1, 3 * mm),
        Paragraph(
            "Exact duplicate (timestamp, ticker) keys keep the last row. Invalid OHLC rows are removed. "
            "Crossed quotes are not used directly for the spread; the ticker median, then the global median, is substituted. "
            "The files in data/raw/ are not modified.",
            styles["Small"],
        ),
        PageBreak(),
        Paragraph("3. Methodology", styles["Section"]),
        Paragraph(
            "Three models are compared on the same cleaned bars, the same portfolio rules and the same cost model.",
            styles["BodyClear"],
        ),
        Paragraph(
            "<b>A — Momentum.</b> Cross-sectional rank of the 60-minute return on 15-minute bars. "
            "New longs are the top 5% and new shorts are the bottom 5%, with at most 10 names on each side. "
            "A held name stays on while it remains in the outer 20%.",
            styles["BodyClear"],
        ),
        Paragraph(
            "<b>B — Mean reversion.</b> Negative one-bar return divided by the rolling 20-bar standard deviation of one-bar returns. "
            "The entry tail, name cap and hold band match strategy A.",
            styles["BodyClear"],
        ),
        Paragraph(
            "<b>C — Regime-switching hybrid.</b> Momentum when the index regime is trending, and mean reversion otherwise. "
            "In a high-volatility regime the target gross exposure is halved.",
            styles["BodyClear"],
        ),
        Paragraph(
            "The signal uses the completed bar. The trade is assumed at the next bar open. "
            "The index classifies the regime from an EMA spread over a rolling range, with high volatility defined by a lagged rolling median. "
            "A continuity gate still scores the reconstructed path and would block the backtest if that path were implausible. "
            "The gate thresholds are not relaxed.",
            styles["Small"],
        ),
        Paragraph("4. Assumptions", styles["Section"]),
        Paragraph(
            "The following assumptions are stated separately from the model definitions. "
            "All results in this report are conditional on them.",
            styles["BodyClear"],
        ),
    ]

    for title, items in assumption_groups():
        story.append(Paragraph(f"<b>{title}</b>", styles["Heading3"]))
        story.append(ListFlowable(
            [ListItem(Paragraph(item, styles["Small"]), leftIndent=8, bulletColor=HEADER_BG) for item in items],
            bulletType="bullet",
            start="•",
            leftIndent=12,
            bulletFontSize=8,
        ))
        story.append(Spacer(1, 2 * mm))

    story.append(Paragraph("5. Key findings and overall performance", styles["Section"]))
    mrows = [["Metric", "A: Momentum", "B: Mean reversion", "C: Hybrid"]]
    mrows.append(["Price result over 5 sessions (%)"] + [fmt(v) for v in price_vals])
    cols = [
        ("net_total_return_pct", "Net return over 5 sessions (%)"),
        ("net_sharpe_annualized_indicative", "Indicative Sharpe*"),
        ("maximum_drawdown_pct", "Maximum drawdown (%)"),
        ("profit_factor_trade_episodes", "Profit factor"),
        ("win_rate_trade_episodes_pct", "Win rate (%)"),
        ("average_trade_return_bps", "Average trade return (bps)"),
        ("total_turnover_pct_nav", "Turnover (% NAV)"),
        ("transaction_cost_bps_nav", "Fees minus spread credit (bps NAV)"),
    ]
    for key, label in cols:
        vals = []
        for exp in ["A", "B", "C"]:
            row = summary[summary.experiment == exp].iloc[0]
            v = row.get(key)
            vals.append("n/a" if pd.isna(v) else fmt(float(v), 2))
        mrows.append([label] + vals)

    t2 = Table(mrows, colWidths=[66 * mm, 34 * mm, 34 * mm, 34 * mm], repeatRows=1)
    t2.setStyle(table_style(7.5))
    t2.setStyle(TableStyle([("ALIGN", (1, 1), (-1, -1), "RIGHT")]))
    story += [t2, Spacer(1, 3 * mm)]
    for paragraph in performance_explanation(summary, price_vals, quality):
        story.append(Paragraph(paragraph, styles["BodyClear"]))

    story += [
        Spacer(1, 2 * mm),
        Paragraph(
            "Net return is the compounded result for 10–14 November 2025. "
            "A negative fees-minus-spread figure means the half-spread credit exceeded commission, exchange fee and sell-side fee. "
            "The indicative Sharpe is a scaling of these five sessions only.",
            styles["Warning"],
        ),
        PageBreak(),
        Paragraph("6. Risk diagnostics", styles["Section"]),
        Paragraph(
            "Risk is summarised by regime, by exposure and by the equity and drawdown paths. "
            "Net return in the regime table is still the five-session contribution of that regime, not a yearly figure.",
            styles["BodyClear"],
        ),
    ]

    rrows = [["Strategy", "Regime", "Periods", "Net return (%)", "Mean 15m (bps)", "Turnover (% NAV)"]]
    for _, r in regimes.iterrows():
        rrows.append([
            r["strategy"], r["regime"], str(int(r["periods"])),
            fmt(r["net_return_pct"]), fmt(r["mean_15m_return_bps"]), fmt(r["turnover_pct_nav"]),
        ])
    tr = Table(rrows, colWidths=[43 * mm, 30 * mm, 16 * mm, 27 * mm, 27 * mm, 27 * mm], repeatRows=1)
    tr.setStyle(table_style(7))
    story += [tr, Spacer(1, 3 * mm)]

    erows = None
    exposure_path = OUT / "exposure_diagnostics.csv"
    if exposure_path.exists():
        exp = pd.read_csv(exposure_path)
        erows = [["Strategy", "Avg gross (%)", "Max gross (%)", "Avg net (%)", "Avg long names", "Avg short names"]]
        for _, e in exp.iterrows():
            erows.append([
                e["strategy"], fmt(e["average_gross_exposure_pct"]),
                fmt(e["maximum_gross_exposure_pct"]), fmt(e["average_net_exposure_pct"]),
                fmt(e["average_long_names"]), fmt(e["average_short_names"]),
            ])
        et = Table(erows, colWidths=[48 * mm, 25 * mm, 25 * mm, 23 * mm, 25 * mm, 25 * mm], repeatRows=1)
        et.setStyle(table_style(7))
        et.setStyle(TableStyle([("ALIGN", (1, 1), (-1, -1), "RIGHT")]))
        story += [Paragraph("Exposure diagnostics", styles["Heading3"]), et, Spacer(1, 2 * mm)]

    for fn, caption in [
        ("equity_curves.png", "Net equity curves"),
        ("drawdowns.png", "Drawdown paths"),
        ("regime_performance.png", "Net return by classified market regime"),
    ]:
        path = OUT / fn
        if path.exists():
            story += [
                Paragraph(caption, styles["Heading3"]),
                Image(str(path), width=165 * mm, height=82 * mm),
                Spacer(1, 2 * mm),
            ]

    story += [
        PageBreak(),
        Paragraph("7. Limitations", styles["Section"]),
        ListFlowable(
            [
                ListItem(Paragraph(
                    f"The raw close-to-close series is discontinuous. The median absolute one-minute equity return is about "
                    f"{quality['raw_equity_one_minute_median_absolute_return_pct']:.1f}%. Those jumps are not traded.",
                    styles["Small"],
                ), leftIndent=8, bulletColor=HEADER_BG),
                ListItem(Paragraph(
                    "The research path is a reconstruction from within-bar returns. Rankings are conditional on that reconstruction.",
                    styles["Small"],
                ), leftIndent=8, bulletColor=HEADER_BG),
                ListItem(Paragraph(
                    "There is no queue. The spread credit assumes every selected order is filled at the posted quote.",
                    styles["Small"],
                ), leftIndent=8, bulletColor=HEADER_BG),
                ListItem(Paragraph(
                    "The sample is only five synthetic sessions. It cannot establish a long-run edge.",
                    styles["Small"],
                ), leftIndent=8, bulletColor=HEADER_BG),
                ListItem(Paragraph(
                    "The event calendar has timestamps and labels only. No direction or surprise is provided.",
                    styles["Small"],
                ), leftIndent=8, bulletColor=HEADER_BG),
                ListItem(Paragraph(
                    "No instrument currency, market-impact model or exchange auction mechanics are supplied.",
                    styles["Small"],
                ), leftIndent=8, bulletColor=HEADER_BG),
                ListItem(Paragraph(
                    "Trade episodes are contiguous position intervals, not exchange-confirmed fills.",
                    styles["Small"],
                ), leftIndent=8, bulletColor=HEADER_BG),
            ],
            bulletType="bullet",
            start="•",
            leftIndent=12,
            bulletFontSize=8,
        ),
        Spacer(1, 3 * mm),
        Paragraph("8. Reproducibility", styles["Section"]),
        Paragraph(
            "From a clean environment, install requirements.txt and run <b>python run_project.py</b> from the project root. "
            "That single command validates the files, runs all three models, writes the tables and figures to outputs/, "
            "and regenerates this report as outputs/research_report.pdf and outputs/research_report.docx. "
            "The run configuration is recorded in outputs/run_config.json.",
            styles["BodyClear"],
        ),
    ]

    if write_pdf:
        doc = SimpleDocTemplate(
            str(OUT / "research_report.pdf"),
            pagesize=A4,
            rightMargin=18 * mm,
            leftMargin=18 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
        )
        doc.build(story)
        print("Wrote", OUT / "research_report.pdf")
    if write_docx_file:
        write_docx(qrows, mrows, rrows, erows, summary, price_vals, quality)


if __name__ == "__main__":
    build_report()
