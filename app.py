"""Payroll Release Guard - the review portal."""
import html
import json
import sqlite3
import time
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

import evaluate
import explainer
import extract
import guard
import store

NAVY, SKY, SKY2, SKY3 = "#031D63", "#BFE0FF", "#EEF5FD", "#8DB4E2"
INK, MUTED, LINE = "#1A1F2B", "#5C6B80", "#DCE5F0"
DANGER, SUCCESS, WARN = "#C9252D", "#12805C", "#E6B000"     # red = danger, one green = success, yellow = warning dot

st.set_page_config(page_title="Payroll Release Guard", page_icon=":material/shield:", layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:ital,wght@0,100..900;1,100..900&display=swap');
:root { --navy:#031D63; --sky:#BFE0FF; --sky2:#EEF5FD; --sky3:#8DB4E2; --bg:#F4F8FD; --ink:#1A1F2B; --muted:#5C6B80;
  --line:#DCE5F0; --danger:#C9252D; --danger-tint:#FCEDEE; --success:#12805C; --success-tint:#E7F4EE; --warn:#E6B000; }
html, body, .stApp, .stApp *:not([data-testid="stIconMaterial"]):not(.material-symbols-rounded):not(code) {
  font-family: 'Archivo', 'Segoe UI', sans-serif !important; }
.stApp { background: var(--bg); }
.block-container { padding-top: 3.4rem; max-width: 1260px; }
h1, h2, h3, h4 { color: var(--ink); letter-spacing: -0.01em; }
.ico { width: 1em; height: 1em; vertical-align: -0.14em; stroke: currentColor; fill: none; stroke-width: 2;
  stroke-linecap: round; stroke-linejoin: round; flex: none; }
.ok { color: var(--success); } .bad { color: var(--danger); }

/* page header */
.ph { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin: 4px 0 16px 0; }
.ph h1 { font-size: 30px; font-weight: 700; margin: 0; padding: 0; }
.ph .meta { color: var(--muted); font-size: 15px; }
.sec { font-weight: 700; font-size: 19px; margin: 22px 0 10px 0; color: var(--ink); }

/* cards */
.card { background: #fff; border: 1px solid var(--line); border-radius: 8px; box-shadow: 0 1px 2px rgba(3,29,99,.04); }
.kpis { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 12px; margin: 0 0 16px 0; }
.kpi { padding: 16px 18px; }
.kpi .label { font-size: 14px; color: var(--muted); font-weight: 500; }
.kpi .value { font-size: 30px; font-weight: 700; color: var(--ink); line-height: 1.2; margin-top: 4px; }
.kpi .value.ok { color: var(--success); } .kpi .value.bad { color: var(--danger); }
.kpi .sub { font-size: 13px; color: var(--muted); margin-top: 2px; }
@media (max-width: 900px) { .kpis { grid-template-columns: repeat(2, minmax(0,1fr)); } }
.pill { display: inline-flex; align-items: center; border-radius: 999px; padding: 5px 13px; font-size: 13px;
  font-weight: 700; color: #fff; letter-spacing: .1px; }
.dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; flex: none; }

/* payroll cards */
div[class*="st-key-pr-"] { background: #fff; border: 1px solid var(--line) !important; border-radius: 8px !important;
  box-shadow: 0 1px 2px rgba(3,29,99,.04); padding: 16px 18px 8px 18px; }
.pr-title { font-weight: 700; font-size: 19px; margin: 12px 0 2px 0; color: var(--ink); }
.pr-meta { color: var(--muted); font-size: 14px; margin-bottom: 12px; }
.story { background: var(--sky2); border-radius: 6px; padding: 9px 12px; font-size: 14px; line-height: 1.45;
         color: var(--ink); margin-bottom: 14px; min-height: 98px; }
.story b { color: var(--navy); }
.story.wide { min-height: 0; margin: -4px 0 14px 0; font-size: 15px; }
.intro { color: var(--muted); font-size: 15px; margin: -6px 0 16px 0; }
.pr-row { display: flex; gap: 34px; margin-bottom: 10px; }
.pr-num { font-weight: 700; font-size: 24px; color: var(--ink); line-height: 1.1; display: flex; align-items: center; gap: 6px; }
.pr-lbl { color: var(--muted); font-size: 13px; margin-top: 2px; }
.pr-num.ok { color: var(--success); } .pr-num.bad { color: var(--danger); }

/* payroll page */
.verdict { display: flex; align-items: center; gap: 14px; padding: 14px 18px; margin: 0 0 14px 0; border-left: 4px solid var(--c); }
.verdict .ico { width: 28px; height: 28px; color: var(--c); }
.verdict .t { font-size: 20px; font-weight: 700; color: var(--ink); }
.verdict .s { font-size: 14px; color: var(--muted); }
.flow { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 12px; margin-bottom: 8px; }
.step { padding: 12px 16px; border-left: 3px solid var(--c, var(--line)); }
.step .w { color: var(--muted); font-size: 13px; }
.step .v { font-weight: 700; font-size: 18px; color: var(--ink); display: flex; align-items: center; gap: 6px; }
.step .x { color: var(--muted); font-size: 13px; }
.finding { display: flex; align-items: center; gap: 10px; border-radius: 8px; padding: 10px 14px; margin: 6px 0;
  font-size: 15px; background: #fff; color: var(--ink); border: 1px solid var(--line); }
.finding .ico { width: 18px; height: 18px; }
.finding.critical { background: var(--danger-tint); border-color: #F2C4C7; } .finding.critical .ico { color: var(--danger); }
.finding.warning .ico { color: var(--warn); }
.finding.good { background: var(--success-tint); border-color: #BFE3D2; } .finding.good .ico { color: var(--success); }
div[class*="st-key-held-"] { background: #fff; border: 1px solid var(--line) !important; border-left: 4px solid var(--danger) !important;
  border-radius: 8px !important; padding: 8px 12px 4px 12px; }
div[class*="st-key-held-done"] { border-left-color: var(--success) !important; }
.h-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.h-ben { font-weight: 700; font-size: 18px; color: var(--ink); }
.risk { font-weight: 700; font-size: 13px; color: var(--danger); }
.tag { display: inline-flex; align-items: center; gap: 5px; background: var(--sky2); color: var(--ink); border-radius: 6px;
  padding: 3px 9px; font-size: 12.5px; }
.amt { font-weight: 700; font-size: 22px; color: var(--danger); }
.exp { color: var(--muted); font-size: 14px; }
.reason { font-size: 15.5px; line-height: 1.5; margin: 4px 0; color: var(--ink); }
.done { display: inline-flex; align-items: center; gap: 6px; color: var(--success); font-weight: 700; font-size: 14px; }

/* tables: Bootstrap-style striped */
.tbl-wrap { border: 1px solid var(--line); border-radius: 8px; overflow: auto; background: #fff; }
.tbl { width: 100%; border-collapse: collapse; font-size: 15.5px; }
.tbl th { background: var(--sky2); color: var(--navy); font-weight: 700; text-align: left; padding: 12px 14px; position: sticky; top: 0;
  border-bottom: 2px solid var(--line); white-space: nowrap; z-index: 1; }
.tbl td { padding: 11px 14px; border-top: 1px solid #E8EEF6; color: var(--ink); vertical-align: top; }
.tbl tbody tr:nth-child(odd) td { background: #FFFFFF; }
.tbl tbody tr:nth-child(even) td { background: #F4F8FD; }
.tbl tbody tr:hover td { background: #E6F0FB; }
.tbl .num { text-align: right; font-variant-numeric: tabular-nums; }
.tbl td:first-child { white-space: nowrap; }
.tbl .st { display: inline-flex; align-items: center; gap: 7px; font-weight: 600; white-space: nowrap; }

/* sidebar */
section[data-testid="stSidebar"] { background: var(--navy); }
section[data-testid="stSidebar"] * { color: #fff; }
section[data-testid="stSidebar"] input { color: var(--ink) !important; }
section[data-testid="stSidebar"] .stButton button { background: rgba(191,224,255,.10); border: 1px solid rgba(191,224,255,.3); border-radius: 6px; }
section[data-testid="stSidebar"] hr { border-color: rgba(191,224,255,.18); }
.brand { display: flex; flex-direction: column; align-items: center; text-align: center; margin: -8px 0 22px 0; }
.brand .ico { width: 200px; height: 200px; color: #fff; stroke-width: 1.2;
              filter: drop-shadow(0 0 28px rgba(191,224,255,.35)); }
.brand .name { font-weight: 700; font-size: 22px; line-height: 1.2; margin-top: 10px; letter-spacing: .2px; }
.conn { background: rgba(191,224,255,.07); border: 1px solid rgba(191,224,255,.18); border-radius: 8px; margin-bottom: 14px; }
.conn-row { display: flex; align-items: center; gap: 12px; padding: 12px 14px; }
.conn-row + .conn-row { border-top: 1px solid rgba(191,224,255,.14); }
.conn-row .ico { width: 22px; height: 22px; color: var(--sky); flex: none; }
.conn-row .txt { flex: 1; font-size: 15px; font-weight: 600; line-height: 1.25; }
.conn-row .top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.conn-row .txt small { display: block; font-weight: 400; color: var(--sky); font-size: 12.5px; margin-top: 4px; }
.state { display: inline-flex; align-items: center; padding: 3px 10px; border-radius: 999px;
         font-size: 12px; font-weight: 700; color: #fff !important; white-space: nowrap; }
.state.on { background: var(--success); } .state.off { background: var(--danger); }
.side-label { font-size: 13px; color: var(--sky) !important; font-weight: 600; margin: 4px 0 4px 0; }
.who { font-size: 21px; font-weight: 700; line-height: 1.2; }

/* view switcher and buttons */
div[class*="st-key-view"] { margin-bottom: 6px; }
div[class*="st-key-view"] button { padding: 7px 16px !important; border-color: var(--line) !important; background: #fff; }
div[class*="st-key-view"] button p { font-size: 15px !important; font-weight: 600 !important; }
.stButton button { border-radius: 6px; }

/* data page and accuracy */
.panel { padding: 18px 22px; height: 100%; }
.panel.dark { background: var(--navy); border-color: var(--navy); }
.panel h4 { margin: 0 0 8px 0; font-size: 17px; font-weight: 700; }
.panel.dark h4, .panel.dark li { color: #fff !important; }
.panel ul { list-style: none; padding: 0; margin: 0; }
.panel li { font-size: 15.5px; padding: 7px 0; border-bottom: 1px solid #E8EEF6; color: var(--ink); display: flex; gap: 10px; align-items: center; }
.panel.dark li { border-bottom-color: rgba(191,224,255,.15); }
.panel li:last-child { border-bottom: 0; }
.panel li .ico { color: var(--success); } .panel.dark li .ico { color: var(--sky); }
.vs { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; }
.vscard { padding: 18px 22px; }
.vscard.g { background: var(--navy); border-color: var(--navy); }
.vscard h4 { margin: 0 0 6px 0; font-size: 17px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
.vscard.g h4 { color: #fff !important; }
.vsrow { display: flex; justify-content: space-between; align-items: baseline; padding: 9px 0; border-bottom: 1px solid rgba(141,180,226,.25); }
.vsrow:last-child { border-bottom: 0; }
.vsrow .l { font-size: 15px; } .vsrow .n { font-weight: 700; font-size: 26px; }
.vscard.g .vsrow .l { color: var(--sky); } .vscard.g .vsrow .n { color: #fff; }
.vscard .vsrow .l { color: var(--muted); } .vscard .vsrow .n { color: var(--ink); }
.foot { color: var(--muted); font-size: 13px; margin-top: 10px; }

/* engine animation */
.engine-wrap { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 18px; }
.engine-full { position: fixed; inset: 0; z-index: 999999; background: radial-gradient(circle at 50% 42%, #0B2F86 0%, #031D63 55%, #020F38 100%); }
.engine-inline { background: radial-gradient(circle at 50% 45%, #0B2F86 0%, #031D63 70%); border-radius: 8px; padding: 22px 10px; }
.engine-title { color: #fff; font-weight: 700; letter-spacing: .32em; font-size: 22px; text-align: center; }
.engine-sub { color: var(--sky); font-size: 14px; letter-spacing: .18em; text-transform: uppercase; text-align: center; }
.engine-sub span { animation: blink 1.4s infinite; }
.engine-sub span:nth-child(2) { animation-delay: .2s; } .engine-sub span:nth-child(3) { animation-delay: .4s; }
.engine-bar { width: 260px; height: 4px; border-radius: 4px; background: rgba(191,224,255,.18); overflow: hidden; }
.engine-bar div { width: 40%; height: 100%; background: linear-gradient(90deg, transparent, #BFE0FF, #fff, transparent);
  animation: sweep 1.3s ease-in-out infinite; }
.rot { transform-box: fill-box; transform-origin: center; }
.r1 { animation: spin 14s linear infinite; } .r2 { animation: spin 6s linear infinite reverse; }
.r3 { animation: spin 3.2s linear infinite; } .r4 { animation: spin 9s linear infinite reverse; }
.o1 { animation: spin 4s linear infinite; transform-origin: 200px 200px; }
.o2 { animation: spin 7s linear infinite reverse; transform-origin: 200px 200px; }
.o3 { animation: spin 11s linear infinite; transform-origin: 200px 200px; }
.scan { animation: spin 2.4s linear infinite; transform-origin: 200px 200px; }
.core { animation: pulse 1.6s ease-in-out infinite; transform-box: fill-box; transform-origin: center; }
.dash { animation: dashmove 2s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes pulse { 0%,100% { transform: scale(.86); opacity: .85; } 50% { transform: scale(1.08); opacity: 1; } }
@keyframes dashmove { to { stroke-dashoffset: -60; } }
@keyframes sweep { 0% { transform: translateX(-110%); } 100% { transform: translateX(260%); } }
@keyframes blink { 0%,100% { opacity: .2; } 50% { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .rot, .o1, .o2, .o3, .scan, .core, .dash, .engine-bar div { animation: none; } }
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------ monochrome icons (inherit the text colour)
_PATHS = {
    "db": '<ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/><path d="M4.5 5.5v13c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-13"/><path d="M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8"/>',
    "chip": '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9.5 9.5h5v5h-5z"/><path d="M9 2.5V6M15 2.5V6M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8.5-8 9-4.5-.5-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "check-circle": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "alert": '<path d="M12 3l9.5 17h-19z"/><path d="M12 10v4.5M12 17.5v.01"/>',
    "stop": '<path d="M8 3h8l5 5v8l-5 5H8l-5-5V8z"/><path d="M12 8v5M12 16v.01"/>',
    "id": '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="11" r="2.2"/><path d="M5.8 16c.6-1.6 1.8-2.4 3.2-2.4s2.6.8 3.2 2.4M15 10h3.5M15 13.5h3.5"/>',
}


def icon(name, cls=""):
    return f'<svg class="ico {cls}" viewBox="0 0 24 24">{_PATHS[name]}</svg>'


STORIES = {   # what was planted in each practice payroll (built in scenarios.py)
    "North": "Nothing. A normal month, to show the Guard stays quiet when all is well.",
    "South": "Extra zeros, a tripled payment, 11 people using one phone, 3 people paid into one account, and an account switched just before payday.",
    "East": "The same person approved it twice at 2:46 at night, in under 30 seconds, plus one KES 6,000,000 payment.",
}


def story(title):
    region = (title or "").split("· ")[-1].split(" ")[0]
    return STORIES.get(region) if (title or "").startswith("October 2026") else None


def pill(label, colour):
    """A solid status pill: green = go, yellow = careful, red = stop."""
    ink = "#1A1F2B" if colour == WARN else "#fff"
    return f'<span class="pill" style="background:{colour};color:{ink}">{label}</span>'


def dot(color):
    return f'<span class="dot" style="background:{color}"></span>'


def table(df, numeric=(), height=None, status=None):
    """A striped HTML table with readable text. status: column whose values are (label, colour) pairs."""
    head = "".join(f'<th class="{"num" if c in numeric else ""}">{html.escape(str(c))}</th>' for c in df.columns)
    body = []
    for row in df.itertuples(index=False):
        cells = []
        for c, v in zip(df.columns, row):
            if c == status:
                label, colour = v
                cells.append(f'<td><span class="st">{dot(colour)}{html.escape(label)}</span></td>')
            else:
                text = f"{v:,.0f}" if c in numeric and isinstance(v, (int, float)) and v == v else html.escape(str(v))
                cells.append(f'<td class="{"num" if c in numeric else ""}">{text}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    style = f' style="max-height:{height}px"' if height else ""
    st.markdown(f'<div class="tbl-wrap"{style}><table class="tbl"><thead><tr>{head}</tr></thead>'
                f'<tbody>{"".join(body)}</tbody></table></div>', unsafe_allow_html=True)


def styled(chart):
    return (chart.configure(font="Archivo").configure_axis(labelFontSize=13, labelColor=MUTED, gridColor="#E8EEF6",
                                                           domainColor=LINE, tickColor=LINE)
            .configure_legend(labelFontSize=13, labelColor=INK).configure_view(stroke=None))


# ------------------------------------------------------------------ the engine animation
def engine(caption="Starting the engine", full=True):
    ticks = "".join(f'<line x1="200" y1="28" x2="200" y2="{40 if i % 5 else 48}" stroke="#BFE0FF" stroke-width="{1.4 if i % 5 else 3}" '
                    f'opacity="{.45 if i % 5 else .9}" transform="rotate({i * 6} 200 200)"/>' for i in range(60))
    spokes = "".join(f'<line x1="200" y1="200" x2="200" y2="118" stroke="#BFE0FF" stroke-width="3" opacity=".5" '
                     f'transform="rotate({i * 45} 200 200)"/>' for i in range(8))
    size = 380 if full else 170
    svg = f"""
<svg width="{size}" height="{size}" viewBox="0 0 400 400" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <radialGradient id="cg" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#FFFFFF"/><stop offset=".45" stop-color="#BFE0FF"/>
      <stop offset="1" stop-color="#2F6BFF" stop-opacity="0"/></radialGradient>
    <linearGradient id="sg" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#BFE0FF" stop-opacity="0"/>
      <stop offset="1" stop-color="#BFE0FF" stop-opacity=".55"/></linearGradient>
    <filter id="glow"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  </defs>
  <g class="rot r1">{ticks}</g>
  <circle cx="200" cy="200" r="150" fill="none" stroke="#BFE0FF" stroke-width="1.5" stroke-dasharray="4 10" class="dash" opacity=".7"/>
  <g class="scan"><path d="M200 200 L200 52 A148 148 0 0 1 328 126 Z" fill="url(#sg)" opacity=".55"/></g>
  <circle cx="200" cy="200" r="122" fill="none" stroke="#7FA8E0" stroke-width="20" stroke-dasharray="14 9" class="rot r2" filter="url(#glow)"/>
  <circle cx="200" cy="200" r="122" fill="none" stroke="#031D63" stroke-width="8"/>
  <g class="rot r3"><circle cx="200" cy="200" r="92" fill="none" stroke="#FFFFFF" stroke-width="5" stroke-dasharray="58 24" opacity=".9"/></g>
  <g class="rot r4">{spokes}<circle cx="200" cy="200" r="72" fill="none" stroke="#BFE0FF" stroke-width="2" stroke-dasharray="2 6"/></g>
  <circle cx="200" cy="200" r="58" fill="#031D63" stroke="#BFE0FF" stroke-width="2"/>
  <circle cx="200" cy="200" r="52" fill="url(#cg)" class="core" filter="url(#glow)"/>
  <path d="M200 176 l20 7.5 v14 c0 12 -8.5 20 -20 22 c-11.5 -2 -20 -10 -20 -22 v-14 z" fill="#031D63" opacity=".9"/>
  <path d="M191 199 l6.5 6.5 l12 -13" fill="none" stroke="#BFE0FF" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
  <g class="o1"><circle cx="200" cy="64" r="6" fill="#FFFFFF" filter="url(#glow)"/></g>
  <g class="o2"><circle cx="338" cy="200" r="5" fill="#BFE0FF" filter="url(#glow)"/><circle cx="62" cy="200" r="3.5" fill="#BFE0FF"/></g>
  <g class="o3"><circle cx="200" cy="350" r="4.5" fill="#FFFFFF"/><circle cx="94" cy="94" r="3" fill="#BFE0FF"/></g>
</svg>"""
    words = "".join("<span>.</span>" for _ in range(3))
    cls = "engine-wrap engine-full" if full else "engine-wrap engine-inline"
    title = '<div class="engine-title">PAYROLL RELEASE GUARD</div>' if full else ""
    return (f'<div class="{cls}">{svg}{title}<div class="engine-sub">{html.escape(caption)}{words}</div>'
            f'<div class="engine-bar"><div></div></div></div>')


# ------------------------------------------------------------------ data helpers
def q(sql, params=()):
    with store.connect() as con:
        return pd.read_sql_query(sql, con, params=params)


def one(sql, params=()):
    with store.connect() as con:
        return con.execute(sql, params).fetchone()


def money(cur, x):
    x = float(x or 0)
    if abs(x) >= 1e6:
        return f"{cur} {x / 1e6:,.1f}M" if x < 1e9 else f"{cur} {x / 1e9:,.2f}B"
    return f"{cur} {x:,.0f}"


def full_money(cur, x):
    return f"{cur} {float(x or 0):,.0f}"


def nice_time(s, fmt="%d %b %H:%M"):
    return datetime.fromisoformat(s).strftime(fmt).lstrip("0") if isinstance(s, str) and s else "-"


def plural(n, word):
    return f"{int(n):,} {word}{'' if int(n) == 1 else 's'}"


def pct(part, whole):
    share = part / max(whole, 1)
    return "<1%" if 0 < share < 0.01 else f"{share:.0%}"


@st.cache_resource(show_spinner=False)
def warm_up():
    store.init()
    with store.connect() as con:
        guard.global_context(con)
    return True


@st.cache_data(ttl=300, show_spinner=False)
def db_online():
    return extract.reachable()


@st.cache_data(ttl=30, show_spinner=False)
def ai_online():
    return explainer.ready()


def latest_checks():
    return q("""SELECT c.*, r.payroll_number, r.title, r.project_id, r.currency, r.total_amount, r.created_on,
                       r.source, r.stage, p.name AS project
                  FROM checks c JOIN payrolls r USING (payroll_id) LEFT JOIN projects p USING (project_id)
                 WHERE c.check_id IN (SELECT MAX(check_id) FROM checks GROUP BY payroll_id)""")


def payroll_decision(pid):
    return one("SELECT decision, reviewer, ts FROM decisions WHERE payroll_id=? AND payment_id IS NULL "
               "ORDER BY id DESC LIMIT 1", (pid,))


def line_decisions(check_id):
    d = q("SELECT payment_id, decision, reviewer, ts FROM decisions WHERE check_id=? AND payment_id IS NOT NULL "
          "ORDER BY id", (check_id,))
    return {int(r.payment_id): (r.decision, r.reviewer, r.ts) for r in d.itertuples()}


def decide(pid, check_id, payment_id, decision, reviewer, detail):
    with store.connect() as con:
        con.execute("INSERT INTO decisions (payroll_id, check_id, payment_id, decision, reviewer, ts) VALUES (?,?,?,?,?,?)",
                    (pid, check_id, payment_id, decision, reviewer, store.now()))
        store.audit(con, decision, f"{detail} - by {reviewer}")


def critical(approval):
    return [t for s, t in approval if s == "critical"]


def verdict_text(row, approval):
    """(title, short line, colour, icon)"""
    if row["verdict"] == "red" and critical(approval):
        return "Hold: approval problem", "Needs a genuine second approval", DANGER, "stop"
    if row["verdict"] == "red":
        return "Hold", "Most of the money is at risk", DANGER, "stop"
    if row["verdict"] == "amber" and row["held_lines"]:
        return "Release with holds", f"{plural(row['held_lines'], 'payment')} held", WARN, "alert"
    if row["verdict"] == "amber":
        return "Release · check approval", "Payments as expected", WARN, "alert"
    return "Safe to release", "Every payment as expected", SUCCESS, "check-circle"


def run_with_engine(caption, fn):
    box = st.empty()
    box.markdown(engine(caption, full=False), unsafe_allow_html=True)
    try:
        return fn()
    finally:
        box.empty()


@st.cache_data(show_spinner=False)
def quality(stamp):
    saved = one("SELECT value FROM sync_info WHERE key = 'quality'")
    if saved:
        return json.loads(saved[0])
    with store.connect() as con:
        return store.quality_stats(con)


@st.cache_data(show_spinner=False)
def approver_rows(stamp):
    pr = q("""SELECT r.payroll_id, r.first_by, r.first_on, r.second_by, r.second_on, r.created_on, COUNT(p.payment_id) AS n
                FROM payrolls r LEFT JOIN payments p USING (payroll_id) GROUP BY r.payroll_id""")
    rows = []
    for r in pr.itertuples():
        for who, start, end, level in ((r.first_by, r.created_on, r.first_on, 1), (r.second_by, r.first_on, r.second_on, 2)):
            if isinstance(who, str) and isinstance(start, str) and isinstance(end, str):
                secs = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
                hour = datetime.fromisoformat(end).hour
                rows.append(dict(who=who, per_k=secs / max(r.n, 1) * 1000, fast=secs < 30 + 0.1 * r.n,
                                 odd=not (7 <= hour < 19), same=level == 2 and r.first_by == r.second_by))
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def phone_groups(stamp):
    return q("""SELECT CASE WHEN n >= 11 THEN '11+' WHEN n >= 6 THEN '6-10' WHEN n >= 4 THEN '4-5' WHEN n >= 2 THEN '2-3' END
                       AS "People", COUNT(*) AS Phones
                  FROM (SELECT phone, COUNT(DISTINCT ben) n FROM beneficiaries WHERE source='live' AND phone IS NOT NULL
                        GROUP BY phone) WHERE n >= 2 GROUP BY 1""")


# ------------------------------------------------------------------ start-up
splash = st.empty()                    # a permanent first slot, so later runs never shift the layout
if "booted" not in st.session_state:
    splash.markdown(engine("Starting the engine"), unsafe_allow_html=True)
    t0 = time.time()
    warm_up()
    quality(dict(q("SELECT key, value FROM sync_info").values).get("last_sync"))
    time.sleep(max(0.0, 2.6 - (time.time() - t0)))          # long enough to be seen, never longer than needed
    splash.empty()
    st.session_state["booted"] = True
else:
    warm_up()
if "toast" in st.session_state:
    st.toast(st.session_state.pop("toast"), icon=":material/check_circle:")
sync = dict(q("SELECT key, value FROM sync_info").values) if one("SELECT COUNT(*) FROM sync_info")[0] else {}

with st.sidebar:
    logo = icon("shield").replace('viewBox="0 0 24 24"', 'viewBox="2.6 2.4 18.8 19.2"')
    st.markdown(f'<div class="brand">{logo}<div class="name">Payroll Release Guard</div></div>',
                unsafe_allow_html=True)
    ai_ok = ai_online()
    state = lambda ok: f'<span class="state {"on" if ok else "off"}">{"Online" if ok else "Offline"}</span>'
    db_ok = db_online()
    st.markdown(
        f'<div class="conn"><div class="conn-row">{icon("db")}<div class="txt"><div class="top">Database{state(db_ok)}</div>'
        f'<small>{"Copied" if db_ok else "Using copy from"} {nice_time(sync.get("last_sync"))}</small></div></div>'
        f'<div class="conn-row">{icon("chip")}<div class="txt"><div class="top">Private AI{state(ai_ok)}</div>'
        f'<small>Runs inside the bank</small></div></div></div>', unsafe_allow_html=True)
    if st.button("Refresh data", icon=":material/sync:", width="stretch"):
        try:
            info = run_with_engine("Copying live data", lambda: extract.run(lambda m: None))
        except extract.AlreadyRefreshing:
            st.session_state["toast"] = "Already refreshing"
        except sqlite3.OperationalError:
            st.session_state["toast"] = "Local copy busy · try again in a minute"
        except Exception as err:                       # the live database or network is unavailable
            st.session_state["toast"] = f"Live database unavailable · using the saved copy ({type(err).__name__})"
        else:
            st.session_state["toast"] = f"{info['payments']:,} payments copied in {info['seconds']}s"
        st.rerun()
    st.divider()
    reviewer = "Head of Payments"
    st.markdown(f'<div class="side-label">Reviewer</div><div class="who">{reviewer}</div>', unsafe_allow_html=True)


def header(title, meta=""):
    st.markdown(f'<div class="ph"><h1>{html.escape(title)}</h1><div class="meta">{html.escape(meta)}</div></div>',
                unsafe_allow_html=True)


# ------------------------------------------------------------------ payment popup
@st.dialog("Payment", width="large")
def payment_dialog(line, meta):
    reasons = json.loads(line["reasons_json"])
    cur = meta["currency"]
    exp = line["expected"]
    st.markdown(f'<div class="h-head"><span class="h-ben">{line["ben"]}</span></div>'
                f'<div style="margin:8px 0"><span class="amt">{full_money(cur, line["amount"])}</span> '
                f'<span class="exp">{"· expected " + full_money(cur, exp) if exp and exp == exp else ""}</span></div>'
                + "".join(f'<div class="reason">{html.escape(r["text"])}</div>' for r in reasons if r["check"] != "Context"),
                unsafe_allow_html=True)
    hist = q("""SELECT r.created_on, p.amount FROM payments p JOIN payrolls r USING (payroll_id)
                 WHERE p.ben = ? AND r.stage = 'paid' AND r.created_on < ? ORDER BY r.created_on""",
             (line["ben"], meta["created_on"]))
    hist["When"] = [nice_time(t, "%b %Y") for t in hist["created_on"]]
    hist["Which"] = "Past"
    chart_df = pd.concat([hist[["When", "amount", "Which"]],
                          pd.DataFrame([{"When": "Now", "amount": line["amount"], "Which": "This payment"}])], ignore_index=True)
    st.altair_chart(styled(alt.Chart(chart_df).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("When:N", sort=list(chart_df["When"]), title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("amount:Q", title=None, axis=alt.Axis(format=",.0f")),
        color=alt.Color("Which:N", scale=alt.Scale(domain=["Past", "This payment"], range=[SKY3, DANGER]),
                        legend=alt.Legend(orient="bottom", title=None)),
        tooltip=["When", alt.Tooltip("amount:Q", format=",.0f")]).properties(height=210)), width="stretch")
    phone = next((r.get("phone") for r in reasons if r.get("phone")), None)
    if phone:
        linked = q("""SELECT b.ben AS "Beneficiary", COALESCE(p.amount, 0) AS "Amount",
                             CASE b.id_checked WHEN 1 THEN 'Yes' ELSE 'No' END AS "ID checked"
                        FROM beneficiaries b LEFT JOIN payments p ON p.ben = b.ben AND p.payroll_id = ?
                       WHERE b.phone = ? GROUP BY b.ben""", (int(meta["payroll_id"]), phone))
        st.markdown(f'<div class="sec">{len(linked)} people · one phone</div>', unsafe_allow_html=True)
        table(linked, numeric=("Amount",), height=300)
    key = f"ai-{line['payment_id']}"
    if st.button("Explain", icon=":material/auto_awesome:", key=f"btn-{key}"):
        st.session_state[key] = run_with_engine("Private AI writing", lambda: explainer.explain(line["ben"], reasons))
    if key in st.session_state:
        st.info(st.session_state[key][0])


def held_card(line, meta, check_id, dec, group=None):
    cur = meta["currency"]
    done = dec.get(int(line["payment_id"]))
    reasons = json.loads(line["reasons_json"])
    with st.container(key=f"held-{'done-' if done else ''}{line['payment_id']}"):
        left, right = st.columns([5, 1.3], vertical_alignment="center")
        with left:
            exp = line["expected"]
            title = f'{len(group)} people · one phone' if group is not None else line["ben"]
            amount = group["amount"].sum() if group is not None else line["amount"]
            no_id = any(r["check"] == "Context" for r in reasons)
            st.markdown(
                f'<div class="h-head"><span class="h-ben">{title}</span>'
                + "".join(f'<span class="tag">{c}</span>' for c in dict.fromkeys(r["check"] for r in reasons if r["check"] != "Context"))
                + (f'<span class="tag">{icon("id")} ID not verified</span>' if no_id else "")
                + (f'<span class="done">{icon("check")} {done[0]}</span>' if done else "")
                + f'</div><div><span class="amt">{full_money(cur, amount)}</span> <span class="exp">'
                + (f'· expected {full_money(cur, exp)}' if exp and exp == exp and group is None else
                   f'· {len(group)} payments' if group is not None else '')
                + '</span></div>'
                + "".join(f'<div class="reason">{html.escape(r["text"])}</div>' for r in reasons if r["check"] != "Context"),
                unsafe_allow_html=True)
        with right:
            if not done and meta["stage"] == "pending":
                rows = group if group is not None else pd.DataFrame([line])
                label = " all" if group is not None else ""
                where = meta["title"] or meta["payroll_number"]
                if st.button(f"Release{label}", icon=":material/check:", key=f"rel-{line['payment_id']}", width="stretch"):
                    for r in rows.itertuples():
                        decide(int(meta["payroll_id"]), check_id, int(r.payment_id), "Released", reviewer,
                               f"{r.ben} ({full_money(cur, r.amount)}) in {where} released after review")
                    st.session_state["toast"] = "Released"
                    st.rerun()
                if st.button(f"Cancel{label}", icon=":material/close:", key=f"can-{line['payment_id']}", width="stretch"):
                    for r in rows.itertuples():
                        decide(int(meta["payroll_id"]), check_id, int(r.payment_id), "Cancelled", reviewer,
                               f"{r.ben} ({full_money(cur, r.amount)}) in {where} cancelled")
                    st.session_state["toast"] = "Cancelled"
                    st.rerun()
            if st.button("Details", icon=":material/search:", key=f"det-{line['payment_id']}", width="stretch"):
                payment_dialog(line, meta)


def kpi(label, value, sub="", tone=""):
    return (f'<div class="card kpi"><div class="label">{label}</div><div class="value {tone}">{value}</div>'
            + (f'<div class="sub">{sub}</div>' if sub else "") + "</div>")


def show_payroll(pid):
    meta = q("SELECT r.*, p.name AS project FROM payrolls r LEFT JOIN projects p USING (project_id) WHERE payroll_id=?",
             (pid,)).iloc[0]
    meta = meta.astype(object).where(meta.notna(), None)      # missing values become None, not NaN
    if st.button("Payrolls", icon=":material/arrow_back:"):
        st.session_state.pop("open", None)
        st.rerun()
    chk = q("SELECT * FROM checks WHERE payroll_id=? ORDER BY check_id DESC LIMIT 1", (pid,))
    if chk.empty:
        run_with_engine("Checking every payment", lambda: guard.check(pid))
        st.rerun()
    c = chk.iloc[0]
    approval = json.loads(c["approval_json"])
    cur = meta["currency"]
    title, sub, colour, ic = verdict_text(c, approval)
    header(meta["title"] or f"Payroll {meta['payroll_number']}",
           f"{int(c['lines']):,} payments · {full_money(cur, c['held_amount'] + c['safe_amount'])}")
    if story(meta["title"]):
        st.markdown(f'<div class="story wide"><b>Practice payroll. Planted:</b> {story(meta["title"])}</div>',
                    unsafe_allow_html=True)
    st.markdown(f'<div class="card verdict" style="--c:{colour}">{icon(ic)}<div><div class="t">{title}</div>'
                f'<div class="s">{sub}</div></div></div>'
                '<div class="kpis" style="grid-template-columns: repeat(2, minmax(0,1fr))">'
                + kpi("Held", money(cur, c["held_amount"]), plural(c["held_lines"], "payment"), "bad" if c["held_lines"] else "ok")
                + kpi("Safe to release", money(cur, c["safe_amount"]), plural(c["lines"] - c["held_lines"], "payment"), "ok")
                + "</div>", unsafe_allow_html=True)

    def gap(a, b):
        if not (isinstance(a, str) and isinstance(b, str)):
            return "-"
        s = (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()
        return (f"{s:,.0f} seconds later" if s < 120 else f"{s / 60:,.0f} minutes later" if s < 7200
                else f"{s / 3600:,.0f} hours later" if s < 172800 else f"{s / 86400:,.0f} days later")
    texts = " ".join(t for _, t in approval)
    same = meta["first_by"] and meta["first_by"] == meta["second_by"]
    bad1 = "First approval" in texts
    bad2 = same or not meta["second_on"] or "Second approval" in texts

    def step(label, who, when, bad, show_ok=True):
        mark = icon("x", "bad") if bad else icon("check", "ok") if show_ok else ""
        return (f'<div class="card step" style="--c:{DANGER if bad else SUCCESS if show_ok else LINE}"><div class="w">{label}</div>'
                f'<div class="v">{who or "missing"} {mark}</div><div class="x">{when}</div></div>')
    st.markdown('<div class="sec">Approval</div><div class="flow">'
                + step("Created", meta["created_by"], nice_time(meta["created_on"]), False, show_ok=False)
                + step("First approval", meta["first_by"], gap(meta["created_on"], meta["first_on"]), bad1)
                + step("Second approval", meta["second_by"], gap(meta["first_on"], meta["second_on"]), bad2) + '</div>'
                + ("".join(f'<div class="finding {sev}">{icon("stop") if sev == "critical" else icon("alert")}{html.escape(t)}</div>'
                           for sev, t in approval) if approval else
                   f'<div class="finding good">{icon("check-circle")}Two different people approved it, in working hours</div>'),
                unsafe_allow_html=True)

    dec = payroll_decision(pid)
    if meta["stage"] == "pending":
        st.markdown('<div class="sec">Decision</div>', unsafe_allow_html=True)
        if dec:
            st.markdown(f'<div class="finding good">{icon("check-circle")}{html.escape(dec[0])} · {html.escape(dec[1])} · '
                        f'{nice_time(dec[2], "%H:%M")}</div>', unsafe_allow_html=True)
        else:
            a, b, c3 = st.columns([1.4, 1, 1])
            safe_n = int(c["lines"] - c["held_lines"])
            if critical(approval):
                if a.button("Send back for re-approval", icon=":material/undo:", type="primary", width="stretch"):
                    decide(pid, int(c["check_id"]), None, "Sent back for re-approval", reviewer, f"{meta['title']}: sent back")
                    st.session_state["toast"] = "Sent back · no money moved"
                    st.rerun()
            elif a.button(f"Release {safe_n:,} payments · {money(cur, c['safe_amount'])}", icon=":material/check_circle:",
                          type="primary", width="stretch"):
                decide(pid, int(c["check_id"]), None, f"Released {safe_n:,} safe payments", reviewer,
                       f"{meta['title']}: released {full_money(cur, c['safe_amount'])}; {int(c['held_lines'])} held")
                st.session_state["toast"] = f"{full_money(cur, c['safe_amount'])} released"
                st.rerun()
            if b.button("Hold payroll", icon=":material/pause_circle:", width="stretch"):
                decide(pid, int(c["check_id"]), None, "Held the whole payroll", reviewer, f"{meta['title']}: held")
                st.session_state["toast"] = "Payroll held"
                st.rerun()
            if c3.button("Check again", icon=":material/refresh:", width="stretch"):
                run_with_engine("Checking every payment", lambda: guard.check(pid))
                st.rerun()

    held = q("SELECT * FROM held WHERE check_id=? ORDER BY risk DESC, amount DESC", (int(c["check_id"]),))
    if held.empty:
        return
    st.markdown(f'<div class="sec">Held · {len(held)}</div>', unsafe_allow_html=True)
    dec_lines = line_decisions(int(c["check_id"]))
    held["phone"] = [next((r.get("phone") for r in json.loads(x) if r.get("phone")), None) for x in held["reasons_json"]]
    shown = set()
    for _, line in held.iterrows():
        if isinstance(line["phone"], str):              # only real phone codes are grouped
            if line["phone"] in shown:
                continue
            shown.add(line["phone"])
            group = held[held["phone"] == line["phone"]]
            if len(group) > 1:
                held_card(line, meta, int(c["check_id"]), dec_lines, group)
                continue
        held_card(line, meta, int(c["check_id"]), dec_lines)


# ------------------------------------------------------------------ release desk
def release_desk():
    header("Release desk")
    checks = latest_checks()
    pending = checks[checks["stage"] == "pending"].sort_values("created_on")
    if len(pending):
        st.markdown('<div class="intro">Three practice payrolls for October, made up for this demo. '
                    'Mistakes were planted in them on purpose to show what the Guard catches.</div>', unsafe_allow_html=True)
        cur = pending["currency"].iloc[0]
        st.markdown('<div class="kpis" style="grid-template-columns: repeat(3, minmax(0,1fr))">'
                    + kpi("Waiting to be paid", f"{len(pending)} payrolls", f"{int(pending['lines'].sum()):,} payments")
                    + kpi("Held", money(cur, pending["held_amount"].sum()), plural(pending["held_lines"].sum(), "payment"), "bad")
                    + kpi("Safe to release", money(cur, pending["safe_amount"].sum()),
                          plural(pending["lines"].sum() - pending["held_lines"].sum(), "payment"), "ok")
                    + "</div>", unsafe_allow_html=True)
        cols = st.columns(len(pending))
        for col, (_, r) in zip(cols, pending.iterrows()):
            approval = json.loads(r["approval_json"])
            label, _, colour, _ = verdict_text(r, approval)
            dec = payroll_decision(int(r["payroll_id"]))
            bad_approval = bool(critical(approval))
            tale = f'<div class="story"><b>Planted:</b> {story(r["title"])}</div>' if story(r["title"]) else ""
            with col.container(key=f"pr-{r['payroll_id']}"):
                st.markdown(
                    f'{pill(label, colour)} <span class="tag">Demo</span>'
                    f'<div class="pr-title">{html.escape(r["title"] or "")}</div>'
                    f'<div class="pr-meta">{int(r["lines"]):,} payments · {money(r["currency"], r["held_amount"] + r["safe_amount"])}</div>{tale}'
                    f'<div class="pr-row"><div><div class="pr-num {"bad" if r["held_amount"] else "ok"}">'
                    f'{money(r["currency"], r["held_amount"])}</div><div class="pr-lbl">Held</div></div>'
                    f'<div><div class="pr-num {"bad" if bad_approval else "ok"}">'
                    f'{icon("x") if bad_approval else icon("check-circle")}</div>'
                    f'<div class="pr-lbl">{"Approval problem" if bad_approval else "Approval OK"}</div></div></div>'
                    + (f'<div class="done" style="margin-bottom:8px">{icon("check")} {html.escape(dec[0])}</div>' if dec else ""),
                    unsafe_allow_html=True)
                if st.button("Open", icon=":material/arrow_forward:", key=f"open-{r['payroll_id']}", type="primary", width="stretch"):
                    st.session_state["open"] = int(r["payroll_id"])
                    st.rerun()

    live = checks[checks["source"] == "live"]
    if len(live):
        st.markdown('<div class="sec">Found in your test database</div>', unsafe_allow_html=True)
        a, b = st.columns(2)
        big = live.sort_values("held_amount", ascending=False).iloc[0]
        with a.container(key=f"pr-red-{big['payroll_id']}"):
            n = int(big["held_lines"])
            st.markdown(
                f'{pill("Would have been held", DANGER)}'
                f'<div class="pr-title">Payroll {html.escape(str(big["payroll_number"]))}</div>'
                f'<div class="pr-meta">Already paid · {plural(big["lines"], "payment")}</div>'
                f'<div class="pr-row"><div><div class="pr-num bad">{full_money(big["currency"], big["held_amount"])}</div>'
                f'<div class="pr-lbl">paid to {plural(n, "person")}, about {money(big["currency"], big["held_amount"] / max(n, 1))} each</div>'
                f'</div></div>', unsafe_allow_html=True)
            if st.button("Open", icon=":material/arrow_forward:", key="open-real", type="primary", width="stretch"):
                st.session_state["open"] = int(big["payroll_id"])
                st.rerun()
        kinds = {"The same person": "approved twice by the same person", "There is no second approval": "had no second approval",
                 "The person who created": "approved by the person who created them"}
        counts = {v: 0 for v in kinds.values()}
        for a_json in live["approval_json"]:
            for sev, text in json.loads(a_json):
                for start, words in kinds.items():
                    if sev == "critical" and text.startswith(start):
                        counts[words] += 1
        total = sum(1 for a_json in live["approval_json"] if critical(json.loads(a_json)))
        with b.container(key="pr-red-approvals"):
            st.markdown(
                f'{pill("Approval problems", DANGER)}'
                f'<div class="pr-title">{total} of {len(live)} payrolls</div>'
                f'<div class="pr-meta">Already paid</div>'
                + "".join(f'<div class="reason"><b>{n}</b> {words}</div>' for words, n in counts.items() if n),
                unsafe_allow_html=True)


# ------------------------------------------------------------------ proof
PLAIN = {"One extra zero (x10)": "One extra zero", "Two extra zeros (x100)": "Two extra zeros",
         "Three extra zeros (x1,000)": "Three extra zeros", "Inflated x5": "5 times too much",
         "Inflated x3": "3 times too much", "Doubled (x2)": "Doubled", "Linked identities (one phone)": "Many people, one phone",
         "Shared account (3 people)": "3 people, one bank account", "Account switched before payday": "Account switched before payday"}


def proof():
    header("Proof")
    row = one("SELECT result_json FROM evaluation ORDER BY id DESC LIMIT 1")
    if not row:
        return
    r = json.loads(row[0])
    g, s = r["guard"], r["rule"]
    total, good = r["problems"], r["lines"] - r["problems"]

    def card(title, m, dark):
        return (f'<div class="card vscard{" g" if dark else ""}"><h4>{title}</h4>'
                f'<div class="vsrow"><span class="l">Mistakes caught</span><span class="n">{m["tp"]} of {total}</span></div>'
                f'<div class="vsrow"><span class="l">Good payments wrongly stopped</span><span class="n">{m["fp"]}</span></div></div>')
    st.markdown('<div class="vs">' + card(f'{icon("shield")} Release Guard', g, True)
                + card("Usual check: over 10 times the average", s, False) + "</div>", unsafe_allow_html=True)
    st.markdown('<div class="sec">Caught, by type of mistake</div>', unsafe_allow_html=True)
    bc = pd.DataFrame(r["by_case"])
    bc = bc[bc["kind"] == "problem"].copy()
    bc["Mistake"] = bc["case"].map(PLAIN).fillna(bc["case"])
    prob = bc.melt(id_vars=["Mistake"], value_vars=["guard", "rule"], var_name="Check", value_name="Caught")
    prob["Check"] = prob["Check"].map({"guard": "Release Guard", "rule": "Usual check"})
    st.altair_chart(styled(alt.Chart(prob).mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3).encode(
        y=alt.Y("Mistake:N", title=None, axis=alt.Axis(labelLimit=300), sort=list(bc.sort_values("guard", ascending=False)["Mistake"])),
        yOffset="Check:N", x=alt.X("Caught:Q", title=None, axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
        color=alt.Color("Check:N", scale=alt.Scale(domain=["Release Guard", "Usual check"], range=[NAVY, SKY]),
                        legend=alt.Legend(orient="bottom", title=None)),
        tooltip=["Mistake", "Check", alt.Tooltip("Caught:Q", format=".0%")]).properties(height=340)), width="stretch")
    st.markdown(f'<div class="foot">Tested on {r["trials"]} practice payrolls ({r["lines"]:,} payments) with {total} planted '
                f'mistakes and {good:,} good payments. Doubled payments are let through on purpose: a doubling is often a '
                'genuine raise.</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ history and safety
def history():
    header("History")
    log = q("""SELECT ts, event, detail FROM audit_log
                WHERE event IN ('Released', 'Cancelled', 'Held the whole payroll', 'Sent back for re-approval')
                   OR event LIKE 'Released %' OR event = 'Copied data from the live database'
                ORDER BY id DESC LIMIT 200""")
    if log.empty:
        st.markdown('<div class="card kpi"><div class="label">No decisions yet</div></div>', unsafe_allow_html=True)
        return
    copies = log["event"] == "Copied data from the live database"
    log = pd.concat([log[~copies], log[copies].head(1)]).sort_values("ts", ascending=False)
    who = [d.rsplit(" - by ", 1)[1] if " - by " in d else "System" for d in log["detail"]]
    what = ["Copied the latest payroll data. Names and numbers scrambled." if e == "Copied data from the live database"
            else d.rsplit(" - by ", 1)[0] for e, d in zip(log["event"], log["detail"])]
    table(pd.DataFrame({"When": [nice_time(t, "%d %b %H:%M") for t in log["ts"]], "What happened": what, "By": who}), height=600)


def safety():
    header("Safety")
    a, b = st.columns(2)
    with a:
        st.markdown('<div class="card panel"><h4>Uses</h4><ul>'
                    + "".join(f"<li>{icon('check')}{t}</li>" for t in (
                        "Payment amounts and dates", "Each person's past payments", "Shared phones and bank accounts",
                        "Who approved, and when"))
                    + "</ul></div>", unsafe_allow_html=True)
    with b:
        st.markdown('<div class="card panel dark"><h4>Never uses</h4><ul>'
                    + "".join(f"<li>{icon('x')}{t}</li>" for t in (
                        "Names or addresses", "Readable ID, phone or account numbers", "Fingerprints",
                        "Cards, PINs or passwords"))
                    + "</ul></div>", unsafe_allow_html=True)
    st.markdown(f'<div class="finding good" style="margin-top:14px">{icon("check-circle")}Reads the payroll system, never changes it. '
                'Runs inside the bank. A person makes every decision.</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ layout
VIEWS = {"Release desk": ":material/fact_check:", "Proof": ":material/verified:", "History": ":material/history:",
         "Safety": ":material/lock:"}
view = st.segmented_control("View", list(VIEWS), default="Release desk", key="view", label_visibility="collapsed",
                            format_func=lambda v: f"{VIEWS[v]} {v}") or "Release desk"
if view == "Release desk":
    if "open" in st.session_state:
        show_payroll(st.session_state["open"])
    else:
        release_desk()
elif view == "Proof":
    proof()
elif view == "History":
    history()
else:
    safety()
