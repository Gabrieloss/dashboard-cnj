"""
Gráficos fixos - 2ª Auditoria da 3ª CJM (STM)
Gera PNGs prontos para inserir em slides/apresentação.
Dados consolidados por TRIMESTRE (menos ruído visual que granularidade mensal).

Lê planilhas/2a_auditoria_3a_cjm.csv e salva em graficos_saida/,
sempre a partir da pasta deste script.
"""

import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
RAIZ = Path(__file__).resolve().parent
CSV_PATH = RAIZ / "planilhas" / "2a_auditoria_3a_cjm.csv"
OUTPUT_DIR = RAIZ / "graficos_saida"
OUTPUT_DIR.mkdir(exist_ok=True)

plt.rcParams.update({
    "font.size": 13,
    "axes.titlesize": 16,
    "axes.titleweight": "bold",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "figure.figsize": (11, 5.5),
    "figure.dpi": 150,
})

COLORS = {
    "casos_novos": "#2a78d6",
    "pendentes": "#eb6834",
    "pendentes_nao_julg": "#e34948",
    "baixados": "#1baf7a",
    "julgados": "#4a3aa7",
}

PROC_COLORS = {
    "Conhecimento criminal": "#2a78d6",
    "Fase investigatória": "#eb6834",
    "Outros": "#1baf7a",
    "Execução penal não privativa de liberdade": "#eda100",
    "Execução penal privativa de liberdade": "#e34948",
}

# ---------------------------------------------------------------------------
# Carga e preparação
# ---------------------------------------------------------------------------
def carregar_dados(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    df["data"] = pd.to_datetime(df["anomes"].astype(str), format="%Y%m")
    df["trimestre"] = df["data"].dt.to_period("Q")

    fluxo_cols = ["ind1", "ind3", "TBaixArq", "ind8a", "SentPri"]
    for c in fluxo_cols:
        if c in df.columns:
            df[c] = df[c].fillna(0)

    return df


def rotulo_trimestre(periodo: pd.Period) -> str:
    return f"{periodo.year}-T{periodo.quarter}"


def agrega_trimestral(df: pd.DataFrame) -> pd.DataFrame:
    """Fluxos (ind1, ind3, TBaixArq, ind8a, SentPri) somados no trimestre;
    estoques (ind2, CPJulg) usam o valor do último mês do trimestre (foto final)."""
    fluxo = ["ind1", "ind3", "TBaixArq", "ind8a", "SentPri"]
    fluxo = [c for c in fluxo if c in df.columns]
    estoque = [c for c in ["ind2", "CPJulg"] if c in df.columns]

    soma_fluxo = df.groupby("trimestre")[fluxo].sum(min_count=1)

    ultimo_mes = df.sort_values("data").groupby("trimestre")["data"].max().reset_index()
    snap = df.merge(ultimo_mes, on=["trimestre", "data"])
    soma_estoque = snap.groupby("trimestre")[estoque].sum(min_count=1)

    out = soma_fluxo.join(soma_estoque).reset_index().sort_values("trimestre")
    out["rotulo"] = out["trimestre"].apply(rotulo_trimestre)
    return out


def agrega_por_procedimento_trimestral(df: pd.DataFrame, coluna: str) -> pd.DataFrame:
    piv = df.pivot_table(index="trimestre", columns="procedimento", values=coluna, aggfunc="sum")
    piv = piv.sort_index()
    piv.index = [rotulo_trimestre(p) for p in piv.index]
    return piv


def eixo_x_trimestral(ax, rotulos):
    """Mostra todos os trimestres, mas só escreve o texto a cada 4 (1x/ano) para não poluir."""
    ax.set_xticks(range(len(rotulos)))
    labels = [r if i % 2 == 0 else "" for i, r in enumerate(rotulos)]
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=10)


# ---------------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------------
def grafico_casos_novos_vs_julgados(t: pd.DataFrame):
    fig, ax = plt.subplots()
    x = range(len(t))
    largura = 0.4
    ax.bar([i - largura / 2 for i in x], t["ind1"], width=largura,
           label="Casos novos", color=COLORS["casos_novos"])
    ax.bar([i + largura / 2 for i in x], t["ind8a"], width=largura,
           label="Julgados", color=COLORS["julgados"])
    eixo_x_trimestral(ax, t["rotulo"].tolist())
    ax.set_title("Casos novos vs. julgados por trimestre")
    ax.set_ylabel("Processos")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "01_casos_novos_vs_julgados.png")
    plt.close(fig)


def grafico_pendentes(t: pd.DataFrame):
    fig, ax = plt.subplots()
    x = range(len(t))
    ax.plot(x, t["ind2"], label="Pendentes (total, fim do trimestre)",
            color=COLORS["pendentes"], linewidth=2.5, marker="o", markersize=4)
    ax.plot(x, t["CPJulg"], label="Pendentes não julgados (fim do trimestre)",
            color=COLORS["pendentes_nao_julg"], linewidth=2.5, linestyle="--", marker="o", markersize=4)
    eixo_x_trimestral(ax, t["rotulo"].tolist())
    ax.set_title("Acervo pendente por trimestre")
    ax.set_ylabel("Processos")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "02_pendentes.png")
    plt.close(fig)


def grafico_baixados(t: pd.DataFrame):
    fig, ax = plt.subplots()
    x = range(len(t))
    ax.bar(x, t["TBaixArq"], color=COLORS["baixados"])
    eixo_x_trimestral(ax, t["rotulo"].tolist())
    ax.set_title("Processos baixados/arquivados por trimestre")
    ax.set_ylabel("Processos")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "03_baixados.png")
    plt.close(fig)


def grafico_composicao_procedimento(df: pd.DataFrame):
    piv = agrega_por_procedimento_trimestral(df, "ind1")
    fig, ax = plt.subplots()
    x = range(len(piv))
    baixo = [0] * len(piv)
    for col in piv.columns:
        vals = piv[col].fillna(0).tolist()
        ax.bar(x, vals, bottom=baixo, label=col, color=PROC_COLORS.get(col, "#888"))
        baixo = [b + v for b, v in zip(baixo, vals)]
    eixo_x_trimestral(ax, piv.index.tolist())
    ax.set_title("Casos novos por tipo de procedimento (trimestral)")
    ax.set_ylabel("Processos")
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "04_composicao_procedimento.png")
    plt.close(fig)


def grafico_indice_atendimento_demanda(t: pd.DataFrame):
    """IAD = TBaix / Cn dos últimos 12 meses (últimos 4 trimestres) - >=100% é bom sinal."""
    janela = t.tail(4)
    iad = janela["TBaixArq"].sum() / janela["ind1"].sum() * 100 if janela["ind1"].sum() else 0

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.pie(
        [min(iad, 100), max(100 - iad, 0)] if iad <= 100 else [100],
        colors=[COLORS["baixados"], "#e1e0d9"],
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.35},
    )
    ax.text(0, 0, f"{iad:.0f}%", ha="center", va="center", fontsize=28, fontweight="bold")
    ax.set_title("Índice de Atendimento à Demanda\n(últimos 4 trimestres)")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "05_indice_atendimento_demanda.png")
    plt.close(fig)


def main():
    df = carregar_dados(CSV_PATH)
    t = agrega_trimestral(df)

    grafico_casos_novos_vs_julgados(t)
    grafico_pendentes(t)
    grafico_baixados(t)
    grafico_composicao_procedimento(df)
    grafico_indice_atendimento_demanda(t)

    print(f"Gráficos salvos em: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
