# Dados locais

Esta pasta contém as entradas e saídas do projeto. Os dados não são versionados;
o `.gitignore` mantém apenas este documento no repositório.

Fonte: [painel de Estatísticas do Poder Judiciário — CNJ/DataJud](https://justica-em-numeros.cnj.jus.br/painel-estatisticas/).
Os CSVs usados pelos scripts têm separador `;`.

| Arquivo | Origem e conteúdo | Uso |
| --- | --- | --- |
| `tbl_fato_R.csv` | Tabela de alimentação do painel, obtida na área Downloads; extraia o ZIP quando necessário | Entrada do processamento histórico; vários GB |
| `auditorias_stm.csv` | Gerado por `processar_tbl_fato.py` | Dashboard comparativo das 19 auditorias |
| `2a_auditoria_3a_cjm.csv` | Gerado por `processar_tbl_fato.py` | Dashboard individual e gráficos estáticos |
| `STM_tbl_correg.csv` | Exportação separada do Relatório Consolidado | Dashboard oficial; o código atual espera o período encerrado em junho de 2026 |
| `Orgaos_julgadores_download.csv` | Cadastro de órgãos julgadores do CNJ | Referência para conferir os IDs; não é necessário em tempo de execução |
| Dicionário de indicadores (`.xlsx`) | Documentação oficial dos indicadores | Consulta; não é necessário em tempo de execução |
| `.atualizacao_cnj/` | Criado pelo atualizador | Controle de publicação, arquivos temporários e versão anterior |

Para preparar os painéis históricos, coloque `tbl_fato_R.csv` nesta pasta e rode,
na raiz do projeto:

```bash
python processar_tbl_fato.py
```

Se já possuir os dois recortes compatíveis, pode utilizá-los diretamente para
abrir os painéis históricos sem manter a tabela nacional na máquina.
Para abrir somente o consolidado, basta fornecer `STM_tbl_correg.csv`.

O consolidado não é produzido a partir dos recortes históricos. Ao usar outra
exportação, confira os nomes das colunas e o período antes de abrir o painel.
