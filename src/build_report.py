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

STRATEGY_NAME = {
    "Momentum": "Momentum",
    "Mean reversion": "Mean reversion",
    "Regime-switching hybrid": "Regime-switching hybrid",
}
REGIME_NAME = {
    "high_volatility": "high volatility",
    "range_bound": "range-bound",
    "trending": "trending",
}
REGIME_ORDER = ["high volatility", "range-bound", "trending"]


def fmt(x, digits=2):
    if pd.isna(x):
        return "n/a"
    if isinstance(x, (int, float)):
        return f"{x:,.{digits}f}"
    return str(x)


def plain_strategy(name):
    return STRATEGY_NAME.get(str(name), str(name))


def plain_regime(name):
    return REGIME_NAME.get(str(name), str(name))


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


def add_docx_table(doc, rows, bold_body=False):
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
                    if i == 0 or bold_body:
                        run.bold = True
                    if i == 0:
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


def refresh_figures():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [("A", "Momentum"), ("B", "Mean reversion"), ("C", "Regime-switching hybrid")]
    portfolios = {label: pd.read_csv(OUT / f"portfolio_returns_{code}.csv") for code, label in labels}

    plt.figure(figsize=(10, 5))
    for label, pf in portfolios.items():
        plt.plot(pd.to_datetime(pf.timestamp), pf.equity, label=label)
    plt.title("Portfolio value over the five days")
    plt.xlabel("Time")
    plt.ylabel("Value, starting at 1")
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUT / "equity_curves.png", dpi=160)
    plt.close()

    plt.figure(figsize=(10, 5))
    for label, pf in portfolios.items():
        plt.plot(pd.to_datetime(pf.timestamp), pf.drawdown * 100, label=label)
    plt.title("Loss from the peak")
    plt.xlabel("Time")
    plt.ylabel("Loss from peak (%)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUT / "drawdowns.png", dpi=160)
    plt.close()

    regimes = pd.read_csv(OUT / "performance_by_regime.csv")
    regimes["strategy"] = regimes["strategy"].map(plain_strategy)
    regimes["regime"] = regimes["regime"].map(plain_regime)
    pivot = regimes.pivot(index="regime", columns="strategy", values="net_return_pct").fillna(0)
    pivot = pivot.reindex(REGIME_ORDER)
    pivot = pivot[["Momentum", "Mean reversion", "Regime-switching hybrid"]]
    pivot.columns.name = None
    ax = pivot.plot(kind="bar", figsize=(9, 5))
    ax.set_title("Result by market type")
    ax.set_xlabel("Market type")
    ax.set_ylabel("Result over these five days (%)")
    plt.xticks(rotation=0)
    plt.tight_layout()
    plt.savefig(OUT / "regime_performance.png", dpi=160)
    plt.close()


def overall_return_rows(summary):
    rows = [["Measure", "A: Momentum", "B: Mean reversion", "C: Regime-switching hybrid"]]
    values = []
    for exp in ["A", "B", "C"]:
        value = float(summary[summary.experiment == exp].iloc[0]["net_total_return_pct"])
        values.append(fmt(value))
    rows.append(["Net return over 5 days (%)"] + values)
    return rows


def overall_intro():
    return (
        "Three intraday trading approaches are tested on the same 500 stocks, the same costs and the same five days. "
        "Momentum buys stocks that have been rising and sells short stocks that have been falling. "
        "Mean reversion takes the opposite side of the last 15-minute move. "
        "The regime-switching hybrid uses Momentum when the index is trending and Mean reversion when it is not."
    )


def overall_result_parts(summary):
    momentum = float(summary[summary.experiment == "A"].iloc[0]["net_total_return_pct"])
    mean_reversion = float(summary[summary.experiment == "B"].iloc[0]["net_total_return_pct"])
    hybrid = float(summary[summary.experiment == "C"].iloc[0]["net_total_return_pct"])
    lead = "All three strategies finish with a profit under the assumptions in section 3. "
    emphasis = (
        f"Momentum makes {momentum:.2f}%. Mean reversion makes {mean_reversion:.2f}%. "
        f"The regime-switching hybrid is the strongest result, at {hybrid:.2f}% over the five days."
    )
    return lead, emphasis


def net_return_definition():
    return (
        "Net return in this report is the total result for the five days in the file. "
        "It is not a daily rate and it is not a yearly rate."
    )


def daily_return_rows(summary):
    import ast

    by_exp = {}
    for exp in ["A", "B", "C"]:
        raw = summary[summary.experiment == exp].iloc[0]["daily_returns_pct"]
        parsed = ast.literal_eval(raw) if isinstance(raw, str) else dict(raw)
        by_exp[exp] = {str(key): float(value) for key, value in parsed.items()}
    rows = [["Day", "Momentum", "Mean reversion", "Regime-switching hybrid"]]
    for day in sorted(by_exp["A"]):
        stamp = pd.Timestamp(day)
        label = f"{stamp.day} {stamp.strftime('%B %Y')}"
        rows.append([label] + [fmt(by_exp[exp][day]) for exp in ["A", "B", "C"]])
    return rows


def performance_paragraphs(summary, price_vals, quality):
    a = summary[summary.experiment == "A"].iloc[0]
    b = summary[summary.experiment == "B"].iloc[0]
    c = summary[summary.experiment == "C"].iloc[0]
    return [
        (
            "Over the five days from 10 to 14 November 2025, all three strategies finish with a profit "
            "under the assumptions in section 4. "
            f"Momentum makes {float(a['net_total_return_pct']):.2f}%. "
            f"Mean reversion makes {float(b['net_total_return_pct']):.2f}%. "
            f"The regime-switching hybrid makes {float(c['net_total_return_pct']):.2f}%. "
            "The regime-switching hybrid is the best result."
        ),
        (
            f"The price move itself is {price_vals[0]:.2f}% for momentum, "
            f"{price_vals[1]:.2f}% for mean reversion, and {price_vals[2]:.2f}% for the regime-switching hybrid. "
            "Momentum loses money on the price move. Mean reversion and the hybrid make only a small gain on the price."
        ),
        (
            f"Momentum holds a stock for about {round(float(a['average_trade_holding_minutes']))} minutes "
            "and keeps the largest book. "
            f"Mean reversion holds for about {round(float(b['average_trade_holding_minutes']))} minutes "
            "and reacts to short moves. "
            "The regime-switching hybrid uses mean reversion when the market is range-bound and momentum when the index is trending. "
            f"In this sample the hybrid has the best result, with {int(c['number_trade_episodes'])} trades "
            f"against {int(a['number_trade_episodes'])} for momentum and {int(b['number_trade_episodes'])} for mean reversion. "
            "This depends on the rebuilt prices. The typical one-minute move falls from "
            f"{quality['raw_equity_one_minute_median_absolute_return_pct']:.1f}% in the raw file to "
            f"{quality['equity_one_minute_median_absolute_return_pct']:.2f}% after the rebuild."
        ),
        (
            "The regime-switching hybrid is the preferred rule for this exercise, with a five-day net return of "
            f"{float(c['net_total_return_pct']):.2f}%. "
            "The choice is based on profit after fees and the assumed quote credit, "
            "the size of the fall from the peak, and the ability to change style with the market. "
            "This is not a claim that the same result would happen in live trading."
        ),
    ]


def assumption_groups():
    return [
        (
            "Prices",
            [
                "Only the five supplied files are used. No outside market data is added.",
                "Each one-minute bar is consistent on its own, but the printed price jumps every minute.",
                "Each stock, and the index, starts each day at its first open price.",
                "The study keeps the open-to-close move inside each minute and drops the jump from that close to the next open.",
                "High, low, bid, ask and adjusted close move with the open, so the quoted gap stays the same in percentage terms.",
            ],
        ),
        (
            "Trading and costs",
            [
                "The book is assumed to provide liquidity and to be filled at its own quote. The file has no order queue.",
                "The book earns half the gap between bid and ask on entry and on exit. Extra slippage is not charged.",
                "A new stock must be among the 20% with the tightest quotes at that bar.",
                "The signal uses a finished 15-minute bar. The trade is assumed at the next bar's open.",
                "A bad or crossed quote is replaced by that stock's typical half-gap, then by the typical half-gap of all stocks.",
                "A new trade starts only after 30 finished tight-quote signals, and only if their average result is positive after fees and the quote credit.",
            ],
        ),
        (
            "Portfolio, risk and news",
            [
                "The starting value is 10,000,000.",
                "The target book is 50% long and 50% short.",
                "Limits are 5% per stock, 100% long plus short, and 10% long minus short.",
                "At most 10 stocks are opened on each side. A stock is added only when it newly enters the top 5% or the bottom 5%.",
                "A held stock keeps its size while it stays in the outer 20%, until 180 minutes pass, or until the day ends. Nothing is held overnight.",
                "If the book loses 1% in a day, later targets that day are closed after the loss is known.",
                "Stocks marked hard to borrow are not sold short. Lot size and the largest allowed trade size are applied.",
                "No new trade starts within 15 minutes of a scheduled event, or within 30 minutes of the breaking-news window. The labels do not say whether the news was good or bad.",
            ],
        ),
    ]


def data_intro(quality):
    return (
        "The price file has one-minute prices for 500 stocks and one index. "
        "The other files give stock details, index weights, news times and fees. "
        "Each minute looks orderly on its own. The problem is the jump from one minute to the next. "
        f"The typical jump is {quality['raw_equity_one_minute_median_absolute_return_pct']:.1f}%, "
        f"and {quality['raw_equity_one_minute_fraction_absolute_return_over_20pct']*100:.1f}% of those jumps are larger than 20%. "
        "The study rebuilds each stock, each day, from its first price. It keeps only the move inside the minute, from open to close. "
        f"After that rebuild, the typical one-minute move is {quality['equity_one_minute_median_absolute_return_pct']:.2f}%."
    )


def data_note():
    return (
        "If the same stock appears twice at the same time, the last row is kept. "
        "Rows with an impossible open, high, low or close are removed."
    )


def purpose_steps():
    return [
        "Check the data.",
        "Build three short-term trading rules.",
        "Apply trading costs.",
        "Write this report, with the results and the risk checks.",
    ]


def limitations(quality):
    return [
        (
            f"The raw prices jump from minute to minute. The typical jump is about "
            f"{quality['raw_equity_one_minute_median_absolute_return_pct']:.1f}%. Those jumps are not traded."
        ),
        "The prices used here are rebuilt from the move inside each minute. The ranking depends on that rebuild.",
        "There is no order queue. The quote credit assumes every chosen order is filled at the posted quote.",
        "The sample is only five made-up trading days. It cannot show a lasting edge.",
        "The news calendar has times and labels only. It does not say whether the news was good or bad.",
        "The files do not give a currency, a market-impact model, or opening and closing auction rules.",
        "A trade here is the stretch of time a stock was held, not a fill confirmed by an exchange.",
    ]


def result_footnote():
    return (
        "Net return is the total result for 10–14 November 2025. It is not a daily rate and it is not a yearly rate. "
        "The risk-adjusted score only rescales these five days."
    )


def write_docx(qrows, mrows, drows, rrows, erows, summary, price_vals, quality):
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

    doc.add_heading("Trading Desk Case Study Report", level=0)

    doc.add_heading("Overall Summary", level=1)
    doc.add_paragraph(overall_intro())
    lead, emphasis = overall_result_parts(summary)
    result = doc.add_paragraph()
    result.add_run(lead)
    result.add_run(emphasis).bold = True
    add_docx_table(doc, overall_return_rows(summary), bold_body=True)
    doc.add_paragraph(net_return_definition())

    doc.add_heading("1. Data check", level=1)
    doc.add_paragraph(data_intro(quality))
    add_docx_table(doc, qrows)
    doc.add_paragraph(data_note())

    doc.add_heading("2. How the three rules work", level=1)
    doc.add_paragraph(
        "All three rules use the same cleaned prices, the same position limits and the same costs. "
        "They are called Momentum, Mean reversion and Regime-switching hybrid."
    )
    doc.add_paragraph(
        "A — Momentum. Buy the stocks that rose the most over the last 60 minutes. "
        "Sell short the stocks that fell the most. New buys are the top 5% and new shorts are the bottom 5%, "
        "with at most 10 stocks on each side. A held stock stays in the book while it remains in the outer 20%."
    )
    doc.add_paragraph(
        "B — Mean reversion. Take the opposite side of the last 15-minute move, after allowing for how much that stock has been moving. "
        "The entry rule, the 10-stock cap and the hold rule match Momentum."
    )
    doc.add_paragraph(
        "C — Regime-switching hybrid. Use Momentum when the index is trending, and Mean reversion otherwise. "
        "When volatility is high, the target size is cut in half."
    )
    doc.add_paragraph(
        "The signal comes from a finished bar. The trade is assumed at the next bar's open. "
        "A data check still reviews the rebuilt prices and would stop the test if those prices looked impossible."
    )

    doc.add_heading("3. Assumptions", level=1)
    doc.add_paragraph(
        "These assumptions are listed on their own, separate from the trading rules. "
        "Every result in this report depends on them."
    )
    for title, items in assumption_groups():
        doc.add_heading(title, level=2)
        for item in items:
            doc.add_paragraph(item, style="List Bullet")

    doc.add_heading("4. Results", level=1)
    add_docx_table(doc, mrows)
    doc.add_heading("Net return by day (%)", level=2)
    doc.add_paragraph(
        "Each number is that day's net result. The five-day net return in the table above is the compounded total, "
        "not the sum of these five days."
    )
    add_docx_table(doc, drows)
    for paragraph in performance_paragraphs(summary, price_vals, quality):
        doc.add_paragraph(paragraph)

    doc.add_heading("5. Risk checks", level=1)
    doc.add_paragraph(
        "Risk is shown by market type, by book size, and by the charts below. "
        "High volatility means the market is moving sharply. Range-bound means it is not going anywhere. "
        "Trending means the index is moving in one direction. "
        "The return in this table is that market type's share of the five-day result. It is not a yearly figure."
    )
    add_docx_table(doc, rrows)
    if erows:
        doc.add_heading("Book size", level=2)
        add_docx_table(doc, erows)
    for filename, caption in [
        ("equity_curves.png", "Portfolio value over the five days"),
        ("drawdowns.png", "Loss from the peak"),
        ("regime_performance.png", "Result by market type"),
    ]:
        path = OUT / filename
        if path.exists():
            doc.add_heading(caption, level=2)
            doc.add_picture(str(path), width=Inches(6.2))

    doc.add_heading("6. Limits of this study", level=1)
    for item in limitations(quality):
        doc.add_paragraph(item, style="List Bullet")

    destination = OUT / "research_report.docx"
    try:
        doc.save(destination)
    except PermissionError:
        destination = OUT / "research_report_plain.docx"
        doc.save(destination)
        print("The original Word file is open, so the new report was saved beside it.")
    print("Wrote", destination)


def build_report(write_pdf=True, write_docx_file=True):
    refresh_figures()
    summary = pd.read_csv(OUT / "strategy_summary.csv")
    regimes = pd.read_csv(OUT / "performance_by_regime.csv")
    quality = json.loads((OUT / "data_quality.json").read_text(encoding="utf-8"))
    price_vals = price_results()

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8, leading=10))
    styles.add(ParagraphStyle(
        name="Note", parent=styles["BodyText"], fontSize=9, leading=12,
        textColor=colors.HexColor("#1F3A4D"), backColor=colors.whitesmoke, borderPadding=7
    ))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], spaceBefore=8, spaceAfter=5))
    styles.add(ParagraphStyle(name="BodyClear", parent=styles["BodyText"], fontSize=9.5, leading=13, spaceAfter=4))
    styles.add(ParagraphStyle(name="CellHead", parent=styles["Small"], fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=colors.white))
    styles.add(ParagraphStyle(name="Cell", parent=styles["Small"], fontSize=7.5, leading=9))
    styles.add(ParagraphStyle(name="CellRight", parent=styles["Small"], fontSize=7.5, leading=9, alignment=2))
    styles.add(ParagraphStyle(name="CellBold", parent=styles["Cell"], fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="CellBoldRight", parent=styles["CellRight"], fontName="Helvetica-Bold"))

    story = [
        Paragraph("Trading Desk Case Study Report", styles["Title"]),
        Spacer(1, 4 * mm),
        Paragraph("Overall Summary", styles["Section"]),
    ]
    story.append(Paragraph(overall_intro(), styles["BodyClear"]))
    lead, emphasis = overall_result_parts(summary)
    story.append(Paragraph(lead + f"<b>{emphasis}</b>", styles["BodyClear"]))
    opening = Table(
        [
            [Paragraph(
                str(value),
                styles["CellHead"] if i == 0 else (styles["CellBold"] if j == 0 else styles["CellBoldRight"]),
            ) for j, value in enumerate(row)]
            for i, row in enumerate(overall_return_rows(summary))
        ],
        colWidths=[58 * mm, 40 * mm, 40 * mm, 40 * mm],
        repeatRows=1,
    )
    opening.setStyle(table_style(7.5))
    story += [
        opening,
        Spacer(1, 2 * mm),
        Paragraph(net_return_definition(), styles["BodyClear"]),
        Paragraph("1. Data check", styles["Section"]),
        Paragraph(data_intro(quality), styles["BodyClear"]),
    ]

    qrows = [
        ["Check", "What we found"],
        ["Price rows", fmt(quality["raw_rows"], 0)],
        ["Stocks / index bars", f"{quality['raw_equity_tickers']} / {quality['index_rows']}"],
        ["Trading days", f"{quality['raw_sessions']} ({', '.join(quality['sessions'])})"],
        ["Repeated stock-and-time rows", fmt(quality["raw_duplicate_timestamp_ticker_rows"], 0)],
        ["Repeated rows that disagree", fmt(quality["conflicting_duplicate_key_groups"], 0)],
        ["Bid higher than ask", fmt(quality["raw_crossed_quotes"], 0)],
        ["Bad price rows", fmt(quality["raw_invalid_ohlc_rows"], 0)],
        ["Typical raw one-minute move", f"{quality['raw_equity_one_minute_median_absolute_return_pct']:.2f}%"],
        ["Raw moves larger than 20%", f"{quality['raw_equity_one_minute_fraction_absolute_return_over_20pct']*100:.2f}%"],
        ["Typical rebuilt one-minute move", f"{quality['equity_one_minute_median_absolute_return_pct']:.2f}%"],
        ["Rebuilt moves larger than 20%", f"{quality['equity_one_minute_fraction_absolute_return_over_20pct']*100:.2f}%"],
        ["Index weights add up to", fmt(quality["constituent_weight_sum"], 6)],
        ["News events", fmt(quality["event_count"], 0)],
    ]
    t = Table(qrows, colWidths=[78 * mm, 92 * mm], repeatRows=1)
    t.setStyle(table_style(8))
    story += [
        t,
        Spacer(1, 3 * mm),
        Paragraph(data_note(), styles["Small"]),
        Paragraph("2. How the three rules work", styles["Section"]),
        Paragraph(
            "All three rules use the same cleaned prices, the same position limits and the same costs. "
            "They are called Momentum, Mean reversion and Regime-switching hybrid.",
            styles["BodyClear"],
        ),
        Paragraph(
            "<b>A — Momentum.</b> Buy the stocks that rose the most over the last 60 minutes. "
            "Sell short the stocks that fell the most. New buys are the top 5% and new shorts are the bottom 5%, "
            "with at most 10 stocks on each side. A held stock stays in the book while it remains in the outer 20%.",
            styles["BodyClear"],
        ),
        Paragraph(
            "<b>B — Mean reversion.</b> Take the opposite side of the last 15-minute move, after allowing for how much that stock has been moving. "
            "The entry rule, the 10-stock cap and the hold rule match Momentum.",
            styles["BodyClear"],
        ),
        Paragraph(
            "<b>C — Regime-switching hybrid.</b> Use Momentum when the index is trending, and Mean reversion otherwise. "
            "When volatility is high, the target size is cut in half.",
            styles["BodyClear"],
        ),
        Paragraph(
            "The signal comes from a finished bar. The trade is assumed at the next bar's open. "
            "A data check still reviews the rebuilt prices and would stop the test if those prices looked impossible.",
            styles["Small"],
        ),
        Paragraph("3. Assumptions", styles["Section"]),
        Paragraph(
            "These assumptions are listed on their own, separate from the trading rules. "
            "Every result in this report depends on them.",
            styles["BodyClear"],
        ),
    ]

    for title, items in assumption_groups():
        story.append(Paragraph(title, styles["Heading3"]))
        story.append(ListFlowable(
            [ListItem(Paragraph(item, styles["Small"]), leftIndent=8, bulletColor=HEADER_BG) for item in items],
            bulletType="bullet",
            start="•",
            leftIndent=12,
            bulletFontSize=8,
        ))
        story.append(Spacer(1, 2 * mm))

    story.append(Paragraph("4. Results", styles["Section"]))
    mrows = [["Measure", "A: Momentum", "B: Mean reversion", "C: Regime-switching hybrid"]]
    cols = [
        ("net_total_return_pct", "Net return over 5 days (%)"),
        ("net_sharpe_annualized_indicative", "Risk-adjusted score*"),
        ("maximum_drawdown_pct", "Largest fall from peak (%)"),
        ("profit_factor_trade_episodes", "Gains divided by losses"),
        ("win_rate_trade_episodes_pct", "Winning trades (%)"),
        ("average_trade_return_bps", "Average trade (bps)"),
        ("total_turnover_pct_nav", "Trading activity (% of book)"),
    ]
    for key, label in cols:
        vals = []
        for exp in ["A", "B", "C"]:
            row = summary[summary.experiment == exp].iloc[0]
            v = row.get(key)
            vals.append("n/a" if pd.isna(v) else fmt(float(v), 2))
        mrows.append([label] + vals)

    def wrapped(rows):
        out = []
        for i, row in enumerate(rows):
            if i == 0:
                out.append([Paragraph(str(value), styles["CellHead"]) for value in row])
            else:
                out.append(
                    [Paragraph(str(row[0]), styles["Cell"])]
                    + [Paragraph(str(value), styles["CellRight"]) for value in row[1:]]
                )
        return out

    t2 = Table(wrapped(mrows), colWidths=[58 * mm, 40 * mm, 40 * mm, 40 * mm], repeatRows=1)
    t2.setStyle(table_style(7.5))
    t2.setStyle(TableStyle([("ALIGN", (1, 1), (-1, -1), "RIGHT")]))
    drows = daily_return_rows(summary)
    daily = Table(wrapped(drows), colWidths=[38 * mm, 46 * mm, 47 * mm, 47 * mm], repeatRows=1)
    daily.setStyle(table_style(7.5))
    daily.setStyle(TableStyle([("ALIGN", (1, 1), (-1, -1), "RIGHT")]))
    story += [
        t2,
        Spacer(1, 3 * mm),
        Paragraph("Net return by day (%)", styles["Heading3"]),
        Paragraph(
            "Each number is that day's net result. The five-day net return in the table above is the compounded total, "
            "not the sum of these five days.",
            styles["Small"],
        ),
        daily,
        Spacer(1, 3 * mm),
    ]
    for paragraph in performance_paragraphs(summary, price_vals, quality):
        story.append(Paragraph(paragraph, styles["BodyClear"]))
    story += [
        Paragraph("5. Risk checks", styles["Section"]),
        Paragraph(
            "Risk is shown by market type, by book size, and by the charts. "
            "High volatility means the market is moving sharply. Range-bound means it is not going anywhere. "
            "Trending means the index is moving in one direction. "
            "The return in this table is that market type's share of the five-day result. It is not a yearly figure.",
            styles["BodyClear"],
        ),
    ]

    regimes = regimes.copy()
    regimes["strategy"] = regimes["strategy"].map(plain_strategy)
    regimes["regime"] = regimes["regime"].map(plain_regime)
    regimes["_order"] = regimes["regime"].map({name: i for i, name in enumerate(REGIME_ORDER)})
    regimes["_strategy"] = regimes["strategy"].map({"Momentum": 0, "Mean reversion": 1, "Regime-switching hybrid": 2})
    regimes = regimes.sort_values(["_strategy", "_order"])
    rrows = [["Rule", "Market type", "Bars", "Net return (%)", "Average 15-min (bps)", "Trading activity (%)"]]
    for _, r in regimes.iterrows():
        rrows.append([
            r["strategy"], r["regime"], str(int(r["periods"])),
            fmt(r["net_return_pct"]), fmt(r["mean_15m_return_bps"]), fmt(r["turnover_pct_nav"]),
        ])
    tr = Table(wrapped(rrows), colWidths=[42 * mm, 28 * mm, 16 * mm, 28 * mm, 32 * mm, 32 * mm], repeatRows=1)
    tr.setStyle(table_style(7))
    story += [tr, Spacer(1, 3 * mm)]

    erows = None
    exposure_path = OUT / "exposure_diagnostics.csv"
    if exposure_path.exists():
        exp = pd.read_csv(exposure_path)
        erows = [["Rule", "Average size (%)", "Largest size (%)", "Long minus short (%)", "Average longs", "Average shorts"]]
        for _, e in exp.iterrows():
            erows.append([
                plain_strategy(e["strategy"]), fmt(e["average_gross_exposure_pct"]),
                fmt(e["maximum_gross_exposure_pct"]), fmt(e["average_net_exposure_pct"]),
                fmt(e["average_long_names"]), fmt(e["average_short_names"]),
            ])
        et = Table(wrapped(erows), colWidths=[42 * mm, 28 * mm, 28 * mm, 32 * mm, 24 * mm, 24 * mm], repeatRows=1)
        et.setStyle(table_style(7))
        et.setStyle(TableStyle([("ALIGN", (1, 1), (-1, -1), "RIGHT")]))
        story += [Paragraph("Book size", styles["Heading3"]), et, Spacer(1, 2 * mm)]

    for fn, caption in [
        ("equity_curves.png", "Portfolio value over the five days"),
        ("drawdowns.png", "Loss from the peak"),
        ("regime_performance.png", "Result by market type"),
    ]:
        path = OUT / fn
        if path.exists():
            story += [
                Paragraph(caption, styles["Heading3"]),
                Image(str(path), width=165 * mm, height=82 * mm),
                Spacer(1, 2 * mm),
            ]

    story += [
        Paragraph("6. Limits of this study", styles["Section"]),
        ListFlowable(
            [
                ListItem(Paragraph(item, styles["Small"]), leftIndent=8, bulletColor=HEADER_BG)
                for item in limitations(quality)
            ],
            bulletType="bullet",
            start="•",
            leftIndent=12,
            bulletFontSize=8,
        ),
    ]

    if write_pdf:
        doc = SimpleDocTemplate(
            str(OUT / "research_report.pdf"),
            pagesize=A4,
            rightMargin=16 * mm,
            leftMargin=16 * mm,
            topMargin=14 * mm,
            bottomMargin=14 * mm,
        )
        doc.build(story)
        print("Wrote", OUT / "research_report.pdf")
    if write_docx_file:
        write_docx(qrows, mrows, drows, rrows, erows, summary, price_vals, quality)


if __name__ == "__main__":
    build_report()
