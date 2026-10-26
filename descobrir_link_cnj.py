"""Obtém o link temporário pela interface pública do painel CNJ.

Selenium + Chrome. O ZIP é bloqueado no navegador: só o atualizador baixa dados.
A navegação depende dos rótulos do painel e deve ser validada na máquina com
acesso ao CNJ. Falhas de carregamento não são contornadas.
"""
import json
import logging
import time
import unicodedata
import urllib.parse
from pathlib import Path


LOG = logging.getLogger('cnj')
RAIZ = Path(__file__).resolve().parent
SELETORES_CONTROLES = ('button, a, [role="button"], [role="tab"], [role="link"], '
                      '[role="menuitem"], [aria-label], [title], svg text, '
                      '.textRun, .navigationItem, .slicerText')


def url_sem_parametros(url):
    partes = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((partes.scheme, partes.netloc, partes.path, '', ''))


def salvar_diagnostico(driver, rotulo):
    """Registra a tela e os rótulos dos frames, sem salvar links assinados."""
    from selenium.webdriver.common.by import By
    diretorio = RAIZ / 'logs'
    documentos = []

    def coletar(caminho, profundidade=0):
        if len(documentos) >= 16:
            return
        # Não inclui href, src, HTML ou texto livre que possa conter assinaturas.
        dados = driver.execute_script('''
            const seletores = arguments[0];
            return {titulo: document.title, controles: Array.from(
                document.querySelectorAll(seletores)).map(e =>
                [e.innerText || e.textContent || '', e.getAttribute('aria-label') || '',
                 e.getAttribute('title') || ''].map(t => t.trim().slice(0, 200)))
                .filter(textos => textos.some(Boolean)).slice(0, 200)};
        ''', SELETORES_CONTROLES)
        # URLs eventualmente usadas como rótulo também ficam fora do arquivo.
        dados['controles'] = [[t for t in textos if '://' not in t and 'Signature=' not in t]
                              for textos in dados['controles']]
        dados['titulo'] = dados['titulo'] if '://' not in dados['titulo'] else '(URL omitida)'
        dados['frame'] = caminho
        documentos.append(dados)
        if profundidade < 6:
            for i, frame in enumerate(driver.find_elements(By.CSS_SELECTOR, 'iframe, frame')):
                if len(documentos) >= 16:
                    break
                try:
                    driver.switch_to.frame(frame)
                except Exception:
                    continue
                try:
                    coletar(caminho + '/' + str(i), profundidade + 1)
                finally:
                    driver.switch_to.parent_frame()

    try:
        diretorio.mkdir(exist_ok=True)
        driver.switch_to.default_content()
        dados = {'passo': rotulo, 'pagina': url_sem_parametros(driver.current_url)}
        captura = diretorio / 'diagnostico_painel_cnj.png'
        if driver.save_screenshot(str(captura)):
            LOG.info('Captura do painel: %s', captura)
        coletar('principal')
        dados['documentos'] = documentos
        destino = diretorio / 'diagnostico_painel_cnj.json'
        destino.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding='utf-8')
        LOG.info('Rótulos encontrados no painel: %s', destino)
    except Exception as exc:
        LOG.warning('Não foi possível completar o diagnóstico (%s).', type(exc).__name__)


def fechar_navegador(driver, interrompido=False):
    try:
        if interrompido:
            # Ctrl+C também pode matar o ChromeDriver no mesmo grupo de processos.
            # Evita enviar DELETE /session a um serviço que já foi encerrado.
            try:
                driver.service.stop()
            finally:
                driver.command_executor.close()
        else:
            driver.quit()
    except Exception as exc:
        LOG.warning('Falha ao encerrar o navegador (%s).', type(exc).__name__)
        try:
            driver.service.stop()
        except Exception:
            pass


def normalizar(texto):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', texto)
                           if not unicodedata.combining(c)).lower().split())


def mesmo_objeto(url, esperado):
    a, b = urllib.parse.urlsplit(url), urllib.parse.urlsplit(esperado)
    return (a.scheme == b.scheme == 'https' and a.netloc == b.netloc
            and urllib.parse.unquote(a.path) == urllib.parse.unquote(b.path))


def link_na_rede(eventos, esperado):
    for evento in eventos:
        mensagem = json.loads(evento['message'])['message']
        if mensagem.get('method') == 'Network.requestWillBeSent':
            url = mensagem['params']['request']['url']
            if mesmo_objeto(url, esperado):
                return url
    return None


def rolar_painel(driver):
    """Rola uma tela no documento/frame atual, inclusive em painéis internos."""
    driver.execute_script('''
        const elementos = Array.from(document.querySelectorAll('*')).filter(e => {
            const estilo = getComputedStyle(e);
            const r = e.getBoundingClientRect();
            return /(auto|scroll)/.test(estilo.overflowY)
                && e.scrollHeight > e.clientHeight && r.width > 0 && r.height > 0;
        }).sort((a, b) => b.clientWidth * b.clientHeight - a.clientWidth * a.clientHeight);
        const alvo = elementos[0] || document.scrollingElement;
        if (alvo) alvo.scrollBy(0, Math.max(400, alvo.clientHeight * 0.75));
    ''')


def procurar_no_documento(driver, rotulo, esperado, profundidade=0):
    """Busca em iframes, incluindo o conteúdo renderizado do Power BI."""
    from selenium.common.exceptions import StaleElementReferenceException, NoSuchFrameException
    from selenium.webdriver.common.by import By
    # Retorna primeiro um link direto, quando o painel já o inclui no DOM.
    for elemento in driver.find_elements(By.CSS_SELECTOR, 'a[href]'):
        try:
            href = elemento.get_attribute('href') or ''
            if mesmo_objeto(href, esperado):
                return href, None
        except StaleElementReferenceException:
            continue
    candidatos = driver.find_elements(By.CSS_SELECTOR, SELETORES_CONTROLES)
    alvo = normalizar(rotulo)
    for elemento in candidatos:
        try:
            # O Power BI pode renderizar o rótulo em SVG/textRun: o Selenium
            # devolve .text vazio embora textContent contenha o texto visível.
            textos = [elemento.text or '', elemento.get_attribute('textContent') or '',
                      elemento.get_attribute('aria-label') or '',
                      elemento.get_attribute('title') or '']
            if any(normalizar(t) == alvo for t in textos):
                driver.execute_script(
                    'arguments[0].scrollIntoView({block: "center", inline: "nearest"});', elemento)
                if not elemento.is_displayed():
                    continue
                # Mantém o driver no frame do elemento até o clique.
                return None, elemento
        except StaleElementReferenceException:
            continue
    if profundidade < 6:
        for frame in driver.find_elements(By.CSS_SELECTOR, 'iframe, frame'):
            try:
                driver.switch_to.frame(frame)
            except (StaleElementReferenceException, NoSuchFrameException):
                continue
            resultado = procurar_no_documento(driver, rotulo, esperado, profundidade + 1)
            if resultado != (None, None):
                return resultado
            driver.switch_to.parent_frame()
    return None, None


def descobrir_link(config):
    from atualizar_cnj import ErroAtualizacao, validar_url
    try:
        from selenium import webdriver
        from selenium.common.exceptions import WebDriverException
        from selenium.webdriver.chrome.service import Service
    except ImportError:
        raise ErroAtualizacao('Renovação do link requer Selenium e Google Chrome. Consulte a seção Atualização dos dados históricos no README.md.')
    pagina = validar_url(config.get('url_painel', ''))
    esperado = validar_url(config.get('url_objeto', ''))
    options = webdriver.ChromeOptions()
    if config.get('navegador_headless', True):
        options.add_argument('--headless=new')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    options.page_load_strategy = 'eager'
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    if config.get('chrome_binario'):
        options.binary_location = config['chrome_binario']
    driver = None
    interrompido = False
    rotulo = 'Carregamento inicial'
    try:
        service = Service(executable_path=config['chromedriver']) if config.get('chromedriver') else Service()
        LOG.info('Iniciando Chrome (%s).', 'sem janela' if config.get('navegador_headless', True) else 'com janela')
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(config.get('timeout_painel_segundos', 90))
        driver.execute_cdp_cmd('Network.enable', {})
        # Bloqueia a requisição do arquivo antes de transferir o ZIP. Os eventos
        # de rede preservam a URL requisitada para o atualizador utilizar.
        nome = urllib.parse.urlsplit(esperado).path.rsplit('/', 1)[-1]
        driver.execute_cdp_cmd('Network.setBlockedURLs', {'urls': ['*' + nome + '*']})
        driver.execute_cdp_cmd('Browser.setDownloadBehavior', {'behavior': 'deny'})
        LOG.info('Abrindo o painel: %s', url_sem_parametros(pagina))
        driver.get(pagina)
        LOG.info('Página carregada; procurando os controles do painel.')
        passos = config.get('passos_painel', ['Downloads', 'Tabela de alimentação do painel', 'Download'])
        for rotulo in passos:
            timeout = config.get('timeout_painel_segundos', 90)
            LOG.info('Procurando %r (limite de %s segundos).', rotulo, timeout)
            inicio = time.monotonic()
            limite = inicio + timeout
            proximo_aviso = inicio + 10
            clicou = False
            while time.monotonic() < limite:
                link = link_na_rede(driver.get_log('performance'), esperado)
                if link:
                    return link
                # Popups podem conter o link/registro do redirecionamento.
                for handle in driver.window_handles:
                    driver.switch_to.window(handle)
                    driver.switch_to.default_content()
                    driver.execute_cdp_cmd('Network.enable', {})
                    driver.execute_cdp_cmd('Network.setBlockedURLs', {'urls': ['*' + nome + '*']})
                    if mesmo_objeto(driver.current_url, esperado):
                        return driver.current_url
                    link, elemento = procurar_no_documento(driver, rotulo, esperado)
                    if link:
                        return link
                    if elemento is not None and not clicou:
                        elemento.click()
                        LOG.info('Controle %r acionado.', rotulo)
                        if normalizar(rotulo) == 'downloads':
                            # Aguarda a mudança de página antes de rolar o frame
                            # em que o controle do Power BI foi encontrado.
                            time.sleep(1)
                            rolar_painel(driver)
                            LOG.info('Painel rolado para baixo após Downloads.')
                        clicou = True
                        break
                if clicou and rotulo != passos[-1]:
                    break
                if time.monotonic() >= proximo_aviso:
                    LOG.info('Aguardando %s: %r (%s segundos).',
                             'o link após o clique em' if clicou else 'o controle',
                             rotulo, int(time.monotonic() - inicio))
                    proximo_aviso = time.monotonic() + 10
                time.sleep(0.5)
            else:
                raise ErroAtualizacao('Não foi possível obter o link no passo {!r}. '
                                      'Confira o carregamento e os rótulos do painel.'.format(rotulo))
        raise ErroAtualizacao('O painel não forneceu uma URL para a tabela configurada.')
    except KeyboardInterrupt:
        interrompido = True
        raise
    except (WebDriverException, RuntimeError, OSError) as exc:
        if driver is not None:
            salvar_diagnostico(driver, rotulo)
        if isinstance(exc, ErroAtualizacao):
            raise
        # Não inclui URLs assinadas que possam estar na mensagem do navegador.
        raise ErroAtualizacao('Não foi possível acessar o painel pelo Chrome ({}). '
                              'Verifique Chrome/ChromeDriver, rede e carregamento do painel.'.format(type(exc).__name__)) from None
    finally:
        if driver is not None:
            fechar_navegador(driver, interrompido=interrompido)
