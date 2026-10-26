"""
Dashboard interativo - 2ª Auditoria da 3ª CJM (STM)

Requisitos:
    pip install dash plotly pandas

Rodar:
    python dashboard_app.py
    -> abre em http://127.0.0.1:8050
"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
DIR_DADOS = Path(__file__).resolve().parent / "planilhas"
CSV_PATH = DIR_DADOS / "2a_auditoria_3a_cjm.csv"

INDICADORES = {
    "ind1": {"label": "Casos novos", "tipo": "fluxo"},
    "ind8a": {"label": "Julgados", "tipo": "fluxo"},
    "TBaixArq": {"label": "Baixados/arquivados", "tipo": "fluxo"},
    "SentPri": {"label": "1ª ocorrência de julgamento", "tipo": "fluxo"},
    "ind3": {"label": "Suspensos", "tipo": "fluxo"},
    "ind2": {"label": "Pendentes (total)", "tipo": "estoque"},
    "CPJulg": {"label": "Pendentes não julgados", "tipo": "estoque"},
}

CORES = {
    "azul": "#2a78d6",
    "roxo": "#4a3aa7",
    "verde": "#1baf7a",
    "laranja": "#eb6834",
    "vermelho": "#e34948",
    "cinza_fundo": "#f4f3ef",
    "cinza_texto": "#666666",
}

COR_INDICADOR = {
    "ind1": CORES["azul"],
    "ind8a": CORES["roxo"],
    "TBaixArq": CORES["verde"],
    "SentPri": CORES["laranja"],
    "ind3": CORES["vermelho"],
    "ind2": CORES["laranja"],
    "CPJulg": CORES["vermelho"],
}

PROC_CORES = {
    "Conhecimento criminal": "#2a78d6",
    "Fase investigatória": "#eb6834",
    "Outros": "#1baf7a",
    "Execução penal não privativa de liberdade": "#eda100",
    "Execução penal privativa de liberdade": "#e34948",
}

FONTE = "Arial, Helvetica, sans-serif"


# ---------------------------------------------------------------------------
# Carga e preparação
# ---------------------------------------------------------------------------
def carregar_dados() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH, sep=";")
    df["data"] = pd.to_datetime(df["anomes"].astype(str), format="%Y%m")
    df["trimestre"] = df["data"].dt.to_period("Q")
    for c in ["ind1", "ind3", "TBaixArq", "ind8a", "SentPri"]:
        if c in df.columns:
            df[c] = df[c].fillna(0)
    return df


def rotulo_trimestre(periodo: pd.Period) -> str:
    return f"{periodo.year}-T{periodo.quarter}"


df = carregar_dados()
procedimentos = sorted(df["procedimento"].dropna().unique().tolist())
trimestres_ordenados = sorted(df["trimestre"].unique())
meses_ordenados = sorted(df["data"].unique())

FLUXO_COLS = [k for k, v in INDICADORES.items() if v["tipo"] == "fluxo"]
ESTOQUE_COLS = [k for k, v in INDICADORES.items() if v["tipo"] == "estoque"]


def agrega(dff: pd.DataFrame, granularidade: str) -> pd.DataFrame:
    chave = "trimestre" if granularidade == "trimestral" else "data"

    soma_fluxo = dff.groupby(chave)[FLUXO_COLS].sum(min_count=1)

    if granularidade == "trimestral":
        # Estoque = foto do último mês de cada trimestre (não soma)
        ultimo = dff.sort_values("data").groupby(chave)["data"].max().reset_index()
        snap = dff.merge(ultimo, on=[chave, "data"])
        soma_estoque = snap.groupby(chave)[ESTOQUE_COLS].sum(min_count=1)
    else:
        # Granularidade mensal: cada grupo já é um único mês, sem necessidade de snapshot
        soma_estoque = dff.groupby(chave)[ESTOQUE_COLS].sum(min_count=1)

    out = soma_fluxo.join(soma_estoque).reset_index().sort_values(chave)
    if granularidade == "trimestral":
        out["rotulo"] = out["trimestre"].apply(rotulo_trimestre)
    else:
        out["rotulo"] = out["data"].dt.strftime("%Y-%m")
    return out


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = Dash(__name__)
app.title = "2ª Auditoria da 3ª CJM — Indicadores"

CARD_ESTILO_BASE = {
    "flex": "1",
    "background": CORES["cinza_fundo"],
    "borderRadius": "10px",
    "padding": "14px 18px",
    "borderTop": "3px solid transparent",
}

app.layout = html.Div(
    style={
        "fontFamily": FONTE,
        "maxWidth": "1160px",
        "margin": "0 auto",
        "padding": "32px 24px",
        "color": "#1a1a1a",
    },
    children=[
        html.Div(
            style={"marginBottom": "24px"},
            children=[
                html.H1(
                    "2ª Auditoria da 3ª CJM (STM)",
                    style={"fontSize": "24px", "fontWeight": "600", "margin": "0 0 4px"},
                ),
                html.P(
                    "Indicadores processuais — fonte: tbl_fato_R (CNJ/DataJud)",
                    style={"color": CORES["cinza_texto"], "fontSize": "13px", "margin": 0},
                ),
            ],
        ),

        html.Div(
            style={
                "display": "flex", "gap": "20px", "marginBottom": "24px",
                "flexWrap": "wrap", "alignItems": "flex-end",
            },
            children=[
                html.Div(
                    style={"flex": "2", "minWidth": "240px"},
                    children=[
                        html.Label("Indicador", style={"fontSize": "12px", "color": CORES["cinza_texto"], "fontWeight": "600"}),
                        dcc.Dropdown(
                            id="indicador-dropdown",
                            options=[{"label": v["label"], "value": k} for k, v in INDICADORES.items()],
                            value="ind1",
                            clearable=False,
                        ),
                    ],
                ),
                html.Div(
                    style={"flex": "2", "minWidth": "240px"},
                    children=[
                        html.Label("Tipo de procedimento", style={"fontSize": "12px", "color": CORES["cinza_texto"], "fontWeight": "600"}),
                        dcc.Dropdown(
                            id="procedimento-dropdown",
                            options=[{"label": "Todos (soma)", "value": "TODOS"}]
                            + [{"label": p, "value": p} for p in procedimentos],
                            value="TODOS",
                            clearable=False,
                        ),
                    ],
                ),
                html.Div(
                    style={"flex": "1", "minWidth": "180px"},
                    children=[
                        html.Label("Granularidade", style={"fontSize": "12px", "color": CORES["cinza_texto"], "fontWeight": "600"}),
                        dcc.RadioItems(
                            id="granularidade-radio",
                            options=[
                                {"label": " Trimestral", "value": "trimestral"},
                                {"label": " Mensal", "value": "mensal"},
                            ],
                            value="trimestral",
                            style={"display": "flex", "gap": "12px", "marginTop": "6px", "fontSize": "13px"},
                            inputStyle={"marginRight": "4px"},
                        ),
                    ],
                ),
            ],
        ),

        html.Div(id="kpi-cards", style={"display": "flex", "gap": "12px", "marginBottom": "24px", "flexWrap": "wrap"}),

        html.Div(
            style={
                "background": "white", "border": "1px solid #e5e4de", "borderRadius": "12px",
                "padding": "16px", "marginBottom": "24px",
            },
            children=[dcc.Graph(id="grafico-principal", config={"displayModeBar": False})],
        ),

        html.H2("Composição de casos novos por tipo de procedimento",
                style={"fontSize": "16px", "fontWeight": "600", "margin": "0 0 12px"}),
        html.Div(
            style={
                "background": "white", "border": "1px solid #e5e4de", "borderRadius": "12px",
                "padding": "16px",
            },
            children=[dcc.Graph(id="grafico-composicao", config={"displayModeBar": False})],
        ),
    ],
)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------
@app.callback(
    Output("grafico-principal", "figure"),
    Output("grafico-composicao", "figure"),
    Output("kpi-cards", "children"),
    Input("indicador-dropdown", "value"),
    Input("procedimento-dropdown", "value"),
    Input("granularidade-radio", "value"),
)
def atualizar(indicador, procedimento, granularidade):
    dff = df if procedimento == "TODOS" else df[df["procedimento"] == procedimento]
    agr = agrega(dff, granularidade)

    tipo = INDICADORES[indicador]["tipo"]
    cor = COR_INDICADOR[indicador]
    nome = INDICADORES[indicador]["label"]

    def hex_para_rgba(hex_cor: str, alpha: float) -> str:
        h = hex_cor.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"

    fig = go.Figure()
    if tipo == "fluxo":
        fig.add_trace(go.Bar(x=agr["rotulo"], y=agr[indicador], marker_color=cor, name=nome))
    else:
        fig.add_trace(go.Scatter(
            x=agr["rotulo"], y=agr[indicador], mode="lines+markers",
            line=dict(color=cor, width=2.5), marker=dict(size=6),
            fill="tozeroy", fillcolor=hex_para_rgba(cor, 0.08),
            name=nome,
        ))

    unidade = "trimestre" if granularidade == "trimestral" else "mês"
    fig.update_layout(
        title=dict(text=f"{nome} por {unidade}", font=dict(size=15, family=FONTE)),
        template="plotly_white",
        font=dict(family=FONTE, size=12, color="#1a1a1a"),
        margin=dict(l=40, r=20, t=50, b=60),
        height=380,
        showlegend=False,
        xaxis=dict(tickangle=-45, showgrid=False),
        yaxis=dict(gridcolor="#eeeee6"),
        bargap=0.3,
    )

    # Gráfico de composição por procedimento (sempre casos novos = ind1)
    chave = "trimestre" if granularidade == "trimestral" else "data"
    piv = df.pivot_table(index=chave, columns="procedimento", values="ind1", aggfunc="sum").sort_index()
    if granularidade == "trimestral":
        rotulos = [rotulo_trimestre(p) for p in piv.index]
    else:
        rotulos = [d.strftime("%Y-%m") for d in piv.index]

    fig2 = go.Figure()
    for col in piv.columns:
        fig2.add_trace(go.Bar(
            x=rotulos, y=piv[col].fillna(0), name=col,
            marker_color=PROC_CORES.get(col, "#999999"),
        ))
    fig2.update_layout(
        barmode="stack",
        template="plotly_white",
        font=dict(family=FONTE, size=12, color="#1a1a1a"),
        margin=dict(l=40, r=20, t=20, b=60),
        height=340,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=11)),
        xaxis=dict(tickangle=-45, showgrid=False),
        yaxis=dict(gridcolor="#eeeee6"),
        bargap=0.3,
    )

    ultimo = agr[indicador].iloc[-1] if len(agr) else 0
    media = agr[indicador].mean() if len(agr) else 0
    total = agr[indicador].sum() if len(agr) else 0

    def card(label, valor, cor_borda):
        estilo = dict(CARD_ESTILO_BASE)
        estilo["borderTop"] = f"3px solid {cor_borda}"
        return html.Div(
            style=estilo,
            children=[
                html.P(label, style={"fontSize": "12px", "color": CORES["cinza_texto"], "margin": "0 0 4px"}),
                html.P(f"{valor:,.0f}".replace(",", "."),
                       style={"fontSize": "24px", "fontWeight": "600", "margin": 0}),
            ],
        )

    cards = [
        card(f"Último {unidade}", ultimo, cor),
        card(f"Média por {unidade} (período)", media, cor),
        card("Total no período", total, cor),
    ]

    return fig, fig2, cards


if __name__ == "__main__":
    import os

    # debug=False: exposto na rede, o modo debug abriria o console do Werkzeug.
    # DEBUG=1 no ambiente religa o hot-reload para desenvolvimento local.
    app.run(debug=os.environ.get("DEBUG") == "1", port=8050,
            host=os.environ.get("HOST", "127.0.0.1"))
