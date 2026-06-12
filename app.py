"""
app.py — Exam PDF Extraction Engine — Admin Portal
Two-page Dash application:
    Page 1 /upload  — upload question + scheme PDFs, view upload history
    Page 2 /records — view all processed extraction jobs
"""

import dash
from dash import dcc, html, dash_table, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc
import requests
import os
from datetime import datetime
from decouple import config as env

API_BASE = env("API_BASE_URL", default="http://localhost:8000")
API_KEY  = env("ADMIN_API_KEY", default="")

HEADERS = {"X-API-Key": API_KEY}

# ── Colour tokens ─────────────────────────────────────────────────────────────

NAVY    = "#0A0F2C"
INK     = "#111827"
PAPER   = "#F5F4EF"
MIST    = "#E8E6DF"
ACCENT  = "#C8A96E"        # warm gold
ACCENT2 = "#4A6FA5"        # steel blue
SUCCESS = "#2D6A4F"
WARNING = "#B5640A"
ERROR   = "#8B1A1A"
WHITE   = "#FFFFFF"

FONT_DISPLAY = "'DM Serif Display', Georgia, serif"
FONT_BODY    = "'DM Mono', 'Courier New', monospace"

EXTERNAL_STYLESHEETS = [
    dbc.themes.BOOTSTRAP,
    "https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Mono:wght@300;400;500&display=swap",
]

app = dash.Dash(
    __name__,
    external_stylesheets=EXTERNAL_STYLESHEETS,
    suppress_callback_exceptions=True,
    use_pages=False,
)
app.title = "Extraction Engine"
server = app.server

# ── Shared styles ─────────────────────────────────────────────────────────────

PAGE_STYLE = {
    "backgroundColor": PAPER,
    "minHeight":       "100vh",
    "fontFamily":      FONT_BODY,
    "color":           INK,
}

SIDEBAR_STYLE = {
    "position":        "fixed",
    "top":             0,
    "left":            0,
    "bottom":          0,
    "width":           "220px",
    "backgroundColor": NAVY,
    "padding":         "2rem 1.5rem",
    "zIndex":          1000,
}

CONTENT_STYLE = {
    "marginLeft": "220px",
    "padding":    "2.5rem 3rem",
    "minHeight":  "100vh",
}

CARD_STYLE = {
    "backgroundColor": WHITE,
    "borderRadius":    "2px",
    "border":          f"1px solid {MIST}",
    "padding":         "2rem",
    "marginBottom":    "1.5rem",
    "boxShadow":       "0 1px 3px rgba(0,0,0,0.06)",
}

HEADING_STYLE = {
    "fontFamily": FONT_DISPLAY,
    "color":      NAVY,
    "fontWeight": "normal",
    "letterSpacing": "-0.5px",
}

NAV_LINK_STYLE = {
    "display":         "block",
    "color":           "#8A9BB5",
    "textDecoration":  "none",
    "fontFamily":      FONT_BODY,
    "fontSize":        "0.78rem",
    "letterSpacing":   "0.12em",
    "textTransform":   "uppercase",
    "padding":         "0.6rem 0",
    "borderLeft":      "2px solid transparent",
    "paddingLeft":     "0.75rem",
    "marginBottom":    "0.25rem",
    "transition":      "all 0.15s ease",
}

NAV_LINK_ACTIVE = {
    **NAV_LINK_STYLE,
    "color":       ACCENT,
    "borderLeft":  f"2px solid {ACCENT}",
}

BTN_PRIMARY = {
    "backgroundColor": NAVY,
    "color":           WHITE,
    "border":          "none",
    "borderRadius":    "2px",
    "fontFamily":      FONT_BODY,
    "fontSize":        "0.78rem",
    "letterSpacing":   "0.1em",
    "textTransform":   "uppercase",
    "padding":         "0.65rem 1.75rem",
    "cursor":          "pointer",
}

TABLE_STYLE = {
    "fontFamily":  FONT_BODY,
    "fontSize":    "0.8rem",
    "color":       INK,
}

TABLE_HEADER_STYLE = [{
    "backgroundColor": NAVY,
    "color":           ACCENT,
    "fontWeight":      "500",
    "letterSpacing":   "0.08em",
    "textTransform":   "uppercase",
    "fontSize":        "0.72rem",
    "border":          "none",
    "padding":         "0.75rem 1rem",
}]

TABLE_CELL_STYLE = [{
    "padding":         "0.65rem 1rem",
    "borderBottom":    f"1px solid {MIST}",
    "backgroundColor": WHITE,
}]

TABLE_FILTER_STYLE = {
    "backgroundColor": PAPER,
    "border":          f"1px solid {MIST}",
    "borderRadius":    "2px",
    "color":           INK,
    "fontFamily":      FONT_BODY,
    "fontSize":        "0.78rem",
    "padding":         "0.4rem 0.6rem",
}

# ── Sidebar ───────────────────────────────────────────────────────────────────

def sidebar(active_page: str):
    links = [
        ("/upload",  "Upload"),
        ("/records", "Records"),
    ]
    items = []
    for href, label in links:
        style = NAV_LINK_ACTIVE if active_page == href else NAV_LINK_STYLE
        items.append(
            html.A(label, href=href, style=style)
        )

    return html.Div([
        html.Div([
            html.Div("⬡", style={
                "color":        ACCENT,
                "fontSize":     "1.5rem",
                "marginBottom": "0.25rem",
            }),
            html.Div("Extraction", style={
                "color":        WHITE,
                "fontFamily":   FONT_DISPLAY,
                "fontSize":     "1.1rem",
                "fontWeight":   "normal",
                "letterSpacing": "-0.3px",
            }),
            html.Div("Engine", style={
                "color":        ACCENT,
                "fontFamily":   FONT_DISPLAY,
                "fontSize":     "1.1rem",
                "fontWeight":   "normal",
                "marginBottom": "2.5rem",
            }),
        ]),
        html.Div([
            html.Div("Navigation", style={
                "color":         "#4A5568",
                "fontSize":      "0.65rem",
                "letterSpacing": "0.15em",
                "textTransform": "uppercase",
                "marginBottom":  "0.75rem",
                "fontFamily":    FONT_BODY,
            }),
            *items,
        ]),
        html.Div([
            html.Div(style={
                "height":          "1px",
                "backgroundColor": "#1E2A4A",
                "marginBottom":    "1rem",
            }),
            html.Div("v1.0.0", style={
                "color":    "#4A5568",
                "fontSize": "0.7rem",
                "fontFamily": FONT_BODY,
            }),
        ], style={
            "position": "absolute",
            "bottom":   "1.5rem",
            "left":     "1.5rem",
            "right":    "1.5rem",
        }),
    ], style=SIDEBAR_STYLE)

# ── Status badge helper ───────────────────────────────────────────────────────
def status_badge(status: str) -> str:
    """Return emoji prefix for status strings in tables."""
    s = (status or "").lower()
    if s == "complete":   return f"● {status}"
    if s == "partial":    return f"◐ {status}"
    if s == "failed":     return f"○ {status}"
    if s == "running":    return f"◌ {status}"
    return status


# ── PAGE 1: UPLOAD ────────────────────────────────────────────────────────────

def layout_upload():
    return html.Div([
        sidebar("/upload"),
        html.Div([

            # Page heading
            html.Div([
                html.H2("Upload Papers", style={**HEADING_STYLE, "fontSize": "1.9rem", "marginBottom": "0.25rem"}),
                html.P("Submit question papers and marking schemes for extraction.",
                       style={"color": "#6B7280", "fontSize": "0.82rem", "marginBottom": "2rem"}),
            ]),

            # ── Upload card ───────────────────────────────────────────────────
            html.Div([
                html.Div([
                    html.Div("01", style={
                        "fontFamily":    FONT_DISPLAY,
                        "fontSize":      "0.75rem",
                        "color":         ACCENT,
                        "letterSpacing": "0.1em",
                        "marginBottom":  "0.25rem",
                    }),
                    html.H4("Submit Documents", style={
                        **HEADING_STYLE,
                        "fontSize":     "1.2rem",
                        "marginBottom": "1.5rem",
                    }),
                ]),

                dbc.Row([
                    # Questions PDF
                    dbc.Col([
                        html.Label("Questions PDF", style={
                            "fontSize":      "0.72rem",
                            "letterSpacing": "0.1em",
                            "textTransform": "uppercase",
                            "color":         "#6B7280",
                            "marginBottom":  "0.5rem",
                            "display":       "block",
                        }),
                        dcc.Upload(
                            id="upload-questions",
                            children=html.Div([
                                html.Div("↑", style={"fontSize": "1.5rem", "color": ACCENT2, "marginBottom": "0.5rem"}),
                                html.Div("Drop file or click to browse", style={"fontSize": "0.8rem", "color": "#6B7280"}),
                                html.Div("PDF only", style={"fontSize": "0.7rem", "color": "#9CA3AF", "marginTop": "0.25rem"}),
                            ], style={"textAlign": "center"}),
                            style={
                                "border":        f"1.5px dashed {MIST}",
                                "borderRadius":  "2px",
                                "padding":       "2rem 1rem",
                                "cursor":        "pointer",
                                "backgroundColor": PAPER,
                                "transition":    "border-color 0.2s",
                            },
                            accept=".pdf",
                        ),
                        html.Div(id="questions-filename", style={
                            "fontSize":   "0.75rem",
                            "color":      SUCCESS,
                            "marginTop":  "0.5rem",
                            "fontFamily": FONT_BODY,
                        }),
                    ], md=6),

                    # Marking scheme PDF
                    dbc.Col([
                        html.Label("Marking Scheme PDF", style={
                            "fontSize":      "0.72rem",
                            "letterSpacing": "0.1em",
                            "textTransform": "uppercase",
                            "color":         "#6B7280",
                            "marginBottom":  "0.5rem",
                            "display":       "block",
                        }),
                        dcc.Upload(
                            id="upload-scheme",
                            children=html.Div([
                                html.Div("↑", style={"fontSize": "1.5rem", "color": ACCENT2, "marginBottom": "0.5rem"}),
                                html.Div("Drop file or click to browse", style={"fontSize": "0.8rem", "color": "#6B7280"}),
                                html.Div("Optional — PDF only", style={"fontSize": "0.7rem", "color": "#9CA3AF", "marginTop": "0.25rem"}),
                            ], style={"textAlign": "center"}),
                            style={
                                "border":        f"1.5px dashed {MIST}",
                                "borderRadius":  "2px",
                                "padding":       "2rem 1rem",
                                "cursor":        "pointer",
                                "backgroundColor": PAPER,
                            },
                            accept=".pdf",
                        ),
                        html.Div(id="scheme-filename", style={
                            "fontSize":   "0.75rem",
                            "color":      SUCCESS,
                            "marginTop":  "0.5rem",
                            "fontFamily": FONT_BODY,
                        }),
                    ], md=6),
                ], style={"marginBottom": "1.75rem"}),

                html.Div([
                    html.Button("Upload & Extract", id="btn-upload", n_clicks=0, style=BTN_PRIMARY),
                    html.Span(id="upload-status", style={
                        "marginLeft": "1.25rem",
                        "fontSize":   "0.78rem",
                        "fontFamily": FONT_BODY,
                    }),
                ], style={"display": "flex", "alignItems": "center"}),

                # Hidden stores for file content
                dcc.Store(id="store-questions"),
                dcc.Store(id="store-scheme"),

            ], style=CARD_STYLE),

            # ── Previous uploads card ─────────────────────────────────────────
            html.Div([
                html.Div([
                    html.Div("02", style={
                        "fontFamily":    FONT_DISPLAY,
                        "fontSize":      "0.75rem",
                        "color":         ACCENT,
                        "letterSpacing": "0.1em",
                        "marginBottom":  "0.25rem",
                    }),
                    html.H4("Upload History", style={
                        **HEADING_STYLE,
                        "fontSize":     "1.2rem",
                        "marginBottom": "1.25rem",
                    }),
                ]),

                html.Div(id="upload-history-table", children=[
                    html.P("Loading history...", style={"color": "#9CA3AF", "fontSize": "0.8rem"})
                ]),

                dcc.Interval(id="history-refresh", interval=15_000, n_intervals=0),

            ], style=CARD_STYLE),

        ], style=CONTENT_STYLE),
    ], style=PAGE_STYLE)


# ── PAGE 2: RECORDS ───────────────────────────────────────────────────────────

def layout_records():
    return html.Div([
        sidebar("/records"),
        html.Div([

            html.Div([
                html.H2("Processed Records", style={**HEADING_STYLE, "fontSize": "1.9rem", "marginBottom": "0.25rem"}),
                html.P("All extraction jobs and their outputs.",
                       style={"color": "#6B7280", "fontSize": "0.82rem", "marginBottom": "2rem"}),
            ]),

            # Stats strip
            html.Div(id="records-stats", style={"marginBottom": "1.5rem"}),

            # Records card
            html.Div([
                html.Div([
                    html.Div("01", style={
                        "fontFamily":    FONT_DISPLAY,
                        "fontSize":      "0.75rem",
                        "color":         ACCENT,
                        "letterSpacing": "0.1em",
                        "marginBottom":  "0.25rem",
                    }),
                    html.H4("All Jobs", style={
                        **HEADING_STYLE,
                        "fontSize":     "1.2rem",
                        "marginBottom": "1.25rem",
                    }),
                ]),
                html.Div(id="records-table", children=[
                    html.P("Loading records...", style={"color": "#9CA3AF", "fontSize": "0.8rem"})
                ]),
                dcc.Interval(id="records-refresh", interval=20_000, n_intervals=0),
            ], style=CARD_STYLE),

        ], style=CONTENT_STYLE),
    ], style=PAGE_STYLE)


# ── Router ────────────────────────────────────────────────────────────────────

app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    html.Div(id="page-content"),
])


@callback(Output("page-content", "children"), Input("url", "pathname"))
def display_page(pathname):
    if pathname in ("/", "/upload"):
        return layout_upload()
    if pathname == "/records":
        return layout_records()
    return html.Div([
        sidebar("/"),
        html.Div([
            html.H2("404 — Page not found", style=HEADING_STYLE),
        ], style=CONTENT_STYLE),
    ], style=PAGE_STYLE)


# ── Upload callbacks ──────────────────────────────────────────────────────────

@callback(
    Output("questions-filename", "children"),
    Output("store-questions",    "data"),
    Input("upload-questions",    "contents"),
    State("upload-questions",    "filename"),
    prevent_initial_call=True,
)
def store_questions(contents, filename):
    if contents is None:
        return "", None
    return f"✓ {filename}", {"contents": contents, "filename": filename}


@callback(
    Output("scheme-filename", "children"),
    Output("store-scheme",    "data"),
    Input("upload-scheme",    "contents"),
    State("upload-scheme",    "filename"),
    prevent_initial_call=True,
)
def store_scheme(contents, filename):
    if contents is None:
        return "", None
    return f"✓ {filename}", {"contents": contents, "filename": filename}


@callback(
    Output("upload-status", "children"),
    Output("upload-status", "style"),
    Input("btn-upload",     "n_clicks"),
    State("store-questions", "data"),
    State("store-scheme",    "data"),
    prevent_initial_call=True,
)
def run_upload(n_clicks, q_data, s_data):
    if not q_data:
        return "Please select a questions PDF first.", {
            "marginLeft": "1.25rem", "fontSize": "0.78rem",
            "color": ERROR, "fontFamily": FONT_BODY,
        }

    def decode_upload(data):
        """Strip data URL prefix and return raw bytes."""
        import base64
        content_string = data["contents"]
        content_type, content_b64 = content_string.split(",", 1)
        return base64.b64decode(content_b64), data["filename"]

    try:
        # Upload questions PDF
        q_bytes, q_name = decode_upload(q_data)
        resp = requests.post(
            f"{API_BASE}/api/upload",
            headers=HEADERS,
            files={"file": (q_name, q_bytes, "application/pdf")},
            data={"folder": "questions"},
            timeout=60,
        )
        resp.raise_for_status()
        q_path = resp.json()["storage_path"]

        # Upload scheme PDF if provided
        s_path = None
        if s_data:
            s_bytes, s_name = decode_upload(s_data)
            resp = requests.post(
                f"{API_BASE}/api/upload",
                headers=HEADERS,
                files={"file": (s_name, s_bytes, "application/pdf")},
                data={"folder": "marking_schemes"},
                timeout=60,
            )
            resp.raise_for_status()
            s_path = resp.json()["storage_path"]

        # Trigger extraction in background — pipeline runs server-side
        # We don't consume the SSE stream from the portal; status is
        # tracked via the jobs table and polled by the history table.
        payload = {"questions_path": q_path}
        if s_path:
            payload["scheme_path"] = s_path

        import threading

        def _fire():
            try:
                with requests.post(
                    f"{API_BASE}/api/extract",
                    headers={**HEADERS, "Accept": "text/event-stream"},
                    json=payload,
                    stream=True,
                    timeout=600,  # 10 min ceiling for large papers
                ) as resp:
                    for line in resp.iter_lines():
                        pass  # drain the stream so server completes
            except Exception:
                pass

        threading.Thread(target=_fire, daemon=True).start()

    except requests.exceptions.Timeout:
        # Extraction started — timeout is expected for SSE
        pass
    except Exception as e:
        return f"Error: {str(e)}", {
            "marginLeft": "1.25rem", "fontSize": "0.78rem",
            "color": ERROR, "fontFamily": FONT_BODY,
        }

    return "✓ Uploaded — extraction running in background.", {
        "marginLeft": "1.25rem", "fontSize": "0.78rem",
        "color": SUCCESS, "fontFamily": FONT_BODY,
    }


# ── Upload history table ──────────────────────────────────────────────────────

@callback(
    Output("upload-history-table", "children"),
    Input("history-refresh",       "n_intervals"),
    Input("url",                   "pathname"),
)
def refresh_history(n, pathname):
    if pathname not in ("/", "/upload"):
        return no_update
    try:
        resp = requests.get(
            f"{API_BASE}/api/jobs",
            headers=HEADERS,
            params={"limit": 20},
            timeout=10,
        )
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
    except Exception:
        return html.P("Could not load history — is the API running?",
                      style={"color": ERROR, "fontSize": "0.8rem"})

    if not jobs:
        return html.P("No uploads yet.", style={"color": "#9CA3AF", "fontSize": "0.8rem"})

    rows = [{
        "Job ID":       j.get("id", "")[:8] + "…",
        "Questions":    j.get("questions_pdf_path", "—").split("/")[-1],
        "Scheme":       (j.get("scheme_pdf_path") or "—").split("/")[-1],
        "Exam Type":    j.get("exam_type") or "—",
        "Status":       status_badge(j.get("status", "—")),
        "Pages":        j.get("total_pages", "—"),
        "Submitted":    _fmt_dt(j.get("created_at")),
    } for j in jobs]

    return dash_table.DataTable(
        data=rows,
        columns=[{"name": c, "id": c} for c in rows[0].keys()],
        style_table={"overflowX": "auto"},
        style_header_conditional=TABLE_HEADER_STYLE,
        style_data_conditional=TABLE_CELL_STYLE,
        style_cell={**TABLE_STYLE, "textAlign": "left", "border": "none"},
        style_header={
            "backgroundColor": NAVY,
            "color":           ACCENT,
            "fontWeight":      "500",
            "letterSpacing":   "0.08em",
            "textTransform":   "uppercase",
            "fontSize":        "0.72rem",
            "border":          "none",
        },
        page_size=10,
        filter_action="native",
        sort_action="native",
        style_filter=TABLE_FILTER_STYLE,
    )


# ── Records table ─────────────────────────────────────────────────────────────

@callback(
    Output("records-table", "children"),
    Output("records-stats", "children"),
    Input("records-refresh", "n_intervals"),
    Input("url",             "pathname"),
)
def refresh_records(n, pathname):
    if pathname != "/records":
        return no_update, no_update

    try:
        resp = requests.get(
            f"{API_BASE}/api/jobs",
            headers=HEADERS,
            params={"limit": 200},
            timeout=10,
        )
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
    except Exception:
        return (
            html.P("Could not load records — is the API running?",
                   style={"color": ERROR, "fontSize": "0.8rem"}),
            no_update,
        )

    # Stats strip
    total    = len(jobs)
    complete = sum(1 for j in jobs if j.get("status") == "complete")
    partial  = sum(1 for j in jobs if j.get("status") == "partial")
    failed   = sum(1 for j in jobs if j.get("status") == "failed")
    total_q  = sum(j.get("questions_extracted", 0) for j in jobs)

    def stat_card(label, value, color=NAVY):
        return html.Div([
            html.Div(str(value), style={
                "fontFamily": FONT_DISPLAY,
                "fontSize":   "2rem",
                "color":      color,
                "lineHeight": "1",
            }),
            html.Div(label, style={
                "fontSize":      "0.7rem",
                "letterSpacing": "0.1em",
                "textTransform": "uppercase",
                "color":         "#6B7280",
                "marginTop":     "0.25rem",
            }),
        ], style={
            **CARD_STYLE,
            "padding":       "1.25rem 1.5rem",
            "marginBottom":  "0",
            "display":       "inline-block",
            "marginRight":   "1rem",
            "minWidth":      "120px",
            "textAlign":     "center",
        })

    stats = html.Div([
        stat_card("Total Jobs",  total),
        stat_card("Complete",    complete, SUCCESS),
        stat_card("Partial",     partial,  WARNING),
        stat_card("Failed",      failed,   ERROR),
        stat_card("Questions",   total_q,  ACCENT2),
    ], style={"marginBottom": "1.5rem"})

    if not jobs:
        return html.P("No records yet.", style={"color": "#9CA3AF", "fontSize": "0.8rem"}), stats

    rows = [{
        "Job ID":       j.get("id", "")[:8] + "…",
        "Exam Type":    j.get("exam_type") or "—",
        "Status":       status_badge(j.get("status", "—")),
        "Questions":    j.get("questions_extracted", 0),
        "Schemes":      j.get("schemes_extracted", 0),
        "Native Pages": j.get("native_pages", 0),
        "Image Pages":  j.get("image_pages", 0),
        "Total Pages":  j.get("total_pages", 0),
        "Started":      _fmt_dt(j.get("started_at")),
        "Completed":    _fmt_dt(j.get("completed_at")),
        "Error":        (j.get("error_message") or "")[:60] or "—",
    } for j in jobs]

    table = dash_table.DataTable(
        data=rows,
        columns=[{"name": c, "id": c} for c in rows[0].keys()],
        style_table={"overflowX": "auto"},
        style_cell={**TABLE_STYLE, "textAlign": "left", "border": "none", "minWidth": "80px"},
        style_header={
            "backgroundColor": NAVY,
            "color":           ACCENT,
            "fontWeight":      "500",
            "letterSpacing":   "0.08em",
            "textTransform":   "uppercase",
            "fontSize":        "0.72rem",
            "border":          "none",
        },
        style_data_conditional=[
            {"if": {"filter_query": '{Status} contains "complete"'},
             "color": SUCCESS},
            {"if": {"filter_query": '{Status} contains "partial"'},
             "color": WARNING},
            {"if": {"filter_query": '{Status} contains "failed"'},
             "color": ERROR},
            {"if": {"row_index": "odd"},
             "backgroundColor": PAPER},
        ],
        page_size=20,
        filter_action="native",
        sort_action="native",
        style_filter=TABLE_FILTER_STYLE,
        export_format="csv",
    )

    return table, stats


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_dt(iso_str: str) -> str:
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y %H:%M")
    except Exception:
        return iso_str


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=8050)