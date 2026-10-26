"""Verifica e atualiza a tabela de alimentação do CNJ sem carregar tudo em memória.

A URL oficial precisa ser configurada em atualizacao_cnj.json. Por padrão,
consulta apenas metadados HTTP. --aplicar baixa, valida e publica os recortes.
Não atualiza STM_tbl_correg.csv: o consolidado tem fonte e esquema próprios.
"""
import argparse
import csv
import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
ARQUIVOS = ('tbl_fato_R.csv', 'auditorias_stm.csv', '2a_auditoria_3a_cjm.csv')
COLUNAS = {'id_orgao_julgador', 'anomes', 'procedimento', 'ind1', 'ind2',
           'ind3', 'ind4', 'ind5', 'ind8a', 'CPJulg', 'TBaixArq', 'SentPri'}
COLUNAS.update('{}{}'.format(m, s) for m in ('ind16', 'ind17', 'ind18', 'ind19')
               for s in ('_dias', '_proc'))
LOG = logging.getLogger('cnj')
BLOCO = 1024 * 1024


class ErroAtualizacao(RuntimeError):
    pass


def agora():
    return datetime.now(timezone.utc).isoformat()


def ler_json(caminho):
    return json.loads(caminho.read_text(encoding='utf-8')) if caminho.exists() else {}


def gravar_json(caminho, valor):
    temporario = caminho.with_suffix(caminho.suffix + '.tmp')
    with temporario.open('w', encoding='utf-8') as arquivo:
        json.dump(valor, arquivo, ensure_ascii=False, indent=2)
        arquivo.flush()
        os.fsync(arquivo.fileno())
    os.replace(str(temporario), str(caminho))


@contextmanager
def trava(diretorio, aguardar=False):
    """O SO libera a trava mesmo se o processo morrer (Linux/WSL)."""
    import fcntl
    diretorio.mkdir(parents=True, exist_ok=True)
    with (diretorio / 'execucao.lock').open('a') as arquivo:
        try:
            modo = fcntl.LOCK_EX if aguardar else fcntl.LOCK_EX | fcntl.LOCK_NB
            fcntl.flock(arquivo, modo)
        except BlockingIOError:
            raise ErroAtualizacao('Outra atualização já está em execução.')
        try:
            yield
        finally:
            fcntl.flock(arquivo, fcntl.LOCK_UN)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            href = dict(attrs).get('href')
            if href:
                self.links.append(href)


def validar_url(url):
    partes = urllib.parse.urlsplit(url)
    if partes.scheme != 'https' or not partes.hostname or partes.username or partes.password:
        raise ErroAtualizacao('Configure uma URL HTTPS pública, sem credenciais embutidas.')
    return url


def url_assinada(url):
    parametros = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    return 'Signature' in parametros or 'X-Amz-Signature' in parametros


def identidade_url(url):
    """Assinaturas renovadas não representam uma nova versão do mesmo objeto."""
    if not url_assinada(url):
        return url
    partes = urllib.parse.urlsplit(url)
    autenticacao = {'AWSAccessKeyId', 'Signature', 'Expires', 'SecurityToken'}
    parametros = [(k, v) for k, v in urllib.parse.parse_qsl(partes.query)
                  if k not in autenticacao and not k.lower().startswith('x-amz-')]
    return urllib.parse.urlunsplit((partes.scheme, partes.netloc, partes.path,
                                   urllib.parse.urlencode(parametros), ''))


def expiracao_url(url):
    parametros = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    if not url_assinada(url):
        return None
    try:
        if 'Expires' in parametros:
            return datetime.fromtimestamp(int(parametros['Expires']), timezone.utc)
        if 'X-Amz-Date' in parametros and 'X-Amz-Expires' in parametros:
            inicio = datetime.strptime(parametros['X-Amz-Date'], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
            return inicio + timedelta(seconds=int(parametros['X-Amz-Expires']))
    except (ValueError, OverflowError, OSError):
        raise ErroAtualizacao('Prazo de validade inválido na URL assinada.')
    raise ErroAtualizacao('URL assinada sem prazo de validade reconhecido.')


def url_valida_agora(url, margem=120):
    fim = expiracao_url(url)
    return fim is None or fim.timestamp() > time.time() + margem


def abrir(url, metodo='GET', headers=None, timeout=60):
    cabecalhos = {'User-Agent': 'CNJ-Indicadores-Atualizador/1.0',
                  'Accept-Encoding': 'identity'}
    cabecalhos.update(headers or {})
    pedido = urllib.request.Request(validar_url(url), headers=cabecalhos, method=metodo)
    resposta = urllib.request.urlopen(pedido, timeout=timeout)
    validar_url(resposta.geturl())
    return resposta


def resolver_url(config):
    direta = config.get('url_tabela_fato')
    arquivo_link = config.get('arquivo_link_temporario')
    caminho_link = None
    if arquivo_link:
        caminho_link = Path(arquivo_link)
        if not caminho_link.is_absolute():
            caminho_link = RAIZ / caminho_link
        if not direta:
            direta = ler_json(caminho_link).get('url')
    if direta and config.get('url_objeto') and identidade_url(direta) != config['url_objeto']:
        raise ErroAtualizacao('O link temporário não corresponde ao objeto configurado.')
    if direta and not config.get('forcar_renovacao_link') and url_valida_agora(direta):
        return validar_url(direta)
    if config.get('renovar_pelo_painel'):
        from descobrir_link_cnj import descobrir_link
        LOG.info('Obtendo um novo link de download pelo painel do CNJ.')
        renovada = validar_url(descobrir_link(config))
        if identidade_url(renovada) != config.get('url_objeto'):
            raise ErroAtualizacao('O painel retornou um objeto diferente da tabela configurada.')
        if not url_valida_agora(renovada):
            raise ErroAtualizacao('O painel retornou uma assinatura já vencida ou prestes a vencer.')
        if caminho_link:
            gravar_json(caminho_link, {'url': renovada})
            caminho_link.chmod(0o600)
        return renovada
    if direta:
        raise ErroAtualizacao('Link de download expirado. Ative renovar_pelo_painel ou informe um novo link.')
    pagina = config.get('pagina_downloads')
    if not pagina:
        raise ErroAtualizacao('Falta a URL de download: preencha url_tabela_fato em atualizacao_cnj.json.')
    with abrir(pagina, timeout=config['timeout_segundos']) as resposta:
        dados = resposta.read(2 * BLOCO + 1)
        if len(dados) > 2 * BLOCO:
            raise ErroAtualizacao('Página de downloads excede 2 MB; use a URL direta.')
        parser = Links()
        parser.feed(dados.decode('utf-8'))
        urls = {urllib.parse.urljoin(resposta.geturl(), link) for link in parser.links}
    nome = config.get('nome_link', 'tbl_fato_R.csv')
    candidatos = [u for u in urls if Path(urllib.parse.unquote(urllib.parse.urlsplit(u).path)).name == nome]
    if len(candidatos) != 1:
        raise ErroAtualizacao('Não foi encontrado um único link para {}. Páginas dinâmicas exigem a URL direta.'.format(nome))
    return validar_url(candidatos[0])


def metadados(resposta, url):
    tamanho = resposta.headers.get('Content-Length')
    return {'url': identidade_url(url), 'etag': resposta.headers.get('ETag'),
            'last_modified': resposta.headers.get('Last-Modified'),
            'bytes': int(tamanho) if tamanho is not None else None}


def mesma_versao(novo, anterior):
    if novo.get('url') != anterior.get('url'):
        return False
    if novo.get('etag') and anterior.get('etag'):
        return novo['etag'] == anterior['etag']
    return bool(novo.get('last_modified') and novo.get('bytes') is not None
                and novo['last_modified'] == anterior.get('last_modified')
                and novo['bytes'] == anterior.get('bytes'))


def sondar(url, config):
    if url_assinada(url):
        # Uma assinatura de GET não autoriza HEAD. Consulta um byte e fecha a
        # resposta; não lê o corpo do ZIP, mesmo se o servidor ignorar Range.
        with abrir(url, headers={'Range': 'bytes=0-0'}, timeout=config['timeout_segundos']) as resposta:
            info = metadados(resposta, url)
            if resposta.status == 206:
                faixa = resposta.headers.get('Content-Range', '')
                total = faixa.rpartition('/')[2]
                if not faixa.startswith('bytes 0-0/') or not total.isdigit():
                    raise ErroAtualizacao('Resposta parcial sem tamanho total válido.')
                info['bytes'] = int(total)
            elif resposta.status != 200:
                raise ErroAtualizacao('Falha ao consultar os metadados do ZIP.')
            return info
    try:
        with abrir(url, metodo='HEAD', timeout=config['timeout_segundos']) as resposta:
            return metadados(resposta, url)
    except urllib.error.HTTPError as exc:
        if exc.code in (405, 501):
            return {'url': identidade_url(url), 'etag': None, 'last_modified': None, 'bytes': None}
        raise


def baixar(url, destino, config, anterior):
    headers = {}
    if anterior.get('url') == identidade_url(url):
        if anterior.get('etag'):
            headers['If-None-Match'] = anterior['etag']
        elif anterior.get('last_modified'):
            headers['If-Modified-Since'] = anterior['last_modified']
    for tentativa in range(config['tentativas']):
        try:
            try:
                resposta = abrir(url, headers=headers, timeout=config['timeout_segundos'])
            except urllib.error.HTTPError as exc:
                if exc.code == 304:
                    return None
                raise
            with resposta:
                if resposta.status != 200:
                    raise ErroAtualizacao('Download retornou HTTP {}, esperado 200.'.format(resposta.status))
                info = metadados(resposta, url)
                tipo = resposta.headers.get('Content-Type', '').lower()
                if 'text/html' in tipo or 'application/json' in tipo:
                    raise ErroAtualizacao('O endereço retornou uma página/JSON em vez do arquivo de dados.')
                if resposta.headers.get('Content-Encoding', 'identity') != 'identity':
                    raise ErroAtualizacao('Codificação HTTP inesperada; configure o download direto do arquivo.')
                livre = shutil.disk_usage(str(destino.parent)).free
                if info['bytes'] and livre < info['bytes'] + 256 * BLOCO:
                    raise ErroAtualizacao('Espaço insuficiente para baixar a nova versão sem apagar a atual.')
                sha = hashlib.sha256()
                tamanho = 0
                with destino.open('wb') as arquivo:
                    while True:
                        bloco = resposta.read(BLOCO)
                        if not bloco:
                            break
                        arquivo.write(bloco)
                        sha.update(bloco)
                        tamanho += len(bloco)
                    arquivo.flush()
                    os.fsync(arquivo.fileno())
                if not tamanho or (info['bytes'] is not None and tamanho != info['bytes']):
                    raise ErroAtualizacao('Download incompleto: tamanho recebido difere do anunciado.')
                info['sha256'] = sha.hexdigest()
                info['bytes'] = tamanho
                return info
        except (OSError, urllib.error.URLError, ErroAtualizacao) as exc:
            if destino.exists():
                destino.unlink()
            if tentativa + 1 == config['tentativas']:
                raise
            LOG.warning('Download falhou (%s); nova tentativa em %ss.', exc, 2 ** tentativa)
            time.sleep(2 ** tentativa)


def preparar_csv(download, destino):
    if zipfile.is_zipfile(str(download)):
        with zipfile.ZipFile(str(download)) as pacote:
            arquivos = [m for m in pacote.infolist() if not m.is_dir()
                        and not m.filename.startswith('__MACOSX/')
                        and not Path(m.filename).name.startswith('._')]
            membros = [m for m in arquivos
                       if Path(m.filename.replace('\\', '/')).name.lower() == 'tbl_fato_r.csv']
            if not membros:
                # O nome distribuído pelo CNJ pode mudar. Só aceita a alternativa
                # se houver um único CSV; as colunas continuam sendo obrigatórias.
                membros = [m for m in arquivos if m.filename.lower().endswith('.csv')]
            if len(membros) != 1:
                nomes = ', '.join(repr(m.filename) for m in arquivos[:20])
                raise ErroAtualizacao('Não foi possível identificar uma única tabela no ZIP. '
                                      'Arquivos encontrados: {}. Esperado tbl_fato_R.csv '
                                      'ou um único CSV com as colunas exigidas.'.format(nomes))
            membro = membros[0]
            LOG.info('Extraindo a tabela do ZIP: %s (%s bytes).', membro.filename, membro.file_size)
            if shutil.disk_usage(str(destino.parent)).free < membro.file_size + 256 * BLOCO:
                raise ErroAtualizacao('Espaço insuficiente para descompactar a nova tabela.')
            with pacote.open(membro) as origem, destino.open('wb') as arquivo:
                shutil.copyfileobj(origem, arquivo, BLOCO)
    else:
        os.replace(str(download), str(destino))
    # Só lê o cabeçalho; o processamento posterior é feito pelo Polars.
    with destino.open('r', encoding='utf-8-sig', newline='') as arquivo:
        cabecalho = arquivo.readline(128 * 1024)
    colunas = set(next(csv.reader([cabecalho], delimiter=';')))
    faltam = COLUNAS - colunas
    if faltam:
        raise ErroAtualizacao('Esquema incompatível. Colunas ausentes: {}'.format(', '.join(sorted(faltam))))


def recuperar(dados, controle):
    """Conclui rollback após interrupção entre substituições; roda sob a trava."""
    diario = controle / 'publicacao.json'
    if not diario.exists():
        return
    registro = ler_json(diario)
    estado = ler_json(controle / 'estado.json')
    if estado.get('publicacao_id') != registro['id']:
        for nome, existia in registro['anteriores'].items():
            destino = dados / nome
            backup = controle / 'anterior' / nome
            if existia:
                if not backup.exists():
                    raise ErroAtualizacao('Backup ausente durante recuperação: {}'.format(nome))
                copia = dados / (nome + '.recuperacao')
                if copia.exists():
                    copia.unlink()
                os.link(str(backup), str(copia))
                os.replace(str(copia), str(destino))
            elif destino.exists():
                destino.unlink()
        LOG.warning('Publicação interrompida: versão anterior restaurada.')
    diario.unlink()


def publicar(staging, dados, controle, estado):
    """Guarda uma versão anterior com hard links; estado.json é o marcador final."""
    anterior = controle / 'anterior'
    if anterior.exists():
        shutil.rmtree(str(anterior))
    anterior.mkdir()
    existentes = {}
    for nome in ARQUIVOS:
        existentes[nome] = (dados / nome).exists()
        if existentes[nome]:
            os.link(str(dados / nome), str(anterior / nome))
    if (controle / 'estado.json').exists():
        shutil.copy2(str(controle / 'estado.json'), str(anterior / 'estado.json'))
    estado['publicacao_id'] = staging.name
    gravar_json(controle / 'publicacao.json', {'id': staging.name, 'anteriores': existentes})
    try:
        for nome in ARQUIVOS:
            os.replace(str(staging / nome), str(dados / nome))
        gravar_json(controle / 'estado.json', estado)
    except BaseException:
        recuperar(dados, controle)
        raise
    (controle / 'publicacao.json').unlink()


def executar(config, aplicar=False):
    dados = Path(config.get('diretorio_dados', 'planilhas'))
    if not dados.is_absolute():
        dados = RAIZ / dados
    controle = dados / '.atualizacao_cnj'
    with trava(controle):
        if aplicar:
            recuperar(dados, controle)
        elif (controle / 'publicacao.json').exists():
            raise ErroAtualizacao('Publicação interrompida; execute --aplicar para recuperar a versão anterior.')
        url = resolver_url(config)
        anterior = ler_json(controle / 'estado.json')
        arquivos_presentes = all((dados / n).exists() for n in ARQUIVOS)
        try:
            remoto = sondar(url, config)
        except urllib.error.HTTPError as exc:
            if exc.code not in (401, 403) or not url_assinada(url) or not config.get('renovar_pelo_painel'):
                raise
            # Credenciais podem ser revogadas antes do prazo Expires.
            LOG.info('Link temporário recusado; solicitando um novo pelo painel.')
            renovacao = dict(config, url_tabela_fato='', arquivo_link_temporario='')
            url = resolver_url(renovacao)
            remoto = sondar(url, config)
        if arquivos_presentes and mesma_versao(remoto, anterior):
            LOG.info('Sem alteração nos metadados da fonte.')
            return 'sem_alteracao'
        if not aplicar:
            LOG.info('Fonte consultada: %s', identidade_url(url))
            LOG.info('Versão nova ou ainda não registrada. Tamanho: %s; Last-Modified: %s; ETag: %s',
                     remoto['bytes'], remoto['last_modified'], remoto['etag'])
            if not remoto['etag'] and not remoto['last_modified']:
                LOG.info('Sem validadores HTTP: a comparação exige download e SHA-256 com --aplicar.')
            return 'pendente'
        with tempfile.TemporaryDirectory(prefix='versao-', dir=str(controle)) as temp:
            staging = Path(temp)
            download = staging / 'download'
            info = baixar(url, download, config, anterior if arquivos_presentes else {})
            if info is None:
                LOG.info('Fonte respondeu 304: nenhuma alteração.')
                return 'sem_alteracao'
            if arquivos_presentes and info['sha256'] == anterior.get('sha256'):
                anterior.update(info)
                anterior['verificado_em'] = agora()
                gravar_json(controle / 'estado.json', anterior)
                LOG.info('Conteúdo idêntico (SHA-256); sem reprocessamento.')
                return 'sem_alteracao'
            preparar_csv(download, staging / ARQUIVOS[0])
            from processar_tbl_fato import processar
            resumo = processar(str(staging / ARQUIVOS[0]), staging, estrito=True)
            # Na primeira execução, compara somente o recorte pequeno já existente.
            referencia = anterior.get('resumo', {})
            if not referencia and (dados / ARQUIVOS[1]).exists():
                import polars as pl
                meses = pl.read_csv(str(dados / ARQUIVOS[1]), separator=';', columns=['anomes'])['anomes']
                referencia = {'primeiro_mes': int(meses.min()), 'ultimo_mes': int(meses.max())}
            if referencia and (resumo['ultimo_mes'] < referencia['ultimo_mes']
                               or resumo['primeiro_mes'] > referencia['primeiro_mes']):
                raise ErroAtualizacao('A nova versão perdeu cobertura histórica; publicação cancelada.')
            info.update({'resumo': resumo, 'publicado_em': agora()})
            publicar(staging, dados, controle, info)
            LOG.info('Versão publicada até %s, com %s auditorias.', resumo['ultimo_mes'], resumo['auditorias'])
            LOG.info('Reinicie os dashboards, ou use executar_paineis.py para reinício automático.')
            return 'atualizado'


def carregar_config(caminho):
    config = {'timeout_segundos': 60, 'tentativas': 3, 'intervalo_horas': 24}
    config.update(ler_json(caminho))
    for nome in ('timeout_segundos', 'tentativas', 'intervalo_horas'):
        if not isinstance(config[nome], (int, float)) or config[nome] <= 0:
            raise ErroAtualizacao('{} deve ser positivo.'.format(nome))
    if not isinstance(config['tentativas'], int) or config['tentativas'] > 5:
        raise ErroAtualizacao('tentativas deve ser um inteiro entre 1 e 5.')
    return config


def executar_cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=RAIZ / 'atualizacao_cnj.json')
    modos = parser.add_mutually_exclusive_group()
    modos.add_argument('--verificar', action='store_true', help='Consulta metadados, sem baixar a tabela (padrão).')
    modos.add_argument('--aplicar', action='store_true', help='Baixa e publica versões novas após validação.')
    parser.add_argument('--monitorar', action='store_true', help='Repete a execução no intervalo configurado.')
    parser.add_argument('--renovar-link', action='store_true',
                        help='Obtém um novo link pelo Chrome, mesmo que o atual ainda seja válido.')
    parser.add_argument('--mostrar-navegador', action='store_true',
                        help='Abre a janela do Chrome para acompanhar a navegação no painel.')
    parser.add_argument('--timeout-painel', type=int,
                        help='Limite de espera por carregamento/cada controle do painel, em segundos (padrão: configuração).')
    args = parser.parse_args()
    if args.timeout_painel is not None and args.timeout_painel <= 0:
        parser.error('--timeout-painel deve ser positivo.')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    while True:
        try:
            config = carregar_config(args.config)
            if args.mostrar_navegador:
                config['navegador_headless'] = False
            if args.timeout_painel is not None:
                config['timeout_painel_segundos'] = args.timeout_painel
            if args.renovar_link:
                if not config.get('renovar_pelo_painel'):
                    raise ErroAtualizacao('--renovar-link requer renovar_pelo_painel na configuração.')
                config['forcar_renovacao_link'] = True
            # Erros de configuração são fatais também no monitor, evitando um serviço inoperante.
            if not config.get('url_tabela_fato') and not config.get('pagina_downloads') and not config.get('renovar_pelo_painel'):
                raise ErroAtualizacao('Configure url_tabela_fato ou pagina_downloads antes de iniciar.')
        except (ValueError, OSError, ErroAtualizacao) as exc:
            LOG.error('%s', exc)
            return 1
        try:
            executar(config, aplicar=args.aplicar)
        except Exception as exc:
            LOG.error('Atualização não concluída: %s', exc)
            if not args.monitorar:
                return 1
        if not args.monitorar:
            return 0
        time.sleep(config['intervalo_horas'] * 3600)


def main():
    try:
        return executar_cli()
    except KeyboardInterrupt:
        LOG.info('Atualização cancelada pelo usuário.')
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
