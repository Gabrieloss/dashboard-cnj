# Indicadores CNJ — Auditorias da Justiça Militar da União

Ferramentas para analisar indicadores do CNJ/DataJud das **19 auditorias da
Justiça Militar da União (JMU)**, com destaque para a **2ª Auditoria da 3ª CJM**.
O projeto reúne três painéis web, processamento de arquivos CSV e ferramentas
opcionais de atualização e geração de gráficos para apresentações.

Os dados são provenientes do CNJ. O painel consolidado apresenta o relatório
destinado à Corregedoria Nacional de Justiça; a Corregedoria não é a produtora
da base.

## Qual painel usar

| Painel | Script | Finalidade | Endereço local |
| --- | --- | --- | --- |
| Individual | `dashboard_app.py` | Evolução dos indicadores da 2ª Auditoria da 3ª CJM | http://127.0.0.1:8050 |
| Comparativo | `dashboard_auditorias.py` | Rankings, evolução e comparação entre as 19 auditorias | http://127.0.0.1:8052 |
| Consolidado oficial | `dashboard_corregedoria.py` | Indicadores do relatório consolidado do CNJ | http://127.0.0.1:8053 |

Os dois primeiros permitem explorar o histórico mensal. O terceiro apresenta
uma janela fixa da exportação oficial: a implementação atual usa **julho de
2025 a junho de 2026**.

## Estrutura e responsabilidade dos arquivos

### Núcleo

| Arquivo ou pasta | Responsabilidade |
| --- | --- |
| `dashboard_*.py` | Interfaces dos três painéis |
| `processar_tbl_fato.py` | Filtra a tabela nacional e gera os dois recortes históricos |
| `assets/` | CSS, JavaScript e fontes locais dos painéis; manter junto dos scripts |
| `planilhas/` | Dados de entrada e recortes gerados, mantidos localmente |
| `requirements.txt` | Dependências dos painéis e do processamento |

### Recursos opcionais

| Arquivo ou pasta | Responsabilidade |
| --- | --- |
| `atualizar_cnj.py` | Consulta a fonte, baixa CSV/ZIP, valida e publica uma nova versão histórica |
| `descobrir_link_cnj.py` | Usa Chrome/Selenium para obter o link temporário pelo painel do CNJ |
| `atualizacao_cnj.json` | Configura fonte, pasta de dados, intervalos e navegação |
| `executar_paineis.py` | Inicia os painéis históricos e os reinicia após uma publicação |
| `scripts/monitorar_cnj.sh` | Executa uma atualização e registra o resultado em log |
| `scripts/agendar_cnj.ps1` | Registra uma tarefa diária no Windows que chama o WSL |
| `expor_rede.ps1` | Configura encaminhamento de portas e firewall no Windows para acesso ao WSL pela rede |
| `graficos_fixos.py` | Gera gráficos trimestrais em PNG para apresentações |
| `tests/` | Testes da atualização, validação, recuperação e navegação simulada |
| `docs/` | Diagramas de arquitetura |
| `AGENTS.md` e `CLAUDE.md` | Orientações de desenvolvimento, definições e decisões do projeto; não são necessários para executar |

## Instalação

Execute a partir da raiz do projeto. O ambiente de referência é Linux/WSL.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

No Windows nativo, os painéis, o processamento manual e os gráficos podem ser
executados com Python. Para ativar o ambiente no PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

O atualizador e o supervisor dependem de Linux/WSL; no Windows, execute esses
dois componentes dentro do WSL.

O código segue convenções de compatibilidade com Python 3.8, mas as dependências
ainda não estão fixadas por versão. A instalação e a execução em Python 3.8 não
foram validadas com um conjunto fechado de dependências.

Instale somente os extras que for utilizar:

```bash
# Gráficos para apresentações
python -m pip install matplotlib

# Renovação de links pelo navegador; requer também Google Chrome instalado
python -m pip install selenium
```

## O que fornecer para rodar em outra máquina

Para abrir os painéis com dados já preparados, basta instalar as dependências
e copiar os CSVs correspondentes para `planilhas/`. Não é necessário informar
usuário, senha ou o caminho da máquina de origem.

| Quero executar | Preciso fornecer | Comando na raiz do projeto |
| --- | --- | --- |
| Painel individual | `planilhas/2a_auditoria_3a_cjm.csv` | `python dashboard_app.py` |
| Comparação das 19 auditorias | `planilhas/auditorias_stm.csv` | `python dashboard_auditorias.py` |
| Consolidado oficial | `planilhas/STM_tbl_correg.csv` com o esquema de junho/2026 | `python dashboard_corregedoria.py` |
| Preparação dos recortes históricos | `planilhas/tbl_fato_R.csv`, extraído do download do CNJ | `python processar_tbl_fato.py` |
| Gráficos PNG | Recorte individual e o pacote `matplotlib` | `python graficos_fixos.py` |
| Atualização automática | Linux/WSL, configuração da fonte, Selenium e Chrome para renovar o link | `python atualizar_cnj.py --verificar` antes de usar `--aplicar` |
| Reinício dos históricos após atualização | Linux/WSL e os dois recortes históricos | `python executar_paineis.py` |

Os arquivos precisam preservar nomes, colunas e separador `;` esperados pelos
scripts. A tabela nacional só é necessária para gerar ou atualizar os recortes;
não é necessária para consultar painéis com recortes prontos.

## Preparação dos dados

Os CSVs não acompanham o repositório. Consulte [planilhas/README.md](planilhas/README.md)
para identificar cada arquivo e sua origem.

### Painéis históricos

1. Acesse o [painel de Estatísticas do Poder Judiciário do CNJ](https://justica-em-numeros.cnj.jus.br/painel-estatisticas/).
2. Em Downloads, obtenha a tabela de alimentação do painel.
3. Caso o download seja um ZIP, extraia o CSV e salve como `planilhas/tbl_fato_R.csv`.
4. Execute:

```bash
python processar_tbl_fato.py
```

O processamento gera `planilhas/auditorias_stm.csv` e
`planilhas/2a_auditoria_3a_cjm.csv`. Confira no terminal a cobertura temporal e
a presença das 19 auditorias. A tabela nacional ocupa vários GB; reserve espaço
também para arquivos temporários e versões anteriores se usar a atualização.

### Painel consolidado

Salve a exportação do Relatório Consolidado como `planilhas/STM_tbl_correg.csv`.
Esse arquivo tem fonte e esquema próprios: **não é gerado pelo processamento da
tabela histórica nem atualizado pelo atualizador**.

A implementação espera colunas como `Pendentes_Jun_2026` e
`Pendentes_Jun_2025`. Uma exportação de outro período pode exigir adaptação do
código e dos rótulos antes de ser utilizada.

## Execução dos painéis

Inicie cada painel desejado em um terminal separado:

```bash
python dashboard_app.py
python dashboard_auditorias.py
python dashboard_corregedoria.py
```

Alternativamente, o supervisor inicia os dois históricos:

```bash
python executar_paineis.py

# Inclui o consolidado, se o respectivo CSV estiver disponível
python executar_paineis.py --com-consolidado
```

Após substituir os CSVs manualmente, reinicie os painéis. O supervisor detecta
publicações do atualizador e reinicia os dois históricos; não detecta qualquer
edição manual nem reinicia automaticamente o consolidado.

O acesso é local por padrão. Para escutar na rede, os dashboards aceitam
`HOST=0.0.0.0`; no WSL, o encaminhamento pelo Windows pode exigir configuração
adicional. O script `expor_rede.ps1` altera firewall e encaminhamento e deve ser
executado no PowerShell como administrador somente se esse acesso for desejado.

## Atualização dos dados históricos

Revise `atualizacao_cnj.json`. Os caminhos relativos são resolvidos a partir da
raiz do projeto. O fluxo atual usa o navegador para obter um link temporário.

| Configuração | O que preencher ou conferir |
| --- | --- |
| `url_painel`, `url_objeto` e `passos_painel` | Já contêm a fonte e os passos conhecidos; revise se o CNJ mudar o endereço ou a navegação |
| `diretorio_dados` | Mantenha `planilhas` para trabalhar com os dashboards e o supervisor |
| `arquivo_link_temporario` | Mantenha `.cnj_link_temporario.json`; o sistema cria esse cache local |
| `renovar_pelo_painel` | `true` para obter links pelo Chrome/Selenium |
| `navegador_headless` | `false` para abrir janela; `true` para executar sem janela |
| `intervalo_horas` | Intervalo usado por `--monitorar`; padrão de 24 horas |
| `timeout_painel_segundos` | Tempo permitido para a navegação; aumente se o painel carregar lentamente |
| `chrome_binario` e `chromedriver` | Campos opcionais: caminhos locais, caso seja necessário indicar manualmente o navegador ou o driver |

Os campos `url_tabela_fato` e `pagina_downloads` podem permanecer vazios no fluxo
de renovação pelo painel. Não coloque links assinados temporários na configuração
versionada. Normalmente o Selenium gerencia o driver; a primeira execução pode
precisar de acesso à rede para obtê-lo.

```bash
# Consulta a fonte sem baixar a tabela completa
python atualizar_cnj.py --verificar

# Força uma nova busca do link, mostrando o navegador
python atualizar_cnj.py --verificar --renovar-link --mostrar-navegador

# Baixa e publica uma versão nova após validação
python atualizar_cnj.py --aplicar

# Repete a atualização no intervalo configurado
python atualizar_cnj.py --aplicar --monitorar
```

O atualizador mantém controle e versão anterior em `planilhas/.atualizacao_cnj/`.
O link temporário fica em `.cnj_link_temporario.json`; ambos são locais e ignorados
pelo Git. Diagnósticos e logs ficam em `logs/`.

A navegação automatizada possui testes simulados. A validação completa do fluxo
real e a ativação do agendamento ainda precisam ser confirmadas no ambiente de
destino; a presença dos scripts não significa que a atualização esteja ativa.

### Agendamento opcional no Windows/WSL

Depois de validar a atualização manualmente, execute no PowerShell do Windows.
Use `wsl -l -q` para consultar as distribuições e `pwd` no terminal WSL, dentro
do projeto, para obter seu caminho absoluto.

```powershell
# Substitua a distribuição e o diretório pelos valores da sua instalação
.\scripts\agendar_cnj.ps1 -Distribuicao "Ubuntu" -Diretorio "/home/SEU_USUARIO/indicadores-cnj-jmu" -Horario "08:00"
```

`-Distribuicao` e `-Diretorio` são obrigatórios; `-Horario` é opcional, com padrão
`08:00`. O diretório informado é o caminho Linux dentro do WSL. A tarefa executa
diariamente enquanto o usuário estiver conectado. O script de monitoramento
usa `.venv/bin/python` quando esse ambiente existe e, caso contrário, `python3`.

## Portabilidade e valores fixos

| Ponto | Situação atual |
| --- | --- |
| Caminhos dos dashboards e do processamento | Usam a localização do script; não dependem do nome do usuário |
| Agendamento no Windows | Sem caminho pessoal padrão; exige `-Diretorio` com o caminho do projeto no WSL e `-Distribuicao` com sua distribuição |
| Gráficos estáticos | Usam os caminhos da pasta do script para ler o recorte em `planilhas/` e gravar em `graficos_saida/` |
| Atualizador e supervisor | Usam `fcntl` para a trava; requerem Linux/WSL, não funcionam diretamente no Python do Windows |
| Diretório de dados | O atualizador aceita `diretorio_dados`, mas os dashboards e o supervisor usam `planilhas/`; mantenha esse padrão para usar o conjunto |
| Auditoria de destaque | ID `32700` e textos da 2ª Auditoria da 3ª CJM estão fixos; mudar o foco exige ajustar processamento e painéis |
| Universo comparado | Os 19 IDs da JMU estão definidos em `processar_tbl_fato.py` |
| Consolidado | Colunas e rótulos vinculados a junho de 2026 |
| Portas | Fixas em 8050, 8052 e 8053; `HOST` e `DEBUG` são configuráveis por ambiente |

## Regras para interpretar os indicadores

- Indicadores de fluxo são somados no período.
- Indicadores de estoque usam o último mês do período, sem somar os meses.
- Tempos médios são calculados como total de dias dividido pelo total de processos.
- Os indicadores sem movimentação e conclusos adotam 120 dias, conforme as colunas da fonte.
- O histórico e o consolidado podem divergir por regras negociais e janelas de referência. Para valores que precisam coincidir com o relatório oficial, use `STM_tbl_correg.csv`.

Definições e decisões adicionais estão em [CLAUDE.md](CLAUDE.md).

## Verificação

```bash
python -m unittest discover -s tests -v
```

Os testes usam dados sintéticos e navegador simulado; não comprovam o download
real nem a renderização dos painéis. Após mudanças nos dashboards, confira
filtros de período, fase e auditoria, os totais e a apresentação no navegador.

## O que entra no Git

Versione código, testes, configuração compartilhada, documentação e assets.
O `.gitignore` exclui dados locais, backups, logs, gráficos gerados, ambientes
virtuais, configurações pessoais e links temporários. Os dados permanecem no
disco e devem ser obtidos separadamente em cada instalação.
