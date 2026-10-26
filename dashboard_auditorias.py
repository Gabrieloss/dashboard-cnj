"""
Dashboard comparativo — Auditorias da Justiça Militar da União (STM)
Compara as 19 auditorias, com destaque para a 2ª Auditoria da 3ª CJM.

Requisitos:
    pip install dash plotly pandas

Rodar:
    python dashboard_auditorias.py
    -> abre em http://127.0.0.1:8052
"""

import json
import re
from pathlib import Path
from typing import List

import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Dash, Input, Output, State, ctx, dcc, html

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
DIR_DADOS = Path(__file__).resolve().parent / "planilhas"
CSV_PATH = DIR_DADOS / "auditorias_stm.csv"   # gerado por processar_tbl_fato.py
NOSSA_AUDITORIA_ID = 32700                    # 2ª Auditoria da 3ª CJM

# Indicadores exibidos. "fluxo" = contagem de eventos no período (soma-se);
# "estoque" = fotografia do acervo no fim do período (usa-se o último valor).
INDICADORES = {
    "ind1":   {"label": "Casos novos",            "tipo": "fluxo",
               "desc": "processos que ingressaram no período"},
    "ind8a":  {"label": "Julgados",               "tipo": "fluxo",
               "desc": "decisões terminativas proferidas (inclui arquivamentos determinados por juiz)"},
    "ind3":   {"label": "Baixados",               "tipo": "fluxo",
               "desc": "processos que saíram do acervo (arquivamento, remessa etc.)"},
    "ind4":   {"label": "Suspensos",              "tipo": "fluxo",
               "desc": "processos que entraram em suspensão/sobrestamento"},
    "ind2":   {"label": "Pendentes — total",      "tipo": "estoque",
               "desc": "acervo total ao fim do período"},
    "CPJulg": {"label": "Pendentes — sem julgamento", "tipo": "estoque",
               "desc": "parcela do acervo que ainda não teve nenhuma decisão"},
    "ind5":   {"label": "Pendentes — líquidos",   "tipo": "estoque",
               "desc": "acervo excluindo processos suspensos/sobrestados"},
}

# Os quatro tempos do painel do CNJ, na ordem em que o processo os percorre.
# 'fluxo' = soma sobre os processos baixados/julgados no período;
# 'estoque' = fotografia do acervo no último mês do período.
TEMPO_INFO = {
    "ind16": {"curto": "Até a 1ª baixa",        "nome": "Tempo médio até a primeira baixa",   "modo": "fluxo"},
    "ind17": {"curto": "Até o 1º julgamento",   "nome": "Tempo médio até o primeiro julgamento", "modo": "fluxo"},
    "ind18": {"curto": "Pendente líquido",      "nome": "Idade média do pendente líquido",    "modo": "estoque"},
    "ind19": {"curto": "Acervo pendente",       "nome": "Idade média do acervo pendente",     "modo": "estoque"},
}

# Paleta de referência validada (gates de CVD/contraste em modo claro).
# Forma dominante aqui é "ênfase": uma cor para a nossa auditoria, cinza para o
# resto — o que importa é achar a nossa na multidão, não distinguir 19 séries.
# Direção "grade suíça": fundo branco, fios de 1px no lugar de cartões, régua
# preta abrindo cada seção. Cor tem função — azul só marca a nossa auditoria.
AZUL      = "#1c5cab"   # nossa auditoria (passo 550 da rampa azul)
LARANJA   = "#eb6834"   # comparadores opcionais
AQUA      = "#1baf7a"
VIOLETA   = "#4a3aa7"
VERMELHO  = "#e34948"
VERDE     = "#006300"
CINZA     = "#c9c8c0"   # demais auditorias (de-ênfase)
CINZA_ESC = "#8b8a84"   # média das demais
SUPERFICIE = "#ffffff"
FUNDO     = "#ffffff"
BORDA     = "#dedcd4"   # fio de 1px
GRADE     = "#eceae2"   # grade dos gráficos, ainda mais recuada
REGUA     = "#111110"   # régua grossa de abertura
TEXTO     = "#111110"
TEXTO_SEC = "#54534f"
TEXTO_MUDO = "#8b8a84"
CORES_COMPARADORES = [LARANJA, AQUA, VIOLETA, VERMELHO]

# Escala tipográfica pensada para leitura a ~4 m numa TV de 70".
T_TITULO, T_SECAO, T_HERO, T_NUM, T_CORPO, T_ROT = "44px", "16px", "96px", "60px", "19px", "15px"

# A Corregedoria e o painel do CNJ contam apenas estas fases. Conferido: com este
# filtro os 4 tempos médios batem exatamente com o painel oficial (386/553/460/506),
# e casos novos/baixados batem nas 19 auditorias contra o STM_tbl_correg.csv.
FASES_CNJ = [
    "Conhecimento criminal",
    "Execução penal não privativa de liberdade",
    "Execução penal privativa de liberdade",
]

FONTE = "Inter, 'Helvetica Neue', Helvetica, Arial, sans-serif"


# ---------------------------------------------------------------------------
# Normalização dos nomes das auditorias
# ---------------------------------------------------------------------------
def normalizar_nome_auditoria(nome: str) -> str:
    """Padroniza capitalização/espaçamento sem alterar a nomenclatura oficial.
    CJMs com auditoria única ('Auditoria da 4ª CJM', sem numeral) mantêm o nome como está."""
    if not isinstance(nome, str):
        return nome
    nome = nome.strip().upper()
    nome = re.sub(r"^(\d+)\s*AUDITORIA", r"\1ª AUDITORIA", nome)   # '4AUDITORIA' -> '4ª AUDITORIA'
    nome = re.sub(r"\s+", " ", nome)
    return nome.title().replace("Cjm", "CJM").replace("Da ", "da ")


def chave_ordenacao(nome: str):
    m = re.match(r"(\d+)ª\s+Auditoria\s+da\s+(\d+)ª\s+CJM", nome, re.IGNORECASE)
    if m:
        return (int(m.group(2)), int(m.group(1)))
    m2 = re.match(r"Auditoria\s+da\s+(\d+)ª\s+CJM", nome, re.IGNORECASE)
    if m2:
        return (int(m2.group(1)), 1)
    return (999, 999)


# ---------------------------------------------------------------------------
# Carga e preparação
# ---------------------------------------------------------------------------
def carregar_dados() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH, sep=";")
    df["data"] = pd.to_datetime(df["anomes"].astype(str), format="%Y%m")
    df["trimestre"] = df["data"].dt.to_period("Q")
    # processar_tbl_fato.py já grava 'nome_auditoria' (join com a tabela de órgãos);
    # a tbl_fato_R crua não traz nome nenhum, só o id.
    df["nome_auditoria"] = df["nome_auditoria"].apply(normalizar_nome_auditoria)
    for c in [k for k, v in INDICADORES.items() if v["tipo"] == "fluxo"]:
        if c in df.columns:
            df[c] = df[c].fillna(0)
    return df


df = carregar_dados()
procedimentos = sorted(df["procedimento"].dropna().unique().tolist())
auditorias_ordenadas = sorted(df["nome_auditoria"].unique(), key=chave_ordenacao)
nome_nossa = df.loc[df["id_orgao_julgador"] == NOSSA_AUDITORIA_ID, "nome_auditoria"].iloc[0]

meses_ordenados = sorted(df["data"].unique())
marcas_slider = {
    i: pd.Timestamp(d).strftime("%Y")
    for i, d in enumerate(meses_ordenados)
    if pd.Timestamp(d).month == 1
}

periodo_ini = df["data"].min().strftime("%m/%Y")
periodo_fim = df["data"].max().strftime("%m/%Y")
meses_ordenados = sorted(df["data"].unique())

ROTULOS_MES = [pd.Timestamp(d).strftime("%m/%Y") for d in meses_ordenados]


def _gerar_js_tooltip() -> None:
    """O RangeSlider trabalha em índices (0, 1, 2...), mas mostrar '71' para o
    usuário não diz nada. Esta função JS traduz o índice em '07/2025' no tooltip.
    É regravada a cada carga, então acompanha sozinha os dados novos."""
    js = ("// gerado por dashboard_auditorias.py — não editar à mão\n"
          "window.dccFunctions = window.dccFunctions || {};\n"
          f"window.dccFunctions.mesDoIndice = function (i) {{ return {json.dumps(ROTULOS_MES)}[i]; }};\n")
    destino = Path(__file__).resolve().parent / "assets" / "slider_meses.js"
    destino.parent.mkdir(exist_ok=True)
    if not destino.exists() or destino.read_text(encoding="utf-8") != js:
        destino.write_text(js, encoding="utf-8")


_gerar_js_tooltip()

# Atalhos de período — arrastar dois punhos até "últimos 12 meses" é trabalhoso
# e é justamente a janela que mais se usa.
PRESETS_PERIODO = [("12 meses", 12), ("24 meses", 24), ("5 anos", 60), ("Tudo", None)]

# Janela padrão = últimos 12 meses, igual ao painel oficial do CNJ. É essa janela
# que faz os números baterem com o consolidado da Corregedoria; abrir o período
# inteiro (desde 01/2020) distorce sobretudo os tempos médios.
JANELA_PADRAO = 12
idx_ini_padrao = max(0, len(meses_ordenados) - JANELA_PADRAO)
idx_fim_padrao = len(meses_ordenados) - 1

FLUXO_COLS = [k for k, v in INDICADORES.items() if v["tipo"] == "fluxo" and k in df.columns]
ESTOQUE_COLS = [k for k, v in INDICADORES.items() if v["tipo"] == "estoque" and k in df.columns]


def rotulo_trimestre(p: pd.Period) -> str:
    return f"T{p.quarter}/{p.year}"


def faixa_eixo(*series, folga: float = 0.08) -> List[float]:
    """Faixa explícita para o eixo dos valores.

    O `transition` do Plotly anima a troca de dados mas não recalcula o
    autorange — a escala fica congelada na do indicador anterior até alguém
    dar duplo-clique. Fixar a faixa a cada render resolve sem perder a
    animação: a transição passa a animar também a mudança de escala.
    """
    vals = pd.concat([pd.Series(s, dtype="float64") for s in series]).dropna()
    if vals.empty:
        return [0, 1]
    lo, hi = float(vals.min()), float(vals.max())
    if lo >= 0:
        # Barras e séries de contagem: âncora no zero, senão a comparação mente.
        return [0, hi * (1 + folga) if hi > 0 else 1]
    span = hi - lo or abs(hi) or 1
    return [lo - span * folga, hi + span * folga]


def agrega(dff: pd.DataFrame, chave_tempo: str) -> pd.DataFrame:
    grupos = ["nome_auditoria", chave_tempo]
    soma_fluxo = dff.groupby(grupos)[FLUXO_COLS].sum(min_count=1)
    if chave_tempo == "data":
        # Cada grupo já é um único mês: o estoque é o próprio valor do mês
        soma_estoque = dff.groupby(grupos)[ESTOQUE_COLS].sum(min_count=1)
    else:
        # Estoque = fotografia do último mês dentro do período
        ultimo = dff.sort_values("data").groupby(grupos)["data"].max().reset_index()
        snap = dff.merge(ultimo, on=[*grupos, "data"])
        soma_estoque = snap.groupby(grupos)[ESTOQUE_COLS].sum(min_count=1)
    return soma_fluxo.join(soma_estoque).reset_index()


# ---------------------------------------------------------------------------
# Elementos de layout
# ---------------------------------------------------------------------------
def rotulo_secao(texto):
    """Etiqueta azul em versalete que abre cada seção, seguida do fio preto."""
    return html.Div(texto, style={
        "fontSize": T_SECAO, "fontWeight": "600", "color": AZUL, "textTransform": "uppercase",
        "letterSpacing": "0.09em", "marginBottom": "14px"})


def secao(titulo, subtitulo, grafico_id):
    """Seção da grade: etiqueta, fio preto de abertura e o gráfico. Sem cartão."""
    return html.Div(
        style={"marginBottom": "52px"},
        children=[
            rotulo_secao(titulo),
            html.Div(style={"borderTop": f"1px solid {REGUA}", "paddingTop": "22px"}, children=[
                html.P(id=f"{grafico_id}-subtitulo", children=subtitulo,
                       style={"fontSize": T_CORPO, "color": TEXTO_SEC, "margin": "0 0 18px",
                              "maxWidth": "95ch", "lineHeight": "1.5"}),
                # animate=False de propósito: o Dash usa Plotly.react, que respeita o
                # layout.transition e anima também a mudança de escala. Com animate=True
                # (Plotly.animate) o eixo fica congelado no indicador anterior.
                dcc.Graph(id=grafico_id, animate=False, config={"displayModeBar": False}),
            ]),
        ],
    )


def filtro(label, componente, flex="1", min_width="200px"):
    return html.Div(
        style={"flex": flex, "minWidth": min_width},
        children=[
            html.Label(label, style={"fontSize": "11px", "color": TEXTO_SEC,
                                     "fontWeight": "600", "textTransform": "uppercase",
                                     "letterSpacing": "0.4px"}),
            componente,
        ],
    )


def faixa_posicoes(serie: pd.Series) -> html.Div:
    """Régua com as 19 auditorias posicionadas pelo valor. A nossa em azul, as
    demais em cinza — forma de 'ênfase': o que importa é achar a nossa na multidão,
    não distinguir 19 séries. Substitui um segundo gráfico de barras."""
    if serie.empty:
        return html.Div(style={"height": "34px"})
    lo, hi = float(serie.min()), float(serie.max())
    faixa = (hi - lo) or 1.0

    pontos = []
    for nome, valor in serie.items():
        nossa = nome == nome_nossa
        pos = (float(valor) - lo) / faixa * 100
        pontos.append(html.Div(
            title=f"{nome}: {valor:,.0f} dias".replace(",", "."),
            style={
                "position": "absolute", "top": "50%", "left": f"{pos}%",
                "transform": "translate(-50%, -50%)",
                "width": "11px" if nossa else "8px",
                "height": "11px" if nossa else "8px",
                "borderRadius": "50%",
                "background": AZUL if nossa else CINZA,
                # anel na cor da superfície: mantém os pontos legíveis onde se sobrepõem
                "boxShadow": f"0 0 0 2px {SUPERFICIE}",
                "zIndex": "2" if nossa else "1",
            },
        ))

    mediana = serie.median()
    return html.Div([
        html.Div(style={"position": "relative", "height": "30px"}, children=[
            html.Div(style={"position": "absolute", "top": "50%", "left": 0, "right": 0,
                            "height": "1.5px", "background": BORDA, "transform": "translateY(-50%)"}),
            *pontos,
        ]),
        # extremos e mediana rotulados: dá escala à régua sem precisar de eixo
        html.Div(style={"display": "flex", "justifyContent": "space-between",
                        "fontSize": "15px", "color": TEXTO_MUDO, "marginTop": "2px"}, children=[
            html.Span(f"{lo:,.0f}".replace(",", ".")),
            html.Span(f"mediana {mediana:,.0f}".replace(",", ".")),
            html.Span(f"{hi:,.0f}".replace(",", ".")),
        ]),
    ], style={"marginTop": "22px"})


def tile_tempo(metrica: str, serie: pd.Series, selecionado: bool) -> html.Div:
    """Número-herói + posição da nossa auditoria + régua das 19. Clicável: abre
    o ranking completo daquela métrica no gráfico abaixo."""
    valor = serie.get(nome_nossa)
    ordenado = serie.sort_values(ascending=True)          # menor tempo = melhor
    pos = list(ordenado.index).index(nome_nossa) + 1 if nome_nossa in serie.index else None
    mediana = serie.median() if not serie.empty else float("nan")

    if pd.isna(valor):
        texto_valor, comparacao = "—", "sem dados no período"
    else:
        texto_valor = f"{valor:,.0f}".replace(",", ".")
        dif = valor - mediana
        rumo = "acima" if dif > 0 else "abaixo"
        comparacao = f"{pos}ª de {len(serie)} · {abs(dif):,.0f} dias {rumo} da mediana".replace(",", ".")

    primeiro = metrica == list(TEMPO_INFO)[0]
    return html.Div(
        id={"type": "tile-tempo", "id": metrica},
        n_clicks=0,
        className="celula-tempo" + (" selecionada" if selecionado else ""),
        n_clicks_timestamp=0,
        style={
            "cursor": "pointer",
            "padding": "28px 34px 26px",
            "borderLeft": "none" if primeiro else f"1px solid {BORDA}",
            "boxShadow": f"inset 0 3px 0 0 {AZUL}" if selecionado else "none",
            "background": "#f4f7fc" if selecionado else "transparent",
            "transition": "background 160ms ease, box-shadow 160ms ease",
        },
        children=[
            html.Div(style={"display": "flex", "justifyContent": "space-between",
                            "alignItems": "baseline", "marginBottom": "20px"}, children=[
                html.Span(TEMPO_INFO[metrica]["curto"],
                          style={"fontSize": T_ROT, "fontWeight": "600", "color": TEXTO_SEC,
                                 "textTransform": "uppercase", "letterSpacing": "0.09em"}),
                html.Span(f"{pos}/{len(serie)}" if pos else "—",
                          style={"fontSize": "16px", "color": TEXTO_MUDO,
                                 "fontVariantNumeric": "tabular-nums"}),
            ]),
            html.P([
                html.Span(texto_valor, style={"fontSize": T_HERO, "fontWeight": "600",
                                              "letterSpacing": "-0.03em", "lineHeight": "0.92"}),
                html.Span(" dias", style={"fontSize": "20px", "color": TEXTO_MUDO, "marginLeft": "10px"}),
            ], style={"margin": 0}),
            html.P(comparacao, style={"fontSize": "16px", "color": TEXTO_MUDO, "margin": "14px 0 0"}),
            faixa_posicoes(serie),
        ],
    )


app = Dash(__name__)
app.title = "Comparativo de Auditorias — JMU"

app.layout = html.Div(
    style={"fontFamily": FONTE, "background": FUNDO, "minHeight": "100vh", "margin": 0},
    children=[html.Div(
        style={"maxWidth": "1720px", "margin": "0 auto", "padding": "40px 56px 72px", "color": TEXTO},
        children=[
            # Cabeçalho — régua grossa e três colunas, como numa publicação oficial
            html.Div(
                style={"borderTop": f"4px solid {REGUA}", "paddingTop": "22px", "marginBottom": "44px",
                       "display": "grid", "gridTemplateColumns": "2.2fr 1fr 1fr", "gap": "40px",
                       "alignItems": "start"},
                children=[
                    html.Div([
                        html.H1("Comparativo de Auditorias",
                                style={"fontSize": T_TITULO, "fontWeight": "600", "margin": "0",
                                       "letterSpacing": "-0.025em", "lineHeight": "1.05"}),
                        html.P(f"Justiça Militar da União · em azul, {nome_nossa}",
                               style={"color": TEXTO_SEC, "fontSize": T_CORPO, "margin": "8px 0 0"}),
                    ]),
                    html.Div([
                        html.Div("Base disponível", style={
                            "fontSize": T_ROT, "color": TEXTO_MUDO, "textTransform": "uppercase",
                            "letterSpacing": "0.09em", "fontWeight": "600", "marginBottom": "8px"}),
                        html.Div(f"{periodo_ini} — {periodo_fim}",
                                 style={"fontSize": "21px", "fontWeight": "600"}),
                    ]),
                    html.Div([
                        html.Div("Fonte", style={
                            "fontSize": T_ROT, "color": TEXTO_MUDO, "textTransform": "uppercase",
                            "letterSpacing": "0.09em", "fontWeight": "600", "marginBottom": "8px"}),
                        html.Div("Painel CNJ · DataJud",
                                 style={"fontSize": "21px", "fontWeight": "600"}),
                    ]),
                ],
            ),

            # Filtros
            html.Div(
                style={"display": "flex", "gap": "20px", "marginBottom": "44px", "flexWrap": "wrap",
                       "borderTop": f"1px solid {BORDA}", "borderBottom": f"1px solid {BORDA}",
                       "padding": "22px 0", "alignItems": "flex-end"},
                children=[
                    filtro("Indicador", dcc.Dropdown(
                        id="f-indicador",
                        options=[{"label": v["label"], "value": k} for k, v in INDICADORES.items() if k in df.columns],
                        value="ind1", clearable=False), flex="2"),
                    filtro("Fase processual", dcc.Dropdown(
                        id="f-procedimento",
                        options=[{"label": "Visão CNJ (conhecimento + execução)", "value": "CNJ"},
                                 {"label": "Todas as fases", "value": "TODOS"}]
                                + [{"label": p, "value": p} for p in procedimentos],
                        value="CNJ", clearable=False), flex="2"),
                    filtro("Período do gráfico de evolução", dcc.RadioItems(
                        id="f-granularidade",
                        options=[{"label": " Por trimestre", "value": "trimestral"},
                                 {"label": " Por mês", "value": "mensal"}],
                        value="trimestral",
                        style={"display": "flex", "gap": "14px", "marginTop": "8px", "fontSize": "13px"},
                        inputStyle={"marginRight": "4px"}), flex="1", min_width="230px"),
                    filtro("Adicionar auditorias à comparação (máx. 3)", dcc.Dropdown(
                        id="f-comparadores",
                        options=[{"label": a, "value": a} for a in auditorias_ordenadas if a != nome_nossa],
                        value=[], multi=True, placeholder="Nenhuma selecionada"), flex="3", min_width="260px"),
                    html.Div(
                        style={"flexBasis": "100%", "marginTop": "8px"},
                        children=[
                            html.Div(
                                style={"display": "flex", "alignItems": "baseline", "gap": "14px",
                                       "flexWrap": "wrap", "marginBottom": "10px"},
                                children=[
                                    html.Label("Período analisado",
                                               style={"fontSize": "11px", "color": TEXTO_SEC,
                                                      "fontWeight": "600", "textTransform": "uppercase",
                                                      "letterSpacing": "0.5px"}),
                                    html.Span(id="periodo-legenda",
                                              style={"fontSize": "13px", "color": TEXTO,
                                                     "fontWeight": "600"}),
                                    html.Div(
                                        style={"display": "flex", "gap": "6px", "marginLeft": "auto"},
                                        children=[
                                            html.Button(
                                                rot, id={"type": "preset-periodo", "meses": m or 0},
                                                n_clicks=0, className="preset-btn")
                                            for rot, m in PRESETS_PERIODO
                                        ],
                                    ),
                                ],
                            ),
                            dcc.RangeSlider(
                                id="f-periodo",
                                min=0, max=len(meses_ordenados) - 1,
                                value=[idx_ini_padrao, idx_fim_padrao],
                                marks=marcas_slider, step=1,
                                # traduz o índice em mm/aaaa; sem isso o tooltip mostra '71'
                                tooltip={"placement": "bottom", "always_visible": False,
                                         "transform": "mesDoIndice"},
                                allow_direct_input=False,
                                allowCross=False,
                            ),
                        ],
                    ),
                ],
            ),

            # KPIs — células da grade, divididas por fios, sem cartão
            html.Div(style={"marginBottom": "52px"}, children=[
                rotulo_secao("Resumo da nossa auditoria"),
                html.Div(id="kpi-cards",
                         style={"display": "grid", "gridTemplateColumns": "repeat(4, 1fr)",
                                "borderTop": f"1px solid {REGUA}",
                                "borderBottom": f"1px solid {BORDA}"}),
            ]),

            # Gráficos
            secao("Ranking das auditorias", "", "g-ranking"),
            secao("Evolução no tempo", "", "g-evolucao"),

            # Seção de tempos médios — os quatro simultâneos, como no painel do CNJ,
            # mas cada um trazendo a posição da nossa auditoria entre as 19.
            dcc.Store(id="tempo-sel", data="ind17"),
            html.Div(
                style={"marginBottom": "52px"},
                children=[
                    rotulo_secao("Tempo médio do processo, em dias"),
                    html.P(id="tempos-chapeu", children="",
                           style={"fontSize": T_CORPO, "color": TEXTO_SEC, "margin": "0 0 18px",
                                  "maxWidth": "95ch", "lineHeight": "1.5"}),

                    html.Div(id="tempo-tiles",
                             style={"display": "grid", "gridTemplateColumns": "repeat(4, 1fr)",
                                    "borderTop": f"1px solid {REGUA}",
                                    "borderBottom": f"1px solid {BORDA}", "marginBottom": "40px"}),

                    html.P(id="g-tempos-subtitulo", children="",
                           style={"fontSize": T_CORPO, "color": TEXTO_SEC, "margin": "0 0 14px",
                                  "maxWidth": "95ch", "lineHeight": "1.5"}),
                    dcc.Graph(id="g-tempo", animate=False, config={"displayModeBar": False}),
                ],
            ),

            html.P(
                "Nota metodológica: indicadores de movimento (casos novos, julgados, baixados, suspensos) são somados "
                "dentro de cada período. Indicadores de acervo (pendentes) usam a fotografia do último mês do período — "
                "somá-los distorceria o valor. \"Julgados\" segue a definição do CNJ: qualquer decisão terminativa, "
                "inclusive arquivamentos determinados por juiz. "
                "Tempos médios seguem a metodologia do CNJ: soma de dias ÷ quantidade de processos. "
                "\"Até a primeira baixa\" e \"até o primeiro julgamento\" consideram os processos baixados/julgados "
                "dentro do período selecionado; \"idade do acervo\" mede há quanto tempo, em média, os processos "
                "ainda pendentes aguardam, na fotografia do último mês do período. Em todos, menor é melhor.",
                style={"fontSize": "16px", "color": TEXTO_MUDO, "lineHeight": "1.6", "marginTop": "8px",
                       "borderTop": f"1px solid {BORDA}", "paddingTop": "20px", "maxWidth": "130ch"},
            ),
        ],
    )],
)


# ---------------------------------------------------------------------------
# Callback
# ---------------------------------------------------------------------------
@app.callback(
    Output("f-periodo", "value"),
    Input({"type": "preset-periodo", "meses": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def aplicar_preset(_cliques):
    if not isinstance(ctx.triggered_id, dict):
        return [idx_ini_padrao, idx_fim_padrao]
    meses = ctx.triggered_id["meses"]
    fim = len(meses_ordenados) - 1
    return [0 if not meses else max(0, len(meses_ordenados) - meses), fim]


@app.callback(
    Output("tempo-sel", "data"),
    Input({"type": "tile-tempo", "id": ALL}, "n_clicks"),
    State("tempo-sel", "data"),
    prevent_initial_call=True,
)
def selecionar_tempo(_cliques, atual):
    """Os próprios cartões são o seletor da métrica — sem radio button separado."""
    if isinstance(ctx.triggered_id, dict):
        return ctx.triggered_id["id"]
    return atual


@app.callback(
    Output("g-ranking", "figure"),
    Output("g-ranking-subtitulo", "children"),
    Output("g-evolucao", "figure"),
    Output("g-evolucao-subtitulo", "children"),
    Output("g-tempo", "figure"),
    Output("g-tempos-subtitulo", "children"),
    Output("tempo-tiles", "children"),
    Output("tempos-chapeu", "children"),
    Output("periodo-legenda", "children"),
    Output("kpi-cards", "children"),
    Input("f-indicador", "value"),
    Input("f-procedimento", "value"),
    Input("f-granularidade", "value"),
    Input("f-comparadores", "value"),
    Input("f-periodo", "value"),
    Input("tempo-sel", "data"),
)
def atualizar(indicador, procedimento, granularidade, comparadores, periodo, tempo_metrica):
    info = INDICADORES[indicador]
    nome_ind = info["label"]
    if procedimento == "TODOS":
        dff = df
    elif procedimento == "CNJ":
        dff = df[df["procedimento"].isin(FASES_CNJ)]
    else:
        dff = df[df["procedimento"] == procedimento]

    # Filtro de período
    data_ini = pd.Timestamp(meses_ordenados[periodo[0]])
    data_fim = pd.Timestamp(meses_ordenados[periodo[1]])
    dff = dff[(dff["data"] >= data_ini) & (dff["data"] <= data_fim)]
    p_ini = data_ini.strftime("%m/%Y")
    p_fim = data_fim.strftime("%m/%Y")
    # quantos meses a janela cobre — para não obrigar ninguém a contar de cabeça
    n_meses = periodo[1] - periodo[0] + 1
    anos, resto = divmod(n_meses, 12)
    mes_txt = lambda q: f"{q} {'mês' if q == 1 else 'meses'}"
    ano_txt = lambda q: f"{q} {'ano' if q == 1 else 'anos'}"
    if anos and resto:
        periodo_legenda = f"{p_ini} → {p_fim} · {mes_txt(n_meses)} ({ano_txt(anos)} e {mes_txt(resto)})"
    elif anos:
        periodo_legenda = f"{p_ini} → {p_fim} · {mes_txt(n_meses)} ({ano_txt(anos)})"
    else:
        periodo_legenda = f"{p_ini} → {p_fim} · {mes_txt(n_meses)}"

    if procedimento == "TODOS":
        fase_txt = "todas as fases"
    elif procedimento == "CNJ":
        fase_txt = "conhecimento + execução, como conta o CNJ"
    else:
        fase_txt = f"fase: {procedimento}"
    chave_tempo = "trimestre" if granularidade == "trimestral" else "data"

    agr = agrega(dff, chave_tempo)

    # ---------------- Ranking ----------------
    if info["tipo"] == "fluxo":
        ranking = agr.groupby("nome_auditoria")[indicador].sum(min_count=1)
        rank_sub = (f"{nome_ind} — total acumulado de {p_ini} a {p_fim} ({fase_txt}). "
                    f"{info['desc'].capitalize()}.")
        eixo_x_rank = f"{nome_ind} no período (total)"
    else:
        ult = agr.sort_values(chave_tempo).groupby("nome_auditoria").tail(1)
        ranking = ult.set_index("nome_auditoria")[indicador]
        rank_sub = (f"{nome_ind} — situação em {p_fim} ({fase_txt}). "
                    f"{info['desc'].capitalize()}.")
        eixo_x_rank = f"{nome_ind} em {p_fim}"

    ranking = ranking.sort_values(ascending=True)
    cores = [AZUL if n == nome_nossa else CINZA for n in ranking.index]

    fig_rank = go.Figure(go.Bar(
        x=ranking.values, y=ranking.index, orientation="h", marker_color=cores,
        width=0.62, marker=dict(cornerradius=4),
        hovertemplate="<b>%{y}</b><br>" + nome_ind + ": %{x:,.0f}<extra></extra>",
    ))
    fig_rank.update_layout(
        template="plotly_white", font=dict(family=FONTE, size=16, color=TEXTO),
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        margin=dict(l=10, r=30, t=6, b=44), height=max(560, len(ranking) * 34 + 90),
        transition=dict(duration=420, easing="cubic-in-out"),
        xaxis=dict(title=dict(text=eixo_x_rank, font=dict(size=16, color=TEXTO_SEC)),
                   gridcolor=GRADE, zeroline=False, tickfont=dict(color=TEXTO_MUDO),
                   range=faixa_eixo(ranking.values), autorange=False),
        yaxis=dict(title=None, showgrid=False, tickfont=dict(color=TEXTO_SEC)),
    )

    # ---------------- Evolução ----------------
    if granularidade == "trimestral":
        agr["rotulo"] = agr["trimestre"].apply(rotulo_trimestre)
        ordem = agr[["trimestre", "rotulo"]].drop_duplicates().sort_values("trimestre")["rotulo"].tolist()
        eixo_x_evo = "Trimestre"
    else:
        agr["rotulo"] = agr["data"].dt.strftime("%m/%Y")
        ordem = agr[["data", "rotulo"]].drop_duplicates().sort_values("data")["rotulo"].tolist()
        eixo_x_evo = "Mês"

    fig_evo = go.Figure()

    nossa = agr[agr["nome_auditoria"] == nome_nossa].set_index("rotulo")[indicador].reindex(ordem)
    fig_evo.add_trace(go.Scatter(
        x=ordem, y=nossa, mode="lines+markers", name=nome_nossa,
        line=dict(color=AZUL, width=3), marker=dict(size=5),
        hovertemplate="<b>" + nome_nossa + "</b><br>%{x}: %{y:,.0f}<extra></extra>",
    ))

    demais = agr[agr["nome_auditoria"] != nome_nossa]
    media = demais.groupby("rotulo")[indicador].mean().reindex(ordem)
    fig_evo.add_trace(go.Scatter(
        x=ordem, y=media, mode="lines", name="Média das demais 18 auditorias",
        line=dict(color=CINZA_ESC, width=2, dash="dot"),
        hovertemplate="<b>Média das demais</b><br>%{x}: %{y:,.1f}<extra></extra>",
    ))

    series_comp = []
    for i, comp in enumerate((comparadores or [])[:3]):
        serie = agr[agr["nome_auditoria"] == comp].set_index("rotulo")[indicador].reindex(ordem)
        series_comp.append(serie)
        fig_evo.add_trace(go.Scatter(
            x=ordem, y=serie, mode="lines+markers", name=comp,
            line=dict(color=CORES_COMPARADORES[i], width=2), marker=dict(size=4),
            hovertemplate="<b>" + comp + "</b><br>%{x}: %{y:,.0f}<extra></extra>",
        ))

    verbo = "somado no" if info["tipo"] == "fluxo" else "medido ao fim de cada"
    evo_sub = (f"{nome_ind} {verbo} {'trimestre' if granularidade == 'trimestral' else 'mês'} "
               f"({fase_txt}). Linha pontilhada: média simples das outras 18 auditorias.")

    fig_evo.update_layout(
        template="plotly_white", font=dict(family=FONTE, size=16, color=TEXTO),
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        margin=dict(l=10, r=20, t=6, b=64), height=520,
        transition=dict(duration=420, easing="cubic-in-out"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(size=16, color=TEXTO_SEC)),
        xaxis=dict(title=dict(text=eixo_x_evo, font=dict(size=16, color=TEXTO_SEC)), tickangle=-45,
                   showgrid=False, nticks=14, tickfont=dict(color=TEXTO_MUDO)),
        yaxis=dict(title=dict(text=nome_ind, font=dict(size=16, color=TEXTO_SEC)), gridcolor=GRADE,
                   zeroline=False, tickfont=dict(color=TEXTO_MUDO),
                   range=faixa_eixo(nossa, media, *series_comp), autorange=False),
    )

    # ---------------- Tempos médios ----------------
    # Metodologia CNJ: tempo médio = soma(_dias) / soma(_proc).
    # ind16/ind17 são eventos (baixa/julgamento): soma no período selecionado.
    # ind18/ind19 são retrato do acervo: usa-se o último mês do período.
    def tempo_medio_por_auditoria(metrica: str) -> pd.Series:
        col_d, col_p = f"{metrica}_dias", f"{metrica}_proc"
        base = dff.copy()
        base[col_d] = pd.to_numeric(base[col_d], errors="coerce")
        base[col_p] = pd.to_numeric(base[col_p], errors="coerce")
        if TEMPO_INFO[metrica]["modo"] == "fluxo":
            dias = base.groupby("nome_auditoria")[col_d].sum(min_count=1)
            proc = base.groupby("nome_auditoria")[col_p].sum(min_count=1)
        else:
            ult_m = base.sort_values("data").groupby("nome_auditoria")["data"].max().reset_index()
            snap = base.merge(ult_m, on=["nome_auditoria", "data"])
            dias = snap.groupby("nome_auditoria")[col_d].sum(min_count=1)
            proc = snap.groupby("nome_auditoria")[col_p].sum(min_count=1)
        return (dias / proc.replace(0, pd.NA)).dropna()

    # Os quatro são calculados sempre — os cartões mostram todos ao mesmo tempo,
    # e o clique só escolhe qual deles o ranking abaixo detalha.
    series_tempo = {m: tempo_medio_por_auditoria(m) for m in TEMPO_INFO}
    tempos = series_tempo[tempo_metrica]
    nome_tempo = TEMPO_INFO[tempo_metrica]["nome"]

    tiles = [tile_tempo(m, series_tempo[m], m == tempo_metrica) for m in TEMPO_INFO]
    chapeu = (f"Os quatro tempos médios da nossa auditoria entre {p_ini} e {p_fim} ({fase_txt}), "
              f"na ordem em que o processo os percorre. Cada régua mostra as {len(tempos)} auditorias "
              "posicionadas pelo seu tempo — o ponto azul é a nossa. Clique num cartão para abrir "
              "o ranking completo.")

    tempos_ord = tempos.sort_values(ascending=False)  # menor tempo no topo do gráfico
    cores_t = [AZUL if n == nome_nossa else CINZA for n in tempos_ord.index]
    fig_tempo = go.Figure(go.Bar(
        x=tempos_ord.values, y=tempos_ord.index, orientation="h", marker_color=cores_t,
        width=0.62,                       # barra fina: sobra ar dentro da faixa
        marker=dict(cornerradius=4),      # ponta arredondada, base quadrada no zero
        hovertemplate="<b>%{y}</b><br>%{x:,.0f} dias<extra></extra>",
    ))
    fig_tempo.update_layout(
        template="plotly_white", font=dict(family=FONTE, size=16, color=TEXTO),
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        margin=dict(l=10, r=30, t=6, b=44), height=max(560, len(tempos_ord) * 34 + 90),
        transition=dict(duration=420, easing="cubic-in-out"),
        xaxis=dict(title=dict(text=f"{nome_tempo} (dias)", font=dict(size=16, color=TEXTO_SEC)),
                   gridcolor=GRADE, zeroline=False, tickfont=dict(color=TEXTO_MUDO),
                   range=faixa_eixo(tempos_ord.values), autorange=False),
        yaxis=dict(title=None, showgrid=False, tickfont=dict(color=TEXTO_SEC)),
    )
    if TEMPO_INFO[tempo_metrica]["modo"] == "fluxo":
        tempos_sub = (f"{nome_tempo}, considerando os processos baixados/julgados entre {p_ini} e {p_fim} "
                      f"({fase_txt}). Quanto menor, melhor.")
    else:
        tempos_sub = (f"{nome_tempo} na fotografia de {p_fim} ({fase_txt}): há quanto tempo, em média, "
                      "os processos ainda pendentes aguardam. Quanto menor, melhor.")

    # ---------------- KPIs ----------------
    rank_desc = ranking.sort_values(ascending=False)
    posicao = list(rank_desc.index).index(nome_nossa) + 1
    valor_nossa = ranking.get(nome_nossa, 0)
    media_geral = ranking.drop(index=nome_nossa, errors="ignore").mean()

    ref_txt = "no período" if info["tipo"] == "fluxo" else f"em {p_fim}"

    def card(rotulo, valor, detalhe, primeiro=False):
        return html.Div(
            style={"padding": "26px 34px 24px",
                   "borderLeft": "none" if primeiro else f"1px solid {BORDA}"},
            children=[
                html.P(rotulo, style={"fontSize": T_ROT, "color": TEXTO_SEC, "fontWeight": "600",
                                      "textTransform": "uppercase", "letterSpacing": "0.09em",
                                      "margin": "0 0 16px"}),
                html.P(valor, style={"fontSize": T_NUM, "fontWeight": "600", "margin": "0 0 10px",
                                     "letterSpacing": "-0.03em", "lineHeight": "0.92"}),
                html.P(detalhe, style={"fontSize": "16px", "color": TEXTO_MUDO, "margin": 0,
                                       "lineHeight": "1.4"}),
            ],
        )

    maior_menor = "maior" if posicao <= len(rank_desc) / 2 else "menor"
    tempo_nossa = tempos.get(nome_nossa)
    media_tempo_demais = tempos.drop(index=nome_nossa, errors="ignore").mean()
    cards = [
        card("Posição no ranking", f"{posicao}º de {len(rank_desc)}",
             f"{posicao}º {maior_menor} volume de {nome_ind.lower()} {ref_txt}", primeiro=True),
        card(nome_ind, f"{valor_nossa:,.0f}".replace(",", "."),
             f"{nome_nossa}, {ref_txt}"),
        card("Média das demais", f"{media_geral:,.0f}".replace(",", "."),
             f"as outras {len(rank_desc) - 1} auditorias, {ref_txt}"),
        card(TEMPO_INFO[tempo_metrica]["curto"],
             f"{tempo_nossa:,.0f} dias".replace(",", ".") if pd.notna(tempo_nossa) else "—",
             f"nossa · demais: {media_tempo_demais:,.0f} dias".replace(",", ".")
             if pd.notna(media_tempo_demais) else "metodologia CNJ"),
    ]

    return (fig_rank, rank_sub, fig_evo, evo_sub, fig_tempo, tempos_sub,
            tiles, chapeu, periodo_legenda, cards)


if __name__ == "__main__":
    # HOST=0.0.0.0 expõe na rede; o padrão fica só na máquina local.
    import os
    # debug=False: exposto na rede, o modo debug abriria o console do Werkzeug.
    # DEBUG=1 no ambiente religa o hot-reload para desenvolvimento local.
    app.run(debug=os.environ.get("DEBUG") == "1", port=8052,
            host=os.environ.get("HOST", "127.0.0.1"))
