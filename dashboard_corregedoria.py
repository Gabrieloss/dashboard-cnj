"""
Dashboard da Corregedoria — Auditorias da Justiça Militar da União (STM)
Fonte: STM_tbl_correg.csv — Relatório Consolidado do painel de Estatísticas do
Poder Judiciário (CNJ/DataJud), que atende aos requisitos da Corregedoria
Nacional de Justiça. Janela de 12 meses.

Diferente do dashboard comparativo (que vem da tbl_fato_R, com histórico mês a mês),
este arquivo traz UMA linha por auditoria, já consolidada nos últimos 12 meses
até junho/2026, com indicadores que só existem aqui (despachos, decisões
interlocutórias, mérito vs. sem mérito).

Requisitos:
    pip install dash plotly pandas
Rodar:
    python dashboard_corregedoria.py   ->  http://127.0.0.1:8053
"""

import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
DIR_DADOS = Path(__file__).resolve().parent / "planilhas"
CSV_PATH = DIR_DADOS / "STM_tbl_correg.csv"
NOSSA_AUDITORIA_ID = 32700
GRAU_AUDITORIAS = "G1"   # o CSV traz também os gabinetes de ministros (SUP)

# Indicadores numéricos diretos (coluna -> rótulo, e se "maior é melhor")
INDICADORES = {
    "Casos_Novos_12_meses":              {"label": "Casos novos (12 meses)", "melhor": None},
    "Baixados_12_meses":                 {"label": "Baixados (12 meses)", "melhor": "maior"},
    "Sentencas_Merito_12_meses":         {"label": "Sentenças de mérito (12 meses)", "melhor": "maior"},
    "Sentencas_Sem_Merito_12_meses":     {"label": "Sentenças sem mérito (12 meses)", "melhor": None},
    "Despachos_12_meses":                {"label": "Despachos (12 meses)", "melhor": "maior"},
    "Decisoes_Interlocutorias_12_meses": {"label": "Decisões interlocutórias (12 meses)", "melhor": "maior"},
    "Pendentes_Jun_2026":                {"label": "Pendentes (jun/2026)", "melhor": "menor"},
    "Suspensos_Jun_2026":                {"label": "Suspensos (jun/2026)", "melhor": None},
    "Sem_Movimentacao_120_dias_Jun_2026":{"label": "Sem movimentação +120 dias", "melhor": "menor"},
    "Conclusos_120_dias_Jun_2026":       {"label": "Conclusos +120 dias", "melhor": "menor"},
    "Taxa_Congestionamento_num":         {"label": "Taxa de congestionamento (%)", "melhor": "menor"},
    "IAD_num":                           {"label": "Índice de atendimento à demanda (%)", "melhor": "maior"},
    "Tempo_Sentenca_meses":              {"label": "Tempo até sentença (meses)", "melhor": "menor"},
    "Tempo_Pendente_meses":              {"label": "Idade do pendente líquido (meses)", "melhor": "menor"},
}

# Mesmo sistema visual do dashboard comparativo: grade suíça, fundo branco, fios
# de 1px no lugar de cartões. Azul marca a nossa auditoria; verde/vermelho só
# aparecem onde o número tem sinal (variação de acervo).
AZUL = "#1c5cab"; CINZA = "#c9c8c0"; CINZA_ESC = "#8b8a84"
AZUL_CLARO = "#9dbbe0"        # segunda série do gráfico agrupado (mesma matiz)
VERDE = "#006300"; VERMELHO = "#b3312f"
FUNDO = "#ffffff"; BORDA = "#dedcd4"; GRADE = "#eceae2"; REGUA = "#111110"
TEXTO = "#111110"; TEXTO_SEC = "#54534f"; TEXTO_MUDO = "#8b8a84"
FONTE = "Inter, 'Helvetica Neue', Helvetica, Arial, sans-serif"

# Escala tipográfica para TV de 70" a ~4 m.
T_TITULO, T_SECAO, T_NUM, T_CORPO, T_ROT = "44px", "16px", "60px", "19px", "15px"


# ---------------------------------------------------------------------------
# Parsers dos formatos textuais da fonte
# ---------------------------------------------------------------------------
def pct_para_num(txt):
    """'58%' -> 58.0 ; '-3,7%' -> -3.7"""
    if not isinstance(txt, str):
        return pd.NA
    t = txt.replace("%", "").replace(",", ".").strip()
    try:
        return float(t)
    except ValueError:
        return pd.NA


def tempo_para_meses(txt):
    """'1 ano e 6 meses' -> 18 ; '2 anos' -> 24 ; '8 meses' -> 8"""
    if not isinstance(txt, str):
        return pd.NA
    anos = re.search(r"(\d+)\s*ano", txt)
    meses = re.search(r"(\d+)\s*[Mm]es", txt)
    total = 0
    if anos:
        total += int(anos.group(1)) * 12
    if meses:
        total += int(meses.group(1))
    return total if total else pd.NA


def normalizar_nome(nome):
    if not isinstance(nome, str):
        return nome
    nome = nome.strip().upper()
    nome = re.sub(r"^(\d+)\s*AUDITORIA", r"\1ª AUDITORIA", nome)   # '4AUDITORIA' -> '4ª AUDITORIA'
    nome = re.sub(r"\s+", " ", nome)
    return nome.title().replace("Cjm", "CJM").replace("Da ", "da ")


def chave_ordenacao(nome):
    m = re.match(r"(\d+)ª\s+Auditoria\s+da\s+(\d+)ª\s+CJM", nome, re.IGNORECASE)
    if m:
        return (int(m.group(2)), int(m.group(1)))
    m2 = re.match(r"Auditoria\s+da\s+(\d+)ª\s+CJM", nome, re.IGNORECASE)
    if m2:
        return (int(m2.group(1)), 1)
    return (999, 999)


def faixa_eixo(*series, folga=0.08):
    """Faixa explícita para o eixo dos valores.

    O `transition` do Plotly anima a troca de dados mas não recalcula o
    autorange — a escala fica congelada na do indicador anterior até alguém
    dar duplo-clique. Fixar a faixa a cada render resolve sem perder a
    animação. (Mesmo helper existe em dashboard_auditorias.py; os dashboards
    são scripts independentes de propósito.)
    """
    vals = pd.concat([pd.Series(s, dtype="float64") for s in series]).dropna()
    if vals.empty:
        return [0, 1]
    lo, hi = float(vals.min()), float(vals.max())
    if lo >= 0:
        return [0, hi * (1 + folga) if hi > 0 else 1]
    # Variação de acervo é assinada: precisa caber o lado negativo.
    span = hi - lo or abs(hi) or 1
    return [lo - span * folga, hi + span * folga]


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------
def carregar_dados():
    # thousands=".": a fonte escreve 1374 como "1.374"; sem isso o pandas lê 1.374 (float).
    df = pd.read_csv(CSV_PATH, sep=";", encoding="utf-8-sig", thousands=".")

    # O CSV traz as 19 auditorias (G1) e os gabinetes de ministros (SUP, 2ª instância).
    # Comparar auditoria com gabinete não faz sentido — fica só o 1º grau.
    df = df[df["Grau"] == GRAU_AUDITORIAS].copy()

    df["nome_auditoria"] = df["Nome orgao"].apply(normalizar_nome)

    # converte percentuais e tempos textuais em números
    df["Taxa_Congestionamento_num"] = df["Taxa_Congestionamento_Jun_2026"].apply(pct_para_num)
    df["IAD_num"] = df["IAD_12_meses"].apply(pct_para_num)
    df["Tempo_Sentenca_meses"] = df["Tempo_Sentenca_12_meses"].apply(tempo_para_meses)
    df["Tempo_Pendente_meses"] = df["Tempo_Pendente_Liquido_Jun_2026"].apply(tempo_para_meses)
    df["%Pendentes_num"] = df["%Pendentes"].apply(pct_para_num)

    return df


df = carregar_dados()
nome_nossa = df.loc[df["Codigo orgao"] == NOSSA_AUDITORIA_ID, "nome_auditoria"].iloc[0]
n_aud = len(df)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = Dash(__name__)
app.title = "Dashboard da Corregedoria — JMU"


def rotulo_secao(texto):
    """Etiqueta azul em versalete que abre cada seção, seguida do fio preto."""
    return html.Div(texto, style={
        "fontSize": T_SECAO, "fontWeight": "600", "color": AZUL, "textTransform": "uppercase",
        "letterSpacing": "0.09em", "marginBottom": "14px"})


def card_kpi(rotulo, valor, detalhe, cor=TEXTO, primeiro=False):
    """Célula da grade — o valor é que carrega a cor quando tem sinal."""
    return html.Div(
        style={"padding": "26px 34px 24px",
               "borderLeft": "none" if primeiro else f"1px solid {BORDA}"},
        children=[
            html.P(rotulo, style={"fontSize": T_ROT, "color": TEXTO_SEC, "fontWeight": "600",
                                  "textTransform": "uppercase", "letterSpacing": "0.09em",
                                  "margin": "0 0 16px"}),
            html.P(valor, style={"fontSize": T_NUM, "fontWeight": "600", "margin": "0 0 10px",
                                 "letterSpacing": "-0.03em", "lineHeight": "0.92", "color": cor}),
            html.P(detalhe, style={"fontSize": "16px", "color": TEXTO_MUDO, "margin": 0,
                                   "lineHeight": "1.4"}),
        ],
    )


def secao(titulo, subtitulo, grafico_id, extra=None):
    """Seção da grade: etiqueta azul, fio preto e o gráfico. Sem cartão."""
    corpo = [html.P(subtitulo, style={"fontSize": T_CORPO, "color": TEXTO_SEC,
                                      "margin": "0 0 18px", "maxWidth": "95ch", "lineHeight": "1.5"})]
    if extra:
        corpo.append(extra)
    # animate=False de propósito: ver comentário em dashboard_auditorias.py.
    corpo.append(dcc.Graph(id=grafico_id, animate=False, config={"displayModeBar": False}))
    return html.Div(style={"marginBottom": "52px"}, children=[
        rotulo_secao(titulo),
        html.Div(style={"borderTop": f"1px solid {REGUA}", "paddingTop": "22px"}, children=corpo),
    ])


app.layout = html.Div(
    style={"fontFamily": FONTE, "background": FUNDO, "minHeight": "100vh", "margin": 0},
    children=[html.Div(
        style={"maxWidth": "1720px", "margin": "0 auto", "padding": "40px 56px 72px", "color": TEXTO},
        children=[
            # Cabeçalho — régua grossa e três colunas
            html.Div(
                style={"borderTop": f"4px solid {REGUA}", "paddingTop": "22px", "marginBottom": "44px",
                       "display": "grid", "gridTemplateColumns": "2.2fr 1fr 1fr", "gap": "40px",
                       "alignItems": "start"},
                children=[
                    html.Div([
                        html.H1("Consolidado da Corregedoria",
                                style={"fontSize": T_TITULO, "fontWeight": "600", "margin": "0",
                                       "letterSpacing": "-0.025em", "lineHeight": "1.05"}),
                        html.P(f"Justiça Militar da União · em azul, {nome_nossa}",
                               style={"color": TEXTO_SEC, "fontSize": T_CORPO, "margin": "8px 0 0"}),
                    ]),
                    html.Div([
                        html.Div("Período", style={
                            "fontSize": T_ROT, "color": TEXTO_MUDO, "textTransform": "uppercase",
                            "letterSpacing": "0.09em", "fontWeight": "600", "marginBottom": "8px"}),
                        html.Div("jul/2025 — jun/2026", style={"fontSize": "21px", "fontWeight": "600"}),
                    ]),
                    html.Div([
                        html.Div("Fonte", style={
                            "fontSize": T_ROT, "color": TEXTO_MUDO, "textTransform": "uppercase",
                            "letterSpacing": "0.09em", "fontWeight": "600", "marginBottom": "8px"}),
                        # Quem publica é o CNJ; a Corregedoria é quem exige o relatório.
                        html.Div("CNJ · DataJud", style={"fontSize": "21px", "fontWeight": "600"}),
                        html.Div("Relatório Consolidado", style={
                            "fontSize": "15px", "color": TEXTO_SEC, "marginTop": "2px"}),
                    ]),
                ],
            ),

            html.Div(style={"marginBottom": "52px"}, children=[
                rotulo_secao("Resumo da nossa auditoria"),
                html.Div(id="kpi-cards",
                         style={"display": "grid", "gridTemplateColumns": "repeat(4, 1fr)",
                                "borderTop": f"1px solid {REGUA}",
                                "borderBottom": f"1px solid {BORDA}"}),
            ]),

            secao("Ranking das auditorias", "", "g-ranking",
                  extra=html.Div(style={"marginBottom": "26px"}, children=[
                      html.Div(style={"maxWidth": "460px"}, children=[
                          html.Label("Indicador do ranking",
                                     style={"fontSize": T_ROT, "color": TEXTO_SEC, "fontWeight": "600",
                                            "textTransform": "uppercase", "letterSpacing": "0.09em"}),
                          dcc.Dropdown(
                              id="f-indicador",
                              options=[{"label": v["label"], "value": k} for k, v in INDICADORES.items()],
                              value="Despachos_12_meses", clearable=False),
                      ]),
                      html.P(id="rank-sub", style={"fontSize": "16px", "color": TEXTO_MUDO,
                                                   "margin": "14px 0 0"}),
                  ])),

            secao("Volume de trabalho além das baixas",
                  "Despachos e decisões interlocutórias nos últimos 12 meses — atos que não aparecem "
                  "na contagem de baixados/julgados, mas representam trabalho efetivo da auditoria.",
                  "g-trabalho"),

            secao("Variação do acervo pendente: jun/2025 → jun/2026",
                  "Quanto o estoque de processos pendentes cresceu ou diminuiu em um ano. "
                  "Barras à direita (positivas) indicam aumento do acervo.",
                  "g-variacao"),

            html.P("Nota: Relatório Consolidado do painel de Estatísticas do Poder Judiciário (CNJ/DataJud), "
                   "que atende aos requisitos da Corregedoria Nacional de Justiça. Usa as regras negociais próprias desse relatório e a janela "
                   "fixa dos últimos 12 meses — por isso alguns números diferem do dashboard comparativo, que "
                   "recalcula a partir da base bruta (tbl_fato_R) e permite escolher o período. Só o 1º grau entra "
                   "aqui: os gabinetes de ministros do STM, que também constam do arquivo, ficam de fora. Tempos "
                   "convertidos de texto ('1 ano e 6 meses') para meses. IAD acima de 100% = baixou mais do que recebeu.",
                   style={"fontSize": "16px", "color": TEXTO_MUDO, "lineHeight": "1.6",
                          "borderTop": f"1px solid {BORDA}", "paddingTop": "20px", "maxWidth": "130ch"}),
        ],
    )],
)


# ---------------------------------------------------------------------------
# Callback
# ---------------------------------------------------------------------------
@app.callback(
    Output("g-ranking", "figure"),
    Output("rank-sub", "children"),
    Output("g-trabalho", "figure"),
    Output("g-variacao", "figure"),
    Output("kpi-cards", "children"),
    Input("f-indicador", "value"),
)
def atualizar(indicador):
    info = INDICADORES[indicador]
    label = info["label"]

    # ---------- Ranking do indicador escolhido ----------
    serie = df.set_index("nome_auditoria")[indicador].dropna()
    # ordena para o "melhor" ficar no topo do gráfico horizontal
    if info["melhor"] == "menor":
        serie = serie.sort_values(ascending=False)
        nota_dir = "Menor é melhor — melhores no topo."
    elif info["melhor"] == "maior":
        serie = serie.sort_values(ascending=True)
        nota_dir = "Maior é melhor — melhores no topo."
    else:
        serie = serie.sort_values(ascending=True)
        nota_dir = "Sem juízo de valor — apenas volume."

    cores = [AZUL if n == nome_nossa else CINZA for n in serie.index]
    eh_pct = "%" in label
    fmt = ":.1f" if (eh_pct or "meses" in label) else ":,.0f"
    fig_rank = go.Figure(go.Bar(
        x=serie.values, y=serie.index, orientation="h", marker_color=cores, width=0.62,
        marker=dict(cornerradius=4),
        hovertemplate="<b>%{y}</b><br>%{x" + fmt + "}<extra></extra>",
    ))
    fig_rank.update_layout(
        template="plotly_white", font=dict(family=FONTE, size=16, color=TEXTO),
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        margin=dict(l=10, r=30, t=6, b=44), height=max(600, len(serie) * 34 + 90),
        xaxis=dict(title=dict(text=label, font=dict(size=16, color=TEXTO_SEC)), gridcolor=GRADE, zeroline=False,
                   range=faixa_eixo(serie.values), autorange=False),
        yaxis=dict(showgrid=False),
        transition=dict(duration=420, easing="cubic-in-out"),
    )

    # ---------- Trabalho: despachos + interlocutórias (barras agrupadas) ----------
    dtrab = df.sort_values("Despachos_12_meses", ascending=True)
    cor_desp = [AZUL if n == nome_nossa else AZUL_CLARO for n in dtrab["nome_auditoria"]]
    cor_int = [CINZA_ESC if n == nome_nossa else CINZA for n in dtrab["nome_auditoria"]]
    fig_trab = go.Figure()
    fig_trab.add_trace(go.Bar(
        y=dtrab["nome_auditoria"], x=dtrab["Despachos_12_meses"], orientation="h",
        name="Despachos", marker_color=cor_desp,
        hovertemplate="<b>%{y}</b><br>Despachos: %{x:,.0f}<extra></extra>"))
    fig_trab.add_trace(go.Bar(
        y=dtrab["nome_auditoria"], x=dtrab["Decisoes_Interlocutorias_12_meses"], orientation="h",
        name="Decisões interlocutórias", marker_color=cor_int,
        hovertemplate="<b>%{y}</b><br>Interlocutórias: %{x:,.0f}<extra></extra>"))
    fig_trab.update_layout(
        barmode="group", template="plotly_white", font=dict(family=FONTE, size=16, color=TEXTO),
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        margin=dict(l=10, r=20, t=6, b=44), height=max(680, len(dtrab) * 42 + 90),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(size=16, color=TEXTO_SEC)),
        xaxis=dict(title=dict(text="Quantidade de atos (12 meses)", font=dict(size=16, color=TEXTO_SEC)),
                   gridcolor=GRADE, zeroline=False),
        yaxis=dict(showgrid=False),
    )

    # ---------- Variação do acervo (diverging) ----------
    dvar = df.copy()
    dvar["delta"] = dvar["Pendentes_Jun_2026"] - dvar["Pendentes_Jun_2025"]
    dvar = dvar.sort_values("delta", ascending=True)
    cores_var = []
    for n, d in zip(dvar["nome_auditoria"], dvar["delta"]):
        if n == nome_nossa:
            cores_var.append(AZUL)
        else:
            cores_var.append(VERMELHO if d > 0 else VERDE)
    fig_var = go.Figure(go.Bar(
        y=dvar["nome_auditoria"], x=dvar["delta"], orientation="h", marker_color=cores_var, width=0.62,
        marker=dict(cornerradius=4),
        hovertemplate="<b>%{y}</b><br>Variação: %{x:+,.0f} processos<extra></extra>"))
    fig_var.update_layout(
        template="plotly_white", font=dict(family=FONTE, size=16, color=TEXTO),
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        margin=dict(l=10, r=20, t=6, b=44), height=max(600, len(dvar) * 34 + 90),
        xaxis=dict(title=dict(text="Variação no nº de pendentes (jun/2025 → jun/2026)", font=dict(size=16, color=TEXTO_SEC)),
                   gridcolor=GRADE, zeroline=True, zerolinecolor=TEXTO, zerolinewidth=1),
        yaxis=dict(showgrid=False),
    )

    # ---------- KPIs (sempre sobre a nossa auditoria) ----------
    nossa = df[df["Codigo orgao"] == NOSSA_AUDITORIA_ID].iloc[0]
    # posição: 1º = melhor. Se "maior é melhor", ordena desc; se "menor é melhor", ordena asc.
    if info["melhor"] == "maior":
        ordenado = serie.sort_values(ascending=False)
        pos = list(ordenado.index).index(nome_nossa) + 1
    elif info["melhor"] == "menor":
        ordenado = serie.sort_values(ascending=True)
        pos = list(ordenado.index).index(nome_nossa) + 1
    else:
        pos = None

    cards = [
        card_kpi("Casos novos (12m)", f"{nossa['Casos_Novos_12_meses']:,.0f}".replace(",", "."),
                 "processos recebidos no período", primeiro=True),
        card_kpi("Baixados (12m)", f"{nossa['Baixados_12_meses']:,.0f}".replace(",", "."),
                 "processos que saíram do acervo"),
        card_kpi("Despachos (12m)", f"{nossa['Despachos_12_meses']:,.0f}".replace(",", "."),
                 "atos de impulso — não contam como baixa"),
        card_kpi("Variação de pendentes", f"{nossa['%Pendentes']}",
                 f"{nossa['Pendentes_Jun_2025']:.0f} → {nossa['Pendentes_Jun_2026']:.0f} em 1 ano",
                 cor=(VERMELHO if pd.notna(nossa["%Pendentes_num"]) and nossa["%Pendentes_num"] > 0
                      else VERDE)),
    ]

    pos_txt = f" · Nossa auditoria: {pos}º de {n_aud}" if pos else ""
    sub = f"{nota_dir}{pos_txt}"

    return fig_rank, sub, fig_trab, fig_var, cards


if __name__ == "__main__":
    # HOST=0.0.0.0 expõe na rede; o padrão fica só na máquina local.
    import os
    # debug=False: exposto na rede, o modo debug abriria o console do Werkzeug.
    # DEBUG=1 no ambiente religa o hot-reload para desenvolvimento local.
    app.run(debug=os.environ.get("DEBUG") == "1", port=8053,
            host=os.environ.get("HOST", "127.0.0.1"))
