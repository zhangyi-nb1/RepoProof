"""Shared visual language for the Product Mode workspace.

The UI stays intentionally local and dependency-light.  Streamlit remains the
rendering shell; this module only supplies presentation helpers and never reads
or changes RepoProof facts.
"""

from __future__ import annotations

from html import escape

import streamlit as st


def apply_product_theme() -> None:
    """Apply the RepoProof Studio product theme once per page render."""
    st.markdown(
        """
        <style>
        :root {
          --rp-ink: #111827;
          --rp-muted: #64748b;
          --rp-line: #e2e8f0;
          --rp-surface: #ffffff;
          --rp-soft: #f6f8fc;
          --rp-blue: #2563eb;
          --rp-violet: #6d5dfc;
          --rp-green: #0f9f6e;
          --rp-amber: #d97706;
          --rp-red: #dc2626;
        }
        [data-testid="stAppViewContainer"] {
          background:
            radial-gradient(circle at 88% 2%, rgba(109, 93, 252, .10), transparent 22rem),
            radial-gradient(circle at 4% 0%, rgba(37, 99, 235, .08), transparent 24rem),
            #f8fafc;
        }
        [data-testid="stMainBlockContainer"] {
          max-width: 1240px;
          padding-top: 2.25rem;
          padding-bottom: 4rem;
        }
        [data-testid="stSidebar"] {
          background: linear-gradient(180deg, #111827 0%, #172554 100%);
          border-right: 0;
        }
        [data-testid="stSidebar"] * { color: #e5e7eb; }
        [data-testid="stSidebar"] [data-testid="stNavSectionHeader"] {
          color: #93c5fd;
          letter-spacing: .08em;
          text-transform: uppercase;
          font-size: .72rem;
        }
        [data-testid="stSidebarNavLink"][aria-current="page"] {
          background: rgba(255,255,255,.12);
          border: 1px solid rgba(255,255,255,.08);
        }
        h1, h2, h3 { color: var(--rp-ink); letter-spacing: -.025em; }
        .rp-hero {
          position: relative;
          overflow: hidden;
          padding: 2.5rem 2.65rem;
          border-radius: 26px;
          color: white;
          background:
            linear-gradient(120deg, rgba(255,255,255,.10), transparent 52%),
            linear-gradient(135deg, #0f172a 0%, #172554 48%, #4338ca 100%);
          box-shadow: 0 24px 60px rgba(30, 41, 59, .18);
          margin: .1rem 0 1.6rem;
        }
        .rp-hero:after {
          content: "";
          position: absolute;
          width: 280px;
          height: 280px;
          right: -100px;
          top: -120px;
          border-radius: 999px;
          border: 54px solid rgba(255,255,255,.07);
        }
        .rp-kicker {
          display: inline-flex;
          align-items: center;
          gap: .45rem;
          padding: .35rem .68rem;
          border: 1px solid rgba(255,255,255,.22);
          background: rgba(255,255,255,.10);
          border-radius: 999px;
          font-size: .78rem;
          font-weight: 700;
          letter-spacing: .06em;
          text-transform: uppercase;
        }
        .rp-hero h1 {
          color: white;
          max-width: 760px;
          font-size: clamp(2.05rem, 4vw, 3.7rem);
          line-height: 1.08;
          margin: 1.05rem 0 .85rem;
        }
        .rp-hero p {
          max-width: 760px;
          color: #cbd5e1;
          font-size: 1.05rem;
          line-height: 1.75;
          margin: 0;
        }
        .rp-card {
          height: 100%;
          padding: 1.15rem 1.2rem;
          border: 1px solid var(--rp-line);
          border-radius: 18px;
          background: rgba(255,255,255,.92);
          box-shadow: 0 10px 32px rgba(15, 23, 42, .045);
        }
        .rp-card-label { color: var(--rp-muted); font-size: .78rem; font-weight: 700; }
        .rp-card-value { color: var(--rp-ink); font-size: 1.65rem; font-weight: 800; margin-top: .15rem; }
        .rp-card-note { color: var(--rp-muted); font-size: .78rem; margin-top: .25rem; }
        .rp-step {
          min-height: 138px;
          padding: 1.15rem;
          border: 1px solid var(--rp-line);
          border-radius: 18px;
          background: white;
        }
        .rp-step-no {
          width: 30px; height: 30px; display: inline-flex; align-items: center;
          justify-content: center; border-radius: 10px; color: white;
          font-weight: 800; background: linear-gradient(135deg, var(--rp-blue), var(--rp-violet));
        }
        .rp-step strong { display: block; margin: .7rem 0 .3rem; color: var(--rp-ink); }
        .rp-step span { color: var(--rp-muted); font-size: .84rem; line-height: 1.55; }
        .rp-status {
          display: inline-flex; align-items: center; gap: .35rem; padding: .3rem .62rem;
          border-radius: 999px; font-size: .75rem; font-weight: 800;
        }
        .rp-status-active { color: #047857; background: #d1fae5; }
        .rp-status-review { color: #b45309; background: #fef3c7; }
        .rp-status-revoked { color: #b91c1c; background: #fee2e2; }
        .rp-status-muted { color: #475569; background: #e2e8f0; }
        .rp-section-lead { color: var(--rp-muted); margin-top: -.55rem; margin-bottom: 1.1rem; }
        [data-testid="stMetric"] {
          background: rgba(255,255,255,.94);
          border: 1px solid var(--rp-line);
          border-radius: 16px;
          padding: .9rem 1rem;
          box-shadow: 0 8px 24px rgba(15, 23, 42, .035);
        }
        .stButton > button[kind="primary"] {
          border: 0;
          background: linear-gradient(135deg, var(--rp-blue), var(--rp-violet));
          box-shadow: 0 8px 20px rgba(79, 70, 229, .20);
        }
        .stButton > button { border-radius: 11px; }
        [data-testid="stDataFrame"] { border-radius: 16px; overflow: hidden; }
        @media (max-width: 720px) {
          [data-testid="stMainBlockContainer"] { padding-top: 1.2rem; }
          .rp-hero { padding: 1.6rem 1.35rem; border-radius: 20px; }
          .rp-hero h1 { font-size: 2.15rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def hero(title: str, body: str, *, kicker: str = "RepoProof Studio") -> None:
    st.markdown(
        f"""
        <section class="rp-hero">
          <span class="rp-kicker">✦ {escape(kicker)}</span>
          <h1>{escape(title)}</h1>
          <p>{escape(body)}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def metric_card(label: str, value: str, note: str) -> None:
    st.markdown(
        f"""
        <div class="rp-card">
          <div class="rp-card-label">{escape(label)}</div>
          <div class="rp-card-value">{escape(value)}</div>
          <div class="rp-card-note">{escape(note)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def flow_step(number: int, title: str, body: str) -> None:
    st.markdown(
        f"""
        <div class="rp-step">
          <span class="rp-step-no">{number}</span>
          <strong>{escape(title)}</strong>
          <span>{escape(body)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_intro(title: str, body: str) -> None:
    st.subheader(title)
    st.markdown(f'<div class="rp-section-lead">{escape(body)}</div>', unsafe_allow_html=True)


def status_badge(status: str) -> str:
    normalized = str(status or "UNKNOWN").upper()
    css = {
        "ACTIVE": "active",
        "REVIEW_REQUIRED": "review",
        "REVOKED": "revoked",
    }.get(normalized, "muted")
    label = {
        "ACTIVE": "可使用",
        "REVIEW_REQUIRED": "待审核",
        "REVOKED": "已撤回",
        "UNVERIFIED": "未验证",
    }.get(normalized, normalized or "未知")
    return f'<span class="rp-status rp-status-{css}">{escape(label)}</span>'
