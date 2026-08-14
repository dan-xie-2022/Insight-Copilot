"""Insight Copilot — UI shell.

Conversation is the product. The **Insight Dashboard** sits open beside it by default and
can be closed to give the conversation the full width. Ask a question, pin the answer,
watch it land in the panel next to you. Data and agent responses are mocked; the layout,
persistence, and governance behaviour are real, so this is the iteration surface rather
than a throwaway mockup.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import agent
import chat_store
import control_plane
import evidence_data as ed
import dashboard_store as store
import feedback_store as fb
import mock_data as md

st.set_page_config(
    page_title="Insight Copilot",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="collapsed",
)

ACCENT = "#1668E3"
GOOD = "#0F9D58"
BAD = "#D93025"
PANEL_HEIGHT = 620

# The dashboard is the default view: a market manager lands on their metrics, and the
# conversation is right there for the question the tiles can't answer.
if "dash_open" not in st.session_state:
    st.session_state["dash_open"] = True
if "conv_id" not in st.session_state:
    st.session_state["conv_id"] = None

dash_open = st.session_state["dash_open"]

# Raised on the frame *after* the pin, so it actually reaches the screen.
_pinned = st.session_state.pop("just_pinned", None)
if _pinned:
    st.toast(f"Pinned {_pinned}", icon="📌")

# Same reason: the confirmation has to outlive the rerun that submitted the feedback.
if st.session_state.pop("fb_sent", None):
    st.toast("Thanks — sent to the analyst queue", icon="📋")

st.markdown(
    """
    <style>
      /* No sidebar — navigation and context live in the top bar. */
      section[data-testid="stSidebar"],
      div[data-testid="stSidebarCollapsedControl"] { display: none !important; }

      /* Streamlit's header is fixed and overlays the top of the page, so the content
         needs to clear it — too little padding here hides the top bar entirely. */
      header[data-testid="stHeader"] { height: 2.75rem; background: transparent; }
      .block-container { padding-top: 3.4rem; max-width: 1580px; }

      .brand { font-size: 1.05rem; font-weight: 600; letter-spacing: -0.01em; }
      .brand-sub { color: #6b7280; font-size: 0.72rem; margin-top: -2px; }
      .topbar-note { color: #6b7280; font-size: 0.72rem; }

      /* --- Conversation, ChatGPT-style ---------------------------------------- */
      /* User turn: right-aligned grey bubble. Assistant turn: no bubble, no avatar,
         plain prose running the full measure. */
      .user-row { display: flex; justify-content: flex-end; margin: 1.75rem 0 0.25rem 0; }
      .user-bubble {
        background: #F4F4F4; border-radius: 20px; padding: 10px 17px;
        max-width: 72%; font-size: 0.95rem; line-height: 1.55; color: #0d0d0d;
      }
      .stMarkdown p { line-height: 1.72; }
      .turn-gap { height: 1.6rem; }

      /* Composer: rounded pill, soft shadow, docked at the foot of the viewport. */
      div[data-testid="stChatInput"] {
        border-radius: 26px !important;
        border: 1px solid rgba(0,0,0,0.12) !important;
        box-shadow: 0 2px 14px rgba(0,0,0,0.08);
        background: #ffffff !important;
      }
      textarea[data-testid="stChatInputTextArea"] {
        font-size: 0.95rem; padding-top: 0.75rem; padding-bottom: 0.75rem;
      }
      div[data-testid="stBottom"] { background: transparent; }
      div[data-testid="stBottomBlockContainer"] {
        max-width: 820px; margin: 0 auto; padding-bottom: 1.1rem;
      }

      /* Subtle per-message actions, like ChatGPT's icon row under a response. */
      .msg-actions button { color: #6b7280 !important; font-size: 0.8rem !important; }

      /* Follow-up card under a thumbs-down. It must read as a quiet aside, never as a
         form standing between the reader and the next answer. */
      .fb-ask { font-size: 0.86rem; font-weight: 600; margin-bottom: 0.1rem; }
      .fb-sub { color: #6b7280; font-size: 0.76rem; margin-bottom: 0.55rem; }
      .fb-thanks { color: #0F9D58; font-size: 0.78rem; margin-top: 0.1rem; }

      .empty-title {
        text-align: center; font-size: 1.75rem; font-weight: 600;
        letter-spacing: -0.02em; margin-bottom: 0.4rem;
      }
      .empty-sub { text-align: center; color: #6b7280; font-size: 0.85rem; margin-bottom: 1.6rem; }

      /* Tiles */
      .tile-head {
        font-size: 0.82rem; font-weight: 600; line-height: 1.25;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      }
      .tile-mkt { color: #6b7280; font-weight: 400; margin-left: 6px; }
      .tile-meta { color: #6b7280; font-size: 0.7rem; margin-left: 4px; }
      div[data-testid="stMetricValue"] { font-size: 1.5rem; }
      /* The ⋯ tile menu should read as a quiet affordance, not a control. */
      div[data-testid="stPopover"] button { color: #9aa0a6 !important; }
      .pill {
        display: inline-block; padding: 1px 8px; border-radius: 10px;
        font-size: 0.68rem; background: #EEF3FC; color: #1668E3; margin-right: 4px;
      }
      .pill-warn { background: #FCEFEE; color: #D93025; }
      .pill-muted { background: #F1F3F4; color: #5f6368; }
      .pill-ok { background: #E8F5EC; color: #0F9D58; }
      /* Evidence card */
      .verdict-effect {
        font-size: 1.6rem; font-weight: 600; letter-spacing: -0.02em; margin: 0.35rem 0 0.2rem 0;
      }
      .verdict-ci {
        font-size: 0.78rem; font-weight: 400; color: #6b7280; margin-left: 10px;
      }
      /* Control plane: inline field labels */
      .cp-label {
        color: #6b7280; font-size: 0.7rem; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.03em; margin-right: 4px;
      }
      .panel-title { font-size: 1.05rem; font-weight: 600; }
      /* Conversation rail */
      .rail-head {
        color: #6b7280; font-size: 0.7rem; font-weight: 600; letter-spacing: 0.04em;
        text-transform: uppercase; margin: 0.9rem 0 0.2rem 0.15rem;
      }
      .hist-empty { color: #6b7280; font-size: 0.78rem; line-height: 1.5; }
      /* Thread titles: single line, ellipsised, left-aligned like a real history list. */
      .rail-scroll button p {
        text-align: left !important; font-size: 0.83rem !important;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      }
      h1 { font-size: 1.6rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --- Top bar ------------------------------------------------------------------------

# The analyst top bar carries an extra control, so the layout is decided from the role
# already in session state before the selector itself is drawn.
is_analyst = st.session_state.get("role_select", list(md.ROLES)[0]) == "Analyst"

if is_analyst:
    brand_col, role_col, market_col, view_col, dash_btn_col = st.columns(
        [3.4, 2.2, 1.6, 2.6, 2.2], vertical_alignment="center"
    )
else:
    brand_col, role_col, market_col, dash_btn_col = st.columns(
        [5.4, 2.2, 1.7, 2.3], vertical_alignment="center"
    )
    view_col = None

with brand_col:
    st.markdown(
        '<div class="brand">🧭 Insight Copilot</div>'
        '<div class="brand-sub">Internal analytics for Expedia Group employees</div>',
        unsafe_allow_html=True,
    )

with role_col:
    role = st.selectbox(
        "Role",
        list(md.ROLES.keys()),
        index=0,
        format_func=lambda r: f"👤  {r}",
        label_visibility="collapsed",
        key="role_select",
        help="Who you're signed in as. Drives which data you can see, in both surfaces.",
    )

policy = md.ROLES[role]
user_key = role  # role stands in for the signed-in user until real auth exists

with market_col:
    _markets_by_region = sorted(md.MARKETS, key=lambda m: (md.region_of(m), m))
    market = st.selectbox(
        "Market",
        _markets_by_region,
        # Rome is the market carrying the demo's story — it must be the landing market,
        # or every new dashboard seeds against the wrong one.
        index=_markets_by_region.index("Rome"),
        format_func=lambda m: f"📍  {m} · {md.region_of(m)}",
        label_visibility="collapsed",
        help=f"Default market for new tiles. {len(md.MARKETS)} markets across "
             f"{', '.join(md.REGIONS)}.",
    )

# Analysts get a second surface: they are the supply side of the copilot, not just
# another asker. Every other role sees the copilot only.
view = "💬 Copilot"
if view_col is not None:
    with view_col:
        view = st.segmented_control(
            "View",
            ["💬 Copilot", "🛠 Control Plane"],
            default="🛠 Control Plane",
            label_visibility="collapsed",
            width="stretch",
            key="analyst_view",
        ) or "🛠 Control Plane"

control_plane_view = view == "🛠 Control Plane"

with dash_btn_col:
    if not control_plane_view:
        if st.button(
            "✕  Close dashboard" if dash_open else "📊  Insight Dashboard",
            width="stretch",
            type="secondary" if dash_open else "primary",
        ):
            st.session_state["dash_open"] = not dash_open
            st.rerun()

st.markdown(f'<div class="topbar-note">{policy["note"]}</div>', unsafe_allow_html=True)
st.divider()

as_of = md.warehouse_as_of()
turns = chat_store.get_turns(user_key, st.session_state["conv_id"])


# --- Shared rendering ---------------------------------------------------------------

def chart_for(
    metric_id: str, mkt: str, height: int = 150, color: str = ACCENT, compact: bool = False
) -> go.Figure:
    spec = md.METRICS[metric_id]
    df = md.series(metric_id, mkt)
    rgb = tuple(int(color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    fig = go.Figure()
    if spec["chart"] == "bar":
        fig.add_bar(x=df["date"], y=df["value"], marker_color=color, opacity=0.75)
    else:
        fig.add_scatter(
            x=df["date"],
            y=df["value"],
            mode="lines",
            line=dict(color=color, width=2),
            fill="tozeroy",
            fillcolor=f"rgba({rgb[0]},{rgb[1]},{rgb[2]},0.10)",
        )
    fig.update_layout(
        height=height,
        margin=dict(l=0, r=0, t=6, b=0),
        showlegend=False,
        # A half-width tile has no room for axes; it reads as a sparkline instead.
        xaxis=dict(showgrid=False, title=None, visible=not compact),
        yaxis=dict(
            showgrid=not compact, gridcolor="rgba(0,0,0,0.06)", title=None, visible=not compact
        ),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def tile_menu(index: int, total: int, size: str) -> None:
    """Per-tile actions.

    These live in a popover rather than a button row because a half-width tile sits two
    column levels deep, and Streamlit refuses a third level of nested columns.
    """
    with st.popover("⋯", help="Tile options"):
        if st.button("⤢  Full width" if size == "half" else "⤡  Half width",
                     key=f"size_{index}", width="stretch", type="tertiary"):
            store.toggle_size(user_key, index)
            st.rerun()
        if st.button("↑  Move up", key=f"up_{index}", disabled=index == 0,
                     width="stretch", type="tertiary"):
            store.move_tile(user_key, index, -1)
            st.rerun()
        if st.button("↓  Move down", key=f"dn_{index}", disabled=index == total - 1,
                     width="stretch", type="tertiary"):
            store.move_tile(user_key, index, 1)
            st.rerun()
        if st.button("✕  Remove", key=f"rm_{index}", width="stretch", type="tertiary"):
            store.remove_tile(user_key, index)
            st.rerun()


def render_tile(tile: dict, index: int, total: int) -> None:
    """One dashboard tile. Re-executed on every render — nothing is read from cache."""
    metric_id, mkt = tile["metric_id"], tile["market"]
    spec = md.METRICS[metric_id]
    size = tile.get("size", "half")
    compact = size == "half"

    # Governance is enforced at *render* time, under the user's current role.
    if metric_id not in policy["allowed"]:
        with st.container(border=True):
            st.markdown(f"**{spec['label']}** · {mkt}")
            st.markdown(
                '<span class="pill pill-warn">access revoked</span>', unsafe_allow_html=True
            )
            st.caption(
                f"Pinned under a different role. **{role}** is not entitled to "
                f"`{'`, `'.join(spec['lineage'][:2])}`, so no values were fetched."
            )
            if st.button("Remove", key=f"rm_{index}", width="stretch"):
                store.remove_tile(user_key, index)
                st.rerun()
        return

    summary = md.summarize(md.series(metric_id, mkt))
    delta = summary["delta_pct"]
    good = (delta >= 0) == spec["higher_is_better"]
    # Colour carries the judgement, so a glance across the grid reads as well as a read.
    colour = GOOD if good else BAD

    with st.container(border=True):
        st.markdown(
            f'<div class="tile-head">{spec["label"]}'
            f'<span class="tile-mkt">{mkt}</span></div>',
            unsafe_allow_html=True,
        )
        st.metric(
            label="last 7 days vs prior 7",
            value=md.format_value(summary["current"], spec["unit"]),
            delta=f"{delta:+.1f}%",
            delta_color="normal" if good else "inverse",
            label_visibility="collapsed",
        )
        st.plotly_chart(
            chart_for(metric_id, mkt, height=104 if compact else 168, color=colour,
                      compact=compact),
            width="stretch",
            key=f"chart_{index}_{metric_id}_{mkt}",
        )

        badge = "pinned from chat" if tile.get("source") == "pinned" else "role template"
        # A live experiment means part of this traffic is deliberately being treated —
        # reading the tile as organic movement would be a mistake.
        live = ed.covering(metric_id, mkt)
        st.markdown(
            f'<span class="pill pill-muted">{badge}</span>'
            + ('<span class="pill pill-warn">🧪 experiment live</span>' if live else "")
            + f'<span class="tile-meta">as of {as_of:%b %d, %H:%M}</span>',
            unsafe_allow_html=True,
        )
        if live:
            st.caption(
                f"`{live['name']}` is running here — this number mixes control and "
                "treatment traffic. Ask about the experiment for a clean readout."
            )
        # No columns anywhere in here: a half-width tile is already two levels deep.
        tile_menu(index, total, size)


def render_empty_state() -> None:
    st.markdown('<div style="height:8vh"></div>', unsafe_allow_html=True)
    st.markdown('<div class="empty-title">What do you want to know?</div>',
                unsafe_allow_html=True)
    st.markdown(
        '<div class="empty-sub">Ask about your markets. Answers show their SQL, sources, '
        'and confidence — and pin to your dashboard.</div>',
        unsafe_allow_html=True,
    )
    samples = md.sample_questions(role)
    for row in (samples[:2], samples[2:]):
        cols = st.columns(len(row))
        for col, sample in zip(cols, row):
            if col.button(sample, key=f"sample_{sample}", width="stretch"):
                st.session_state["pending_question"] = sample
                st.rerun()


def render_history_rail() -> None:
    """Conversation sidebar: new chat + saved threads, scoped to the signed-in role."""
    if st.button("＋  New chat", width="stretch", type="secondary"):
        st.session_state["conv_id"] = None
        st.rerun()

    st.markdown('<div class="rail-head">Recent</div>', unsafe_allow_html=True)

    conversations = chat_store.list_conversations(user_key)
    with st.container(height=PANEL_HEIGHT - 60, border=False):
        if not conversations:
            st.markdown(
                '<div class="hist-empty">No conversations yet. Ask something and it will '
                "appear here.</div>",
                unsafe_allow_html=True,
            )
            return

        for conv in conversations[:30]:
            active = conv["id"] == st.session_state["conv_id"]
            title = conv["title"]
            if len(title) > 26:
                title = title[:25].rstrip() + "…"

            open_col, del_col = st.columns([5, 1.25], vertical_alignment="center")
            if open_col.button(
                f"{'●  ' if active else ''}{title}",
                key=f"conv_{conv['id']}",
                width="stretch",
                type="tertiary",
                help=f"{len(conv['turns'])} turn(s) · updated "
                f"{conv['updated'][:16].replace('T', ' ')}",
            ):
                st.session_state["conv_id"] = conv["id"]
                st.rerun()
            if del_col.button("✕", key=f"delconv_{conv['id']}", type="tertiary",
                              help="Delete conversation"):
                chat_store.delete(user_key, conv["id"])
                if active:
                    st.session_state["conv_id"] = None
                st.rerun()


DESIGN_STYLE = {
    "randomized": ("🎲 randomized experiment", "pill-ok"),
    "quasi-experimental": ("⚖️ quasi-experimental", "pill"),
    "associational": ("〜 association only", "pill-warn"),
}


def render_verdict(v: dict, turn: int) -> None:
    """The evidence card. One component renders all four rungs of the ladder."""
    label, css = DESIGN_STYLE[v["design"]]
    st.markdown(
        f'<span class="pill {css}">{label}</span>'
        f'<span class="pill pill-muted">{v["method"]}</span>',
        unsafe_allow_html=True,
    )

    if v["effect_pct"] is not None and v["ci_pct"]:
        lo, hi = v["ci_pct"]
        st.markdown(
            f'<div class="verdict-effect">{v["effect_pct"]:+.1f}%'
            f'<span class="verdict-ci">95% CI [{lo:+.1f}, {hi:+.1f}]'
            + (f" · p={v['p_value']:.3f}" if v["p_value"] is not None else "")
            + "</span></div>",
            unsafe_allow_html=True,
        )

    if v.get("intervention"):
        st.markdown(
            f'<span class="cp-label">Attributed to</span> {v["intervention"]}',
            unsafe_allow_html=True,
        )
    if v.get("controls"):
        st.markdown(
            f'<span class="cp-label">Compared against</span> {", ".join(v["controls"])}',
            unsafe_allow_html=True,
        )

    with st.expander(
        "Assumptions "
        + ("✓ all hold" if all(a["passed"] for a in v["assumptions"]) else "⚠ one or more fail")
    ):
        for a in v["assumptions"]:
            mark = "✅" if a["passed"] else "❌"
            st.markdown(f"{mark} **{a['name']}** — {a['detail']}")
        for c in v["caveats"]:
            st.markdown(f"⚠️ {c}")
        if v.get("excluded_controls"):
            st.markdown(
                "**Markets excluded as controls:** "
                + ", ".join(f"{m} — {why}" for m, why in v["excluded_controls"])
            )


ROW_MARK = {"win": "✅", "regression": "🚨", "flat": "—"}


def render_scorecard(sc: dict, turn: int) -> None:
    """An experiment readout, rendered the way a scorecard actually reads."""
    st.markdown(
        f'<span class="pill pill-ok">🎲 randomized experiment</span>'
        f'<span class="pill pill-muted">{sc["status"]} · day {sc["day"]}</span>'
        + (
            '<span class="pill pill-warn">SRM fail — unreadable</span>'
            if not sc["srm_pass"]
            else ""
        ),
        unsafe_allow_html=True,
    )
    st.markdown(f'_{sc["hypothesis"]}_')

    rows = []
    for r in sc["visible_metrics"]:
        spec = md.METRICS[r["metric_id"]]
        verdict = ed.row_verdict(r)
        lo, hi = r["ci"]
        rows.append(
            {
                "": ROW_MARK[verdict] if sc["srm_pass"] else "🚫",
                "Metric": spec["label"],
                "Role": r["kind"],
                "Control": md.format_value(r["control"], spec["unit"]),
                "Treatment": md.format_value(r["treatment"], spec["unit"]),
                "Lift": f"{r['estimate']:+.1f}%",
                "95% CI": f"[{lo:+.1f}, {hi:+.1f}]",
                "p": f"{r['p_value']:.3f}",
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    st.markdown(
        f'<span class="cp-label">Unit</span> {sc["unit"]} &nbsp; '
        f'<span class="cp-label">Exposed</span> {sc["exposed_users"]:,} &nbsp; '
        f'<span class="cp-label">Owner</span> {sc["owner"]} &nbsp; '
        f'<span class="cp-label">Source</span> experimentation platform (read-only)',
        unsafe_allow_html=True,
    )


def render_rating(turn: int, q: str, a: dict) -> None:
    """👍/👎 under an answer. A thumbs-down opens the follow-up card beneath it.

    The rating is written the moment it is clicked. Asking for a reason first would lose
    the signal from everyone who cannot be bothered to give one — which is most people,
    and their thumbs-down still counts.
    """
    conv_id = st.session_state["conv_id"]
    current = (fb.get(user_key, conv_id, turn) or {}).get("rating")

    widget = f"fb_thumbs_{conv_id}_{turn}"
    if widget not in st.session_state:
        st.session_state[widget] = {"down": 0, "up": 1}.get(current)

    picked = {0: "down", 1: "up"}.get(st.feedback("thumbs", key=widget))
    if picked == current:
        return

    if picked is None:
        fb.clear(user_key, conv_id, turn)
    else:
        fb.rate(
            user_key, conv_id, turn, picked,
            {
                "question": q,
                "role": role,
                "metric_id": a.get("metric_id"),
                "market": a.get("market"),
                "kind": a.get("kind"),
            },
        )
    st.session_state[f"fb_open_{conv_id}_{turn}"] = picked == "down"
    st.rerun()


def render_feedback_detail(turn: int) -> None:
    """The 'tell us more' step: reason chips plus free text, on a thumbs-down only."""
    conv_id = st.session_state["conv_id"]
    record = fb.get(user_key, conv_id, turn) or {}
    if record.get("rating") != "down":
        return

    open_key = f"fb_open_{conv_id}_{turn}"
    given = bool(record.get("reasons") or record.get("comment"))

    if not st.session_state.get(open_key):
        # Collapsed: a receipt if they told us why, a way back in if they dismissed it.
        if given:
            st.markdown(
                '<div class="fb-thanks">✓ Thanks — this is with the analyst queue.</div>',
                unsafe_allow_html=True,
            )
        elif st.button("＋ Add detail", key=f"fb_more_{conv_id}_{turn}", type="tertiary"):
            st.session_state[open_key] = True
            st.rerun()
        return

    with st.container(border=True):
        st.markdown(
            '<div class="fb-ask">Tell us what went wrong</div>'
            '<div class="fb-sub">Optional — but it routes the fix to whoever owns it.</div>',
            unsafe_allow_html=True,
        )
        reasons = st.pills(
            "Reason",
            list(fb.REASONS),
            selection_mode="multi",
            default=record.get("reasons") or None,
            key=f"fb_why_{conv_id}_{turn}",
            label_visibility="collapsed",
        )
        comment = st.text_area(
            "More detail",
            value=record.get("comment", ""),
            placeholder="What did you expect to see instead?",
            key=f"fb_txt_{conv_id}_{turn}",
            label_visibility="collapsed",
            height=80,
        )
        send, skip, _ = st.columns([1.7, 1.1, 3.6])
        if send.button(
            "Submit feedback", key=f"fb_send_{conv_id}_{turn}",
            type="primary", width="stretch",
        ):
            fb.add_detail(user_key, conv_id, turn, reasons, comment)
            st.session_state[open_key] = False
            st.session_state["fb_sent"] = True
            st.rerun()
        if skip.button(
            "Not now", key=f"fb_skip_{conv_id}_{turn}", type="tertiary", width="stretch"
        ):
            st.session_state[open_key] = False
            st.rerun()


def render_conversation() -> None:
    """The transcript: user bubbles right, assistant prose left, actions underneath."""
    if not turns:
        render_empty_state()
        return

    for turn, (q, a) in enumerate(turns):
        st.markdown(
            f'<div class="user-row"><div class="user-bubble">{q}</div></div>',
            unsafe_allow_html=True,
        )

        if a["kind"] == "refusal":
            st.error(a["narrative"], icon="🔒")
        elif a["kind"] == "unknown":
            st.info(a["narrative"], icon="❓")
        else:
            st.markdown(a["narrative"])
            if a.get("verdict"):
                render_verdict(a["verdict"], turn)
            if a.get("scorecard"):
                render_scorecard(a["scorecard"], turn)
            if a["metric_id"] and a["metric_id"] in policy["allowed"]:
                st.plotly_chart(
                    chart_for(a["metric_id"], a["market"], height=210),
                    width="stretch",
                    key=f"ans_chart_{turn}",
                )

        conf = a["confidence"]
        conf_label = "high" if conf >= 0.85 else "medium" if conf >= 0.6 else "low"
        st.markdown(
            f'<span class="pill">confidence: {conf_label} ({conf:.0%})</span>'
            + (
                f'<span class="pill pill-muted">sources: {", ".join(a["lineage"])}</span>'
                if a["lineage"]
                else ""
            )
            + (
                f'<span class="pill pill-muted">{a["engine"]}</span>'
                if a.get("engine")
                else ""
            ),
            unsafe_allow_html=True,
        )

        with st.expander("How I got this"):
            st.markdown("**Plan**")
            for i, step in enumerate(a["plan"], 1):
                st.markdown(f"{i}. {step}")
            if a["sql"]:
                st.markdown("**Query**")
                if policy["can_see_sql"]:
                    st.code(a["sql"], language="sql")
                else:
                    st.caption(
                        "SQL is hidden for your role — the query ran against "
                        f"`{'`, `'.join(a['lineage'][:3])}` under your access policy. "
                        "Switch to Analyst to inspect it."
                    )

        st.markdown('<div class="msg-actions">', unsafe_allow_html=True)
        act1, act2, _ = st.columns([2.1, 1.4, 4])
        can_pin = bool(a["metric_id"]) and a["metric_id"] in policy["allowed"]
        # The button has to tell the truth about state. Offering "Pin" for something
        # already pinned reads as a broken button when the duplicate is refused.
        already = can_pin and store.has_tile(user_key, a["metric_id"], a["market"])
        if act1.button(
            "✓ On your dashboard" if already else "📌 Pin to dashboard",
            key=f"pin_{turn}",
            disabled=not can_pin or already,
            type="tertiary",
            help=f"{md.METRICS[a['metric_id']]['label']} · {a['market']} is already a tile"
            if already
            else None,
        ):
            store.add_tile(user_key, a["metric_id"], a["market"])
            # Pinning opens the panel so the result of the action is visible.
            st.session_state["dash_open"] = True
            # Toast after the rerun, not before it — a toast raised immediately before
            # st.rerun() is discarded with the rest of the frame.
            st.session_state["just_pinned"] = (
                f"{md.METRICS[a['metric_id']]['label']} · {a['market']}"
            )
            st.rerun()
        with act2:
            render_rating(turn, q, a)
        st.markdown("</div>", unsafe_allow_html=True)
        render_feedback_detail(turn)
        st.markdown('<div class="turn-gap"></div>', unsafe_allow_html=True)


def render_tile_grid(tiles: list) -> None:
    """Pack tiles into rows: full-width tiles take a row, half-width tiles pair up."""
    i = 0
    while i < len(tiles):
        if tiles[i].get("size", "half") == "full":
            render_tile(tiles[i], i, len(tiles))
            i += 1
            continue

        pair = i + 1 < len(tiles) and tiles[i + 1].get("size", "half") == "half"
        left, right = st.columns(2, gap="small")
        with left:
            render_tile(tiles[i], i, len(tiles))
        if pair:
            with right:
                render_tile(tiles[i + 1], i + 1, len(tiles))
        i += 2 if pair else 1


def render_add_metric() -> None:
    """Add any metric the role is entitled to, without going through the chat."""
    with st.popover("＋  Add metric", width="stretch"):
        st.markdown("**Add a metric to your dashboard**")
        choice = st.selectbox(
            "Metric",
            policy["allowed"],
            format_func=lambda m: md.METRICS[m]["label"],
            key="add_metric",
        )
        add_market = st.selectbox(
            "Market", md.MARKETS, index=md.MARKETS.index(market), key="add_market"
        )
        st.caption(
            f"Sources: `{'`, `'.join(md.METRICS[choice]['lineage'][:2])}` · "
            "the tile stores this definition and recomputes it on every open."
        )
        if st.button("Add to dashboard", key="do_add", width="stretch", type="primary"):
            if store.add_tile(user_key, choice, add_market, source="added"):
                st.toast(f"Added {md.METRICS[choice]['label']} · {add_market}", icon="📊")
                st.rerun()
            else:
                st.warning("That tile is already on your dashboard.")


def render_dashboard_panel() -> None:
    title_col, add_col = st.columns([3, 1.7], vertical_alignment="center")
    with title_col:
        st.markdown('<div class="panel-title">📊 Insight Dashboard</div>',
                    unsafe_allow_html=True)
    with add_col:
        render_add_metric()

    st.caption(
        f"Saved layout, recomputed on open · as of **{as_of:%b %d, %H:%M}** (hourly batch)"
    )

    with st.container(height=PANEL_HEIGHT, border=False):
        # Monitoring is the product, not a mode: the panel always leads with the
        # largest unexplained move rather than waiting to be asked.
        a = md.driver_analysis("Rome")
        st.warning(
            f"**Rome conversion fell {abs(a['deltas']['conversion_rate']):.1f}% WoW** — "
            f"largest move across your monitored metrics. Lines up with a "
            f"{abs(a['deltas']['marketing_spend']):.0f}% paid-search cut on "
            f"{a['cut_date']:%b %d}.",
            icon="⚡",
        )

        tiles = store.load(user_key, policy["template"], market)
        if not tiles:
            st.info("No tiles yet. Ask a question and pin the answer.")
        render_tile_grid(tiles)


# --- Layout: conversation and dashboard side by side --------------------------------

if control_plane_view:
    control_plane.render()
    st.stop()

if dash_open:
    rail_area, chat_area, panel_area = st.columns([0.95, 2.15, 1.95], gap="medium")
else:
    # Closed: rail stays put and the transcript centres on a ChatGPT-ish measure
    # rather than sprawling the full page width.
    rail_area, chat_area, _ = st.columns([0.95, 3.0, 0.95], gap="medium")
    panel_area = None

with rail_area:
    render_history_rail()

with chat_area:
    if not dash_open:
        # With the panel closed the alert still has to reach the user, so it leads
        # the conversation instead.
        a = md.driver_analysis("Rome")
        st.warning(
            f"**Rome conversion fell {abs(a['deltas']['conversion_rate']):.1f}% WoW.** "
            f"Timing lines up with a {abs(a['deltas']['marketing_spend']):.0f}% paid-search "
            f"cut on {a['cut_date']:%b %d}. Ask me why, or open the dashboard.",
            icon="⚡",
        )

    if dash_open:
        # Beside the panel, the transcript gets its own scroll so the two sides stay
        # aligned and the composer stays reachable.
        with st.container(height=PANEL_HEIGHT, border=False):
            render_conversation()
        typed = st.chat_input("Ask anything about your markets…", key="composer_inline")
    else:
        render_conversation()
        typed = None

if panel_area is not None:
    with panel_area:
        render_dashboard_panel()

if not dash_open:
    # Top-level call, so Streamlit docks it to the foot of the viewport and the page
    # scrolls behind it — the ChatGPT arrangement.
    typed = st.chat_input("Ask anything about your markets…", key="composer_docked")

question = typed or st.session_state.pop("pending_question", None)
if question:
    if st.session_state["conv_id"] is None:
        st.session_state["conv_id"] = chat_store.create(user_key, question)
    with st.spinner("Thinking…"):
        # Live DeepSeek agent; falls back to the deterministic answers if the model or
        # the network is unavailable, so the demo never dies mid-conversation.
        reply = agent.answer(question, role)
    chat_store.append_turn(user_key, st.session_state["conv_id"], question, reply)
    st.rerun()
