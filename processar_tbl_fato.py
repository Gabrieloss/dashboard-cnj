# =============================================================================
# CÉLULA DE PROCESSAMENTO — tbl_fato_R.csv -> CSVs prontos para os dashboards
#
# Fluxo de uso (toda vez que houver atualização):
#   1. Baixe a nova tbl_fato_R.csv e substitua a antiga no diretório do projeto
#      (mesmo nome de arquivo).
#   2. Rode esta célula.
#   3. Ela regenera os CSVs filtrados usados pelos dashboards.
#
# Requisitos: polars  (pip install polars)
# =============================================================================
from pathlib import Path
from typing import List
import polars as pl

# -----------------------------------------------------------------------------
# Configuração — ajuste apenas aqui se os caminhos mudarem
# -----------------------------------------------------------------------------
DIR_DADOS = Path(__file__).resolve().parent / "planilhas"
ARQUIVO_FATO = str(DIR_DADOS / "tbl_fato_R.csv")   # arquivo grande, sempre com este nome
SEPARADOR = ";"
DIR_SAIDA = DIR_DADOS                              # onde salvar os CSVs de saída

# ID da nossa auditoria (2ª Auditoria da 3ª CJM) — usado para o dashboard individual
NOSSA_AUDITORIA_ID = 32700

# As 19 auditorias da Justiça Militar da União (STM). Fixos no código, conforme
# Orgaos_julgadores_download.csv. O nome fica só para referência/conferência.
AUDITORIAS_STM = {
    32693: "1ª AUDITORIA DA 1ª CJM",
    32694: "2ª AUDITORIA DA 1ª CJM",
    32695: "3ª AUDITORIA DA 1ª CJM",
    32696: "4ª AUDITORIA DA 1ª CJM",   # corrigido: fonte traz '4AUDITORIA' sem espaço
    32697: "1ª AUDITORIA DA 2ª CJM",
    32698: "2ª AUDITORIA DA 2ª CJM",
    32699: "1ª AUDITORIA DA 3ª CJM",
    32700: "2ª AUDITORIA DA 3ª CJM",
    32701: "3ª AUDITORIA DA 3ª CJM",
    32702: "AUDITORIA DA 4ª CJM",
    32703: "AUDITORIA DA 5ª CJM",
    32704: "AUDITORIA DA 6ª CJM",
    32705: "AUDITORIA DA 7ª CJM",
    32706: "AUDITORIA DA 8ª CJM",
    32707: "AUDITORIA DA 9ª CJM",
    32708: "AUDITORIA DA 10ª CJM",
    32709: "1ª AUDITORIA DA 11ª CJM",
    32710: "2ª AUDITORIA DA 11ª CJM",
    32711: "AUDITORIA DA 12ª CJM",
}


# -----------------------------------------------------------------------------
# Funções
# -----------------------------------------------------------------------------
def carregar_lazy(caminho: str) -> pl.LazyFrame:
    """Abre a tabela fato em modo lazy (não carrega os 7GB na memória)."""
    if not Path(caminho).exists():
        raise FileNotFoundError(
            f"'{caminho}' não encontrado no diretório atual. "
            "Confirme que a tbl_fato_R.csv foi colocada na pasta do projeto."
        )
    return pl.scan_csv(caminho, separator=SEPARADOR)


def filtrar_auditorias(lf: pl.LazyFrame, ids: List[int]) -> pl.DataFrame:
    """Filtra apenas as linhas das auditorias informadas e adiciona o nome oficial."""
    nomes = pl.DataFrame(
        {"id_orgao_julgador": list(AUDITORIAS_STM.keys()),
         "nome_auditoria": list(AUDITORIAS_STM.values())}
    )
    return (
        lf.filter(pl.col("id_orgao_julgador").is_in(ids))
        .collect()
        .join(nomes, on="id_orgao_julgador", how="left")
    )


def validar(df: pl.DataFrame, estrito: bool = False) -> None:
    """Confere se todas as auditorias esperadas apareceram e reporta o período coberto."""
    encontrados = set(df["id_orgao_julgador"].unique().to_list())
    esperados = set(AUDITORIAS_STM.keys())
    faltando = esperados - encontrados
    if estrito:
        if df.is_empty() or faltando:
            raise ValueError("Atualização incompleta: faltam auditorias esperadas.")
        meses_invalidos = [m for m in df["anomes"].unique().to_list()
                           if m is None or len(str(m)) != 6
                           or not 1 <= int(str(m)[4:]) <= 12]
        if meses_invalidos:
            raise ValueError("Atualização contém competências inválidas.")
        ultimo = df["anomes"].max()
        ids_ultimo = set(df.filter(pl.col("anomes") == ultimo)["id_orgao_julgador"].unique().to_list())
        if esperados - ids_ultimo:
            raise ValueError("Última competência incompleta: faltam auditorias.")
    if faltando:
        nomes_faltando = [AUDITORIAS_STM[i] for i in faltando]
        print(f"  ATENÇÃO: {len(faltando)} auditoria(s) sem dados nesta base: {nomes_faltando}")

    meses = df["anomes"].unique().sort()
    print(f"  Período coberto: {meses.min()} a {meses.max()}  ({len(meses)} meses)")
    print(f"  Auditorias com dados: {len(encontrados)} de {len(esperados)}")
    print(f"  Total de linhas: {df.height:,}")


def salvar(df: pl.DataFrame, nome_arquivo: str, diretorio: Path = DIR_SAIDA) -> None:
    caminho = diretorio / nome_arquivo
    df.write_csv(caminho, separator=SEPARADOR)
    print(f"  -> {caminho}  ({df.height:,} linhas)")


# -----------------------------------------------------------------------------
# Execução
# -----------------------------------------------------------------------------
def processar(caminho: str = ARQUIVO_FATO, diretorio: Path = DIR_SAIDA,
              estrito: bool = False):
    """Gera os dois recortes; a automação usa um diretório temporário isolado."""
    diretorio.mkdir(parents=True, exist_ok=True)
    print("Lendo tbl_fato_R.csv (lazy)...")
    lf = carregar_lazy(caminho)

    print("\n[1/2] Filtrando todas as 19 auditorias (dashboard comparativo)...")
    df_todas = filtrar_auditorias(lf, list(AUDITORIAS_STM.keys()))
    validar(df_todas, estrito=estrito)
    salvar(df_todas, "auditorias_stm.csv", diretorio)

    print("\n[2/2] Extraindo a nossa auditoria (dashboard individual)...")
    df_nossa = df_todas.filter(pl.col("id_orgao_julgador") == NOSSA_AUDITORIA_ID)
    salvar(df_nossa, "2a_auditoria_3a_cjm.csv", diretorio)

    print("\nConcluído. Rode os dashboards normalmente — eles leem esses CSVs.")
    return {"primeiro_mes": int(df_todas["anomes"].min()),
            "ultimo_mes": int(df_todas["anomes"].max()),
            "auditorias": df_todas["id_orgao_julgador"].n_unique(),
            "linhas": df_todas.height}


if __name__ == "__main__":
    processar()
