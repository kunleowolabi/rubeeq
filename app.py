"""
app.py — Rubeeq Extraction Engine — Admin Portal
Two-page Dash application:
    Page 1 /upload  — upload question + scheme PDFs, view upload history
    Page 2 /records — view all processed extraction jobs
"""

import dash
from dash import dcc, html, dash_table, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc
import requests
import os
import threading
from datetime import datetime
from decouple import config as env

API_BASE = env("API_BASE_URL", default="http://localhost:8000")
API_KEY  = env("ADMIN_API_KEY", default="")
HEADERS  = {"X-API-Key": API_KEY}

# ── Fonts & external ──────────────────────────────────────────────────────────

EXTERNAL_STYLESHEETS = [
    dbc.themes.BOOTSTRAP,
    "https://fonts.googleapis.com/css2?family=Raleway:wght@300;400;500;600&display=swap",
]

# ── Colour tokens ─────────────────────────────────────────────────────────────

BG       = "#0A0F1E"       # deep navy — sidebar/background
SURFACE  = "#F7F6F2"       # warm off-white — floating card
INK      = "#0A0F1E"       # text on surface
MUTED    = "#9098A8"       # secondary text
BORDER   = "#E4E2DC"       # card borders
ACCENT   = "#0A0F1E"       # buttons — same as BG for monochrome feel
WHITE    = "#FFFFFF"
SUCCESS  = "#2A6049"
WARNING  = "#8A5C00"
ERROR    = "#7A1F1F"
RUNNING  = "#1A4A7A"

FONT = "Raleway, sans-serif"

# ── Global styles ─────────────────────────────────────────────────────────────

ROOT_STYLE = {
    "fontFamily": FONT,
    "height":     "100vh",
    "overflow":   "hidden",
    "backgroundColor": BG,
}

SIDEBAR_STYLE = {
    "position":   "fixed",
    "top":        0,
    "left":       0,
    "bottom":     0,
    "width":      "200px",
    "padding":    "2rem 1.5rem",
    "display":    "flex",
    "flexDirection": "column",
    "justifyContent": "space-between",
    "zIndex":     100,
}

MAIN_STYLE = {
    "marginLeft":    "200px",
    "height":        "100vh",
    "padding":       "1.25rem 1.25rem 1.25rem 0",
    "boxSizing":     "border-box",
}

CARD_STYLE = {
    "backgroundColor": SURFACE,
    "borderRadius":    "16px",
    "height":          "100%",
    "overflowY":       "auto",
    "padding":         "2.5rem 3rem",
    "boxSizing":       "border-box",
}

SECTION_CARD = {
    "backgroundColor": WHITE,
    "borderRadius":    "10px",
    "border":          f"1px solid {BORDER}",
    "padding":         "1.75rem 2rem",
    "marginBottom":    "1.25rem",
}

LABEL_STYLE = {
    "fontSize":      "0.68rem",
    "fontWeight":    "600",
    "letterSpacing": "0.12em",
    "textTransform": "uppercase",
    "color":         MUTED,
    "marginBottom":  "0.5rem",
    "display":       "block",
    "fontFamily":    FONT,
}

HEADING_STYLE = {
    "fontFamily":  FONT,
    "fontWeight":  "600",
    "color":       INK,
    "fontSize":    "1.4rem",
    "marginBottom": "0.2rem",
    "letterSpacing": "-0.3px",
}

SUBHEADING_STYLE = {
    "fontFamily":  FONT,
    "fontWeight":  "500",
    "color":       INK,
    "fontSize":    "0.95rem",
    "marginBottom": "1.25rem",
}

BTN_STYLE = {
    "backgroundColor": BG,
    "color":           WHITE,
    "border":          "none",
    "borderRadius":    "6px",
    "fontFamily":      FONT,
    "fontWeight":      "500",
    "fontSize":        "0.78rem",
    "letterSpacing":   "0.08em",
    "padding":         "0.6rem 1.5rem",
    "cursor":          "pointer",
    "textTransform":   "uppercase",
}

NAV_BASE = {
    "display":       "block",
    "fontFamily":    FONT,
    "fontSize":      "0.75rem",
    "fontWeight":    "500",
    "letterSpacing": "0.1em",
    "textTransform": "uppercase",
    "textDecoration": "none",
    "padding":       "0.5rem 0.75rem",
    "borderRadius":  "6px",
    "marginBottom":  "0.25rem",
    "transition":    "all 0.15s",
}

NAV_INACTIVE = {**NAV_BASE, "color": "rgba(255,255,255,0.45)"}
NAV_ACTIVE   = {**NAV_BASE, "color": WHITE, "backgroundColor": "rgba(255,255,255,0.1)"}

TABLE_STYLE = {
    "fontFamily": FONT,
    "fontSize":   "0.78rem",
    "color":      INK,
}

TABLE_HEADER = {
    "backgroundColor": SURFACE,
    "color":           MUTED,
    "fontWeight":      "600",
    "fontSize":        "0.65rem",
    "letterSpacing":   "0.12em",
    "textTransform":   "uppercase",
    "border":          "none",
    "borderBottom":    f"1px solid {BORDER}",
    "padding":         "0.6rem 0.75rem",
}

TABLE_CELL = {
    "border":          "none",
    "borderBottom":    f"1px solid {BORDER}",
    "padding":         "0.65rem 0.75rem",
    "backgroundColor": WHITE,
}

# ── Logo SVG (icon only — logo1.svg adapted inline) ───────────────────────────


LOGO_ICON = html.Img(
    src="/assets/logo1.svg",
    style={"width": "40px", "height": "40px", "filter": "brightness(0) invert(1)"}
)

# ── Sidebar ───────────────────────────────────────────────────────────────────

def sidebar(active: str):
    nav_items = [
        ("/upload",  "Upload"),
        ("/records", "Records"),
    ]
    return html.Div([
        # Top — logo + nav
        html.Div([
            html.Div([
                LOGO_ICON,
                html.Span("Rubeeq", style={
                    "color":       WHITE,
                    "fontFamily":  FONT,
                    "fontWeight":  "600",
                    "fontSize":    "1rem",
                    "marginLeft":  "0.6rem",
                    "letterSpacing": "-0.2px",
                }),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "2.5rem"}),

            html.Div([
                html.A(label, href=href,
                       style=NAV_ACTIVE if active == href else NAV_INACTIVE)
                for href, label in nav_items
            ]),
        ]),

        # Bottom — version
        html.Div("v1.0.0", style={
            "color":      "rgba(255,255,255,0.25)",
            "fontSize":   "0.68rem",
            "fontFamily": FONT,
            "letterSpacing": "0.05em",
        }),
    ], style=SIDEBAR_STYLE)


# ── Status helpers ────────────────────────────────────────────────────────────

STATUS_COLORS = {
    "complete": SUCCESS,
    "partial":  WARNING,
    "failed":   ERROR,
    "running":  RUNNING,
    "pending":  MUTED,
}

def status_dot(status: str) -> str:
    s = (status or "").lower()
    dot = {"complete": "●", "partial": "◐", "failed": "○", "running": "◌"}.get(s, "·")
    return f"{dot} {status}"


def _fmt_dt(iso_str):
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y %H:%M")
    except Exception:
        return iso_str


# ── Page shell ────────────────────────────────────────────────────────────────

def page_shell(active: str, content):
    return html.Div([
        sidebar(active),
        html.Div([
            html.Div(content, style=CARD_STYLE),
        ], style=MAIN_STYLE),
    ], style=ROOT_STYLE)


# ── Upload zone component ─────────────────────────────────────────────────────

def upload_zone(upload_id, label, optional=False):
    return html.Div([
        html.Span(label + (" (optional)" if optional else ""), style=LABEL_STYLE),
        dcc.Upload(
            id=upload_id,
            children=html.Div([
                html.Div("↑", style={
                    "fontSize":    "1.3rem",
                    "color":       MUTED,
                    "marginBottom": "0.4rem",
                }),
                html.Div("Drop or click to browse",
                         style={"fontSize": "0.78rem", "color": MUTED}),
                html.Div("PDF only", style={
                    "fontSize":  "0.68rem",
                    "color":     BORDER,
                    "marginTop": "0.2rem",
                }),
            ], style={"textAlign": "center", "padding": "1.5rem 0"}),
            style={
                "border":          f"1.5px dashed {BORDER}",
                "borderRadius":    "8px",
                "cursor":          "pointer",
                "backgroundColor": SURFACE,
            },
            accept=".pdf",
        ),
    ])


# ── PAGE 1: UPLOAD ────────────────────────────────────────────────────────────

def layout_upload():
    content = html.Div([

        # Page header
        html.Div([
            html.H2("Upload", style=HEADING_STYLE),
            html.P("Submit exam papers for extraction.",
                   style={"color": MUTED, "fontSize": "0.82rem",
                          "marginBottom": "1.75rem", "fontFamily": FONT}),
        ]),

        # Upload section
        html.Div([
            html.H4("Documents", style=SUBHEADING_STYLE),
            dbc.Row([
                dbc.Col(upload_zone("upload-questions", "Questions PDF"), md=6),
                dbc.Col(upload_zone("upload-scheme", "Marking Scheme", optional=True), md=6),
            ], style={"marginBottom": "1rem"}),

            # Filename confirmations
            dbc.Row([
                dbc.Col(html.Div(id="questions-filename", style={
                    "fontSize": "0.73rem", "color": SUCCESS,
                    "fontFamily": FONT, "minHeight": "1.2rem",
                }), md=6),
                dbc.Col(html.Div(id="scheme-filename", style={
                    "fontSize": "0.73rem", "color": SUCCESS,
                    "fontFamily": FONT, "minHeight": "1.2rem",
                }), md=6),
            ], style={"marginBottom": "1.25rem"}),

            html.Div([
                html.Button("Upload & Extract", id="btn-upload",
                            n_clicks=0, style=BTN_STYLE),
                html.Span(id="upload-status", style={
                    "marginLeft": "1rem",
                    "fontSize":   "0.75rem",
                    "fontFamily": FONT,
                    "color":      MUTED,
                }),
            ], style={"display": "flex", "alignItems": "center"}),

            dcc.Store(id="store-questions"),
            dcc.Store(id="store-scheme"),

        ], style=SECTION_CARD),

        # History section
        html.Div([
            html.H4("Recent Uploads", style=SUBHEADING_STYLE),
            html.Div(id="upload-history-table"),
            dcc.Interval(id="history-refresh", interval=15_000, n_intervals=0),
        ], style=SECTION_CARD),

    ])
    return page_shell("/upload", content)


# ── PAGE 2: RECORDS ───────────────────────────────────────────────────────────

def layout_records():
    content = html.Div([

        html.Div([
            html.H2("Records", style=HEADING_STYLE),
            html.P("All extraction jobs and their outputs.",
                   style={"color": MUTED, "fontSize": "0.82rem",
                          "marginBottom": "1.75rem", "fontFamily": FONT}),
        ]),

        # Stats row
        html.Div(id="records-stats", style={"marginBottom": "1.25rem"}),

        # Table section
        html.Div([
            html.H4("All Jobs", style=SUBHEADING_STYLE),
            html.Div(id="records-table"),
            dcc.Interval(id="records-refresh", interval=20_000, n_intervals=0),
        ], style=SECTION_CARD),

    ])
    return page_shell("/records", content)


# ── App ───────────────────────────────────────────────────────────────────────

app = dash.Dash(
    __name__,
    external_stylesheets=EXTERNAL_STYLESHEETS,
    suppress_callback_exceptions=True,
    title="Rubeeq",
)
app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        <link rel="icon" type="image/svg+xml" href="/assets/logo1.svg?v=3" sizes="96x96">
        {%css%}
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { overflow: hidden; background: ''' + BG + '''; }
            ::-webkit-scrollbar { width: 4px; }
            ::-webkit-scrollbar-track { background: transparent; }
            ::-webkit-scrollbar-thumb { background: ''' + BORDER + '''; border-radius: 2px; }
            .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner td,
            .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner th {
                font-family: Raleway, sans-serif !important;
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''
server = app.server

app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    html.Div(id="page-content"),
])


# ── Router ────────────────────────────────────────────────────────────────────

@callback(Output("page-content", "children"), Input("url", "pathname"))
def display_page(pathname):
    if pathname in ("/", "/upload"):
        return layout_upload()
    if pathname == "/records":
        return layout_records()
    return page_shell("/", html.Div([
        html.H2("404", style=HEADING_STYLE),
        html.P("Page not found.", style={"color": MUTED, "fontFamily": FONT}),
    ]))


# ── Upload callbacks ──────────────────────────────────────────────────────────

@callback(
    Output("questions-filename", "children"),
    Output("store-questions",    "data"),
    Input("upload-questions",    "contents"),
    State("upload-questions",    "filename"),
    prevent_initial_call=True,
)
def store_questions(contents, filename):
    if not contents:
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
    if not contents:
        return "", None
    return f"✓ {filename}", {"contents": contents, "filename": filename}


@callback(
    Output("upload-status", "children"),
    Output("upload-status", "style"),
    Input("btn-upload",      "n_clicks"),
    State("store-questions", "data"),
    State("store-scheme",    "data"),
    prevent_initial_call=True,
)
def run_upload(n_clicks, q_data, s_data):
    base_style = {
        "marginLeft": "1rem",
        "fontSize":   "0.75rem",
        "fontFamily": FONT,
    }

    if not q_data:
        return "Select a questions PDF first.", {**base_style, "color": ERROR}

    def decode(data):
        import base64
        _, b64 = data["contents"].split(",", 1)
        return base64.b64decode(b64), data["filename"]

    try:
        q_bytes, q_name = decode(q_data)
        resp = requests.post(
            f"{API_BASE}/api/upload",
            headers=HEADERS,
            files={"file": (q_name, q_bytes, "application/pdf")},
            data={"folder": "questions"},
            timeout=60,
        )
        resp.raise_for_status()
        q_path = resp.json()["storage_path"]

        s_path = None
        if s_data:
            s_bytes, s_name = decode(s_data)
            resp = requests.post(
                f"{API_BASE}/api/upload",
                headers=HEADERS,
                files={"file": (s_name, s_bytes, "application/pdf")},
                data={"folder": "marking_schemes"},
                timeout=60,
            )
            resp.raise_for_status()
            s_path = resp.json()["storage_path"]

        payload = {"questions_path": q_path}
        if s_path:
            payload["scheme_path"] = s_path

        def _fire():
            try:
                # Fire extraction as a non-streaming POST.
                # Portal tracks status via polling — SSE kept for API customers only.
                requests.post(
                    f"{API_BASE}/api/extract",
                    headers=HEADERS,
                    json=payload,
                    timeout=5,
                )
            except requests.exceptions.Timeout:
                pass  # Expected — pipeline runs async server-side
            except Exception:
                pass

        threading.Thread(target=_fire, daemon=True).start()

    except Exception as e:
        return f"Error: {e}", {**base_style, "color": ERROR}

    return "Uploaded — extraction running.", {**base_style, "color": SUCCESS}


# ── History table ─────────────────────────────────────────────────────────────

@callback(
    Output("upload-history-table", "children"),
    Input("history-refresh",       "n_intervals"),
    Input("url",                   "pathname"),
)
def refresh_history(n, pathname):
    if pathname not in ("/", "/upload"):
        return no_update
    try:
        resp = requests.get(f"{API_BASE}/api/jobs", headers=HEADERS,
                            params={"limit": 20}, timeout=10)
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
    except Exception:
        return html.P("API unavailable.", style={
            "color": ERROR, "fontSize": "0.78rem", "fontFamily": FONT
        })

    if not jobs:
        return html.P("No uploads yet.", style={
            "color": MUTED, "fontSize": "0.78rem", "fontFamily": FONT
        })

    rows = [{
        "Job":       j.get("id", "")[:8] + "…",
        "Questions": (j.get("questions_pdf_path") or "").split("/")[-1],
        "Scheme":    ((j.get("scheme_pdf_path") or "") or "—").split("/")[-1],
        "Type":      j.get("exam_type") or "—",
        "Status":    status_dot(j.get("status", "—")),
        "Pages":     j.get("total_pages") or "—",
        "Submitted": _fmt_dt(j.get("created_at")),
    } for j in jobs]

    return dash_table.DataTable(
        data=rows,
        columns=[{"name": c, "id": c} for c in rows[0]],
        style_table={"overflowX": "auto"},
        style_cell={**TABLE_STYLE, "textAlign": "left", "border": "none",
                    "padding": "0.6rem 0.75rem"},
        style_header=TABLE_HEADER,
        style_data=TABLE_CELL,
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": SURFACE},
        ],
        page_size=8,
        sort_action="native",
        style_as_list_view=True,
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
        resp = requests.get(f"{API_BASE}/api/jobs", headers=HEADERS,
                            params={"limit": 200}, timeout=10)
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
    except Exception:
        return (
            html.P("API unavailable.", style={
                "color": ERROR, "fontSize": "0.78rem", "fontFamily": FONT
            }),
            no_update,
        )

    total    = len(jobs)
    complete = sum(1 for j in jobs if j.get("status") == "complete")
    failed   = sum(1 for j in jobs if j.get("status") == "failed")
    total_q  = sum(j.get("questions_extracted", 0) for j in jobs)

    def stat(label, value, color=INK):
        return html.Div([
            html.Div(str(value), style={
                "fontFamily":  FONT,
                "fontWeight":  "600",
                "fontSize":    "1.6rem",
                "color":       color,
                "lineHeight":  "1",
            }),
            html.Div(label, style={
                "fontFamily":    FONT,
                "fontSize":      "0.65rem",
                "fontWeight":    "600",
                "letterSpacing": "0.1em",
                "textTransform": "uppercase",
                "color":         MUTED,
                "marginTop":     "0.2rem",
            }),
        ], style={
            "backgroundColor": WHITE,
            "border":          f"1px solid {BORDER}",
            "borderRadius":    "8px",
            "padding":         "1rem 1.25rem",
            "marginRight":     "0.75rem",
            "minWidth":        "100px",
            "display":         "inline-block",
        })

    stats = html.Div([
        stat("Total",     total),
        stat("Complete",  complete, SUCCESS),
        stat("Failed",    failed,   ERROR),
        stat("Questions", total_q,  RUNNING),
    ])

    if not jobs:
        return html.P("No records yet.", style={
            "color": MUTED, "fontSize": "0.78rem", "fontFamily": FONT
        }), stats

    rows = [{
        "Job":       j.get("id", "")[:8] + "…",
        "Type":      j.get("exam_type") or "—",
        "Status":    status_dot(j.get("status", "—")),
        "Questions": j.get("questions_extracted", 0),
        "Schemes":   j.get("schemes_extracted",   0),
        "Pages":     j.get("total_pages",         0),
        "Started":   _fmt_dt(j.get("started_at")),
        "Completed": _fmt_dt(j.get("completed_at")),
        "Error":     (j.get("error_message") or "—")[:50],
    } for j in jobs]

    table = dash_table.DataTable(
        data=rows,
        columns=[{"name": c, "id": c} for c in rows[0]],
        style_table={"overflowX": "auto"},
        style_cell={**TABLE_STYLE, "textAlign": "left",
                    "border": "none", "padding": "0.6rem 0.75rem",
                    "minWidth": "70px"},
        style_header=TABLE_HEADER,
        style_data=TABLE_CELL,
        style_data_conditional=[
            {"if": {"filter_query": '{Status} contains "complete"'},
             "color": SUCCESS},
            {"if": {"filter_query": '{Status} contains "failed"'},
             "color": ERROR},
            {"if": {"filter_query": '{Status} contains "running"'},
             "color": RUNNING},
            {"if": {"row_index": "odd"},
             "backgroundColor": SURFACE},
        ],
        page_size=15,
        sort_action="native",
        filter_action="native",
        export_format="csv",
        style_as_list_view=True,
    )

    return table, stats


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=8050)