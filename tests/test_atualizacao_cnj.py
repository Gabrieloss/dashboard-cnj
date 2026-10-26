"""Testes isolados: respostas HTTP simuladas e CSVs sintéticos de poucos KB."""
import csv
import importlib.util
import io
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import atualizar_cnj as app
from processar_tbl_fato import AUDITORIAS_STM


class Resposta(io.BytesIO):
    status = 200

    def __init__(self, body=b'', headers=None):
        super().__init__(body)
        self.headers = headers or {}

    def geturl(self):
        return 'https://exemplo.cnj.jus.br/tbl_fato_R.csv'


def tabela(ids=None, mes=202606):
    out = io.StringIO()
    campos = sorted(app.COLUNAS)
    writer = csv.DictWriter(out, fieldnames=campos, delimiter=';')
    writer.writeheader()
    for orgao in (ids if ids is not None else AUDITORIAS_STM):
        row = dict.fromkeys(campos, 1)
        row.update(id_orgao_julgador=orgao, anomes=mes, procedimento='Conhecimento criminal')
        writer.writerow(row)
    return out.getvalue().encode('utf-8')


class AtualizacaoTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dados = Path(self.temp.name)
        self.config = {'url_tabela_fato': 'https://exemplo.cnj.jus.br/tbl_fato_R.csv',
                       'diretorio_dados': str(self.dados), 'tentativas': 1, 'timeout_segundos': 1}

    def respostas(self, body, etag='"v1"'):
        headers = {'Content-Length': str(len(body)), 'ETag': etag, 'Content-Type': 'text/csv'}
        return [Resposta(headers=headers), Resposta(body, headers)]

    def test_verificar_nao_baixa_arquivo(self):
        with patch.object(app, 'abrir', return_value=Resposta(headers={'ETag': '"v1"'})) as abrir:
            self.assertEqual(app.executar(self.config), 'pendente')
        self.assertEqual(abrir.call_count, 1)
        self.assertEqual(abrir.call_args.kwargs['metodo'], 'HEAD')
        self.assertFalse((self.dados / app.ARQUIVOS[0]).exists())

    def test_publica_e_pula_versao_igual(self):
        body = tabela()
        with patch.object(app, 'abrir', side_effect=self.respostas(body)):
            self.assertEqual(app.executar(self.config, aplicar=True), 'atualizado')
        for nome in app.ARQUIVOS:
            self.assertTrue((self.dados / nome).exists())
        estado = app.ler_json(self.dados / '.atualizacao_cnj' / 'estado.json')
        self.assertEqual(estado['resumo']['auditorias'], 19)
        with patch.object(app, 'abrir', return_value=self.respostas(body)[0]) as abrir:
            self.assertEqual(app.executar(self.config, aplicar=True), 'sem_alteracao')
        self.assertEqual(abrir.call_count, 1)

    def test_dados_invalidos_preservam_arquivos(self):
        for nome in app.ARQUIVOS:
            (self.dados / nome).write_bytes(b'versao anterior')
        body = tabela(ids=[32700])
        with patch.object(app, 'abrir', side_effect=self.respostas(body)):
            with self.assertRaises(ValueError):
                app.executar(self.config, aplicar=True)
        for nome in app.ARQUIVOS:
            self.assertEqual((self.dados / nome).read_bytes(), b'versao anterior')

    def test_download_truncado_nao_publica(self):
        headers = {'Content-Length': '999999', 'ETag': '"v1"'}
        with patch.object(app, 'abrir', side_effect=[Resposta(headers=headers), Resposta(b'abc', headers)]):
            with self.assertRaises(app.ErroAtualizacao):
                app.executar(self.config, aplicar=True)
        self.assertFalse((self.dados / app.ARQUIVOS[0]).exists())

    def test_html_nao_e_tratado_como_csv(self):
        respostas = [Resposta(), Resposta(b'<html/>', {'Content-Type': 'text/html'})]
        with patch.object(app, 'abrir', side_effect=respostas):
            with self.assertRaises(app.ErroAtualizacao):
                app.executar(self.config, aplicar=True)

    def test_sha_igual_nao_reprocessa(self):
        body = tabela()
        with patch.object(app, 'abrir', side_effect=self.respostas(body)):
            app.executar(self.config, aplicar=True)
        with patch.object(app, 'abrir', side_effect=self.respostas(body, '"v2"')):
            with patch('processar_tbl_fato.processar') as processar:
                self.assertEqual(app.executar(self.config, aplicar=True), 'sem_alteracao')
                processar.assert_not_called()

    def test_regressao_de_periodo_nao_substitui(self):
        with patch.object(app, 'abrir', side_effect=self.respostas(tabela(mes=202606))):
            app.executar(self.config, aplicar=True)
        original = (self.dados / app.ARQUIVOS[0]).read_bytes()
        with patch.object(app, 'abrir', side_effect=self.respostas(tabela(mes=202605), '"v2"')):
            with self.assertRaises(app.ErroAtualizacao):
                app.executar(self.config, aplicar=True)
        self.assertEqual((self.dados / app.ARQUIVOS[0]).read_bytes(), original)

    def test_falha_publicacao_restaura_conjunto(self):
        controle = self.dados / '.atualizacao_cnj'
        controle.mkdir()
        staging = controle / 'versao-teste'
        staging.mkdir()
        for nome in app.ARQUIVOS:
            (self.dados / nome).write_bytes(b'antigo')
            (staging / nome).write_bytes(b'novo')
        real_replace = app.os.replace

        def replace(origem, destino):
            if origem == str(staging / app.ARQUIVOS[1]):
                raise OSError('falha simulada')
            return real_replace(origem, destino)

        with patch.object(app.os, 'replace', side_effect=replace):
            with self.assertRaises(OSError):
                app.publicar(staging, self.dados, controle, {})
        for nome in app.ARQUIVOS:
            self.assertEqual((self.dados / nome).read_bytes(), b'antigo')

    def test_zip_nome_alternativo_exige_csv_unico_e_colunas_validas(self):
        import zipfile
        download = self.dados / 'fonte.zip'
        destino = self.dados / 'extraido.csv'
        with zipfile.ZipFile(str(download), 'w') as pacote:
            pacote.writestr('dados/tabela_atual.csv', tabela())
        app.preparar_csv(download, destino)
        self.assertEqual(destino.read_bytes(), tabela())
        with zipfile.ZipFile(str(download), 'w') as pacote:
            pacote.writestr('dados/tabela_atual.csv', 'coluna;outra\n1;2\n')
        with self.assertRaisesRegex(app.ErroAtualizacao, 'Colunas ausentes'):
            app.preparar_csv(download, destino)
        with zipfile.ZipFile(str(download), 'w') as pacote:
            pacote.writestr('primeira.csv', tabela())
            pacote.writestr('segunda.csv', tabela())
        with self.assertRaisesRegex(app.ErroAtualizacao, 'primeira.csv.*segunda.csv'):
            app.preparar_csv(download, destino)

    def test_zip_extrai_somente_csv_esperado(self):
        import zipfile
        download = self.dados / 'download'
        with zipfile.ZipFile(str(download), 'w') as pacote:
            pacote.writestr('../../tbl_fato_R.csv', tabela())
            pacote.writestr('../../ignorar.txt', b'ignorar')
        destino = self.dados / 'tabela.csv'
        app.preparar_csv(download, destino)
        self.assertEqual(destino.read_bytes(), tabela())
        self.assertFalse((self.dados / 'ignorar.txt').exists())

    def test_html_resolve_link_relativo_e_rejeita_ambiguidade(self):
        config = dict(self.config, url_tabela_fato='', pagina_downloads='https://exemplo.cnj.jus.br/downloads/')
        with patch.object(app, 'abrir', return_value=Resposta(b'<a href="/tbl_fato_R.csv">CSV</a>')):
            self.assertEqual(app.resolver_url(config), self.config['url_tabela_fato'])
        html = b'<a href="/a/tbl_fato_R.csv"></a><a href="/b/tbl_fato_R.csv"></a>'
        with patch.object(app, 'abrir', return_value=Resposta(html)):
            with self.assertRaises(app.ErroAtualizacao):
                app.resolver_url(config)

    def test_304_nao_baixa(self):
        erro = urllib.error.HTTPError(self.config['url_tabela_fato'], 304, 'Not Modified', {}, None)
        with patch.object(app, 'abrir', side_effect=erro):
            self.assertIsNone(app.baixar(self.config['url_tabela_fato'], self.dados / 'download', self.config, {}))

    def test_sem_validadores_nao_presume_arquivo_igual(self):
        self.assertFalse(app.mesma_versao({'url': 'x', 'bytes': 3}, {'url': 'x', 'bytes': 3}))

    def test_assinatura_renovada_preserva_identidade(self):
        base = self.config['url_tabela_fato']
        primeira = base + '?AWSAccessKeyId=demo&Signature=antiga&Expires=1'
        segunda = base + '?AWSAccessKeyId=outra&Signature=nova&Expires=4102444800'
        self.assertEqual(app.identidade_url(primeira), base)
        self.assertEqual(app.identidade_url(segunda), base)
        self.assertTrue(app.mesma_versao({'url': app.identidade_url(segunda), 'etag': 'v1'},
                                       {'url': app.identidade_url(primeira), 'etag': 'v1'}))

    def test_sondagem_assinada_usa_get_range_e_tamanho_total(self):
        url = self.config['url_tabela_fato'] + '?Signature=demo&Expires=4102444800'
        resposta = Resposta(b'x', {'Content-Length': '1', 'Content-Range': 'bytes 0-0/123456', 'ETag': 'v1'})
        resposta.status = 206
        with patch.object(resposta, 'read', side_effect=AssertionError('Corpo não deve ser lido')):
            with patch.object(app, 'abrir', return_value=resposta) as abrir:
                info = app.sondar(url, self.config)
        self.assertEqual(info['bytes'], 123456)
        self.assertEqual(info['url'], self.config['url_tabela_fato'])
        self.assertEqual(abrir.call_args.kwargs['headers'], {'Range': 'bytes=0-0'})
        self.assertNotEqual(abrir.call_args.kwargs.get('metodo'), 'HEAD')

    def test_range_ignorado_nao_le_corpo(self):
        url = self.config['url_tabela_fato'] + '?Signature=demo&Expires=4102444800'
        resposta = Resposta(b'zip', {'Content-Length': '123456'})
        with patch.object(resposta, 'read', side_effect=AssertionError('Corpo não deve ser lido')):
            with patch.object(app, 'abrir', return_value=resposta):
                self.assertEqual(app.sondar(url, self.config)['bytes'], 123456)

    def test_url_vencida_nao_e_usada(self):
        config = dict(self.config, url_tabela_fato=self.config['url_tabela_fato'] + '?Signature=demo&Expires=1')
        with self.assertRaisesRegex(app.ErroAtualizacao, 'expirado'):
            app.resolver_url(config)

    def test_renova_e_guarda_link_expirado(self):
        cache = self.dados / 'link.json'
        base = self.config['url_tabela_fato']
        app.gravar_json(cache, {'url': base + '?Signature=demo&Expires=1'})
        config = dict(self.config, url_tabela_fato='', arquivo_link_temporario=str(cache),
                      url_objeto=base, renovar_pelo_painel=True)
        nova = base + '?Signature=demo&Expires=4102444800'
        with patch('descobrir_link_cnj.descobrir_link', return_value=nova) as descobrir:
            self.assertEqual(app.resolver_url(config), nova)
            descobrir.assert_called_once()
        with patch('descobrir_link_cnj.descobrir_link') as descobrir:
            self.assertEqual(app.resolver_url(config), nova)
            descobrir.assert_not_called()
        with patch('descobrir_link_cnj.descobrir_link', return_value=nova) as descobrir:
            self.assertEqual(app.resolver_url(dict(config, forcar_renovacao_link=True)), nova)
            descobrir.assert_called_once()

    def test_renovacao_rejeita_outro_objeto(self):
        config = dict(self.config, url_tabela_fato='', url_objeto=self.config['url_tabela_fato'],
                      renovar_pelo_painel=True)
        with patch('descobrir_link_cnj.descobrir_link', return_value='https://exemplo.cnj.jus.br/outra.zip'):
            with self.assertRaisesRegex(app.ErroAtualizacao, 'diferente'):
                app.resolver_url(config)

    def test_expiracao_sigv4(self):
        url = 'https://exemplo.cnj.jus.br/a?X-Amz-Signature=demo&X-Amz-Date=20261008T180000Z&X-Amz-Expires=3600'
        self.assertEqual(app.expiracao_url(url).isoformat(), '2026-10-08T19:00:00+00:00')

    @unittest.skipUnless(importlib.util.find_spec('selenium'), 'Selenium opcional não instalado')
    def test_busca_rotulo_svg_em_iframe_com_texto_selenium_vazio(self):
        from descobrir_link_cnj import procurar_no_documento
        driver = MagicMock()
        frame = MagicMock()
        controle = MagicMock()
        controle.text = ''
        controle.get_attribute.side_effect = lambda nome: {
            'textContent': ' Downloads ', 'aria-label': '', 'title': ''}.get(nome)
        controle.is_displayed.return_value = True
        driver.find_elements.side_effect = [[], [], [frame], [], [controle]]
        self.assertEqual(procurar_no_documento(
            driver, 'Downloads', self.config['url_tabela_fato']), (None, controle))
        driver.switch_to.frame.assert_called_once_with(frame)
        driver.switch_to.parent_frame.assert_not_called()
        controle.is_displayed.return_value = False
        driver.find_elements.side_effect = [[], [controle], []]
        self.assertEqual(procurar_no_documento(
            driver, 'Downloads', self.config['url_tabela_fato']), (None, None))

    def test_chrome_captura_link_e_bloqueia_download(self):
        try:
            import selenium
        except ImportError:
            self.skipTest('Selenium opcional não instalado')
        import json
        from descobrir_link_cnj import descobrir_link
        driver = MagicMock()
        base = self.config['url_tabela_fato']
        url = base + '?Signature=demo&Expires=4102444800'
        driver.get_log.return_value = [{'message': json.dumps({'message': {
            'method': 'Network.requestWillBeSent', 'params': {'request': {'url': url}}}})}]
        config = dict(self.config, url_objeto=base, url_painel='https://exemplo.cnj.jus.br/painel/')
        with patch('selenium.webdriver.chrome.service.Service'), patch('selenium.webdriver.Chrome', return_value=driver):
            self.assertEqual(descobrir_link(config), url)
        driver.execute_cdp_cmd.assert_any_call('Network.setBlockedURLs', {'urls': ['*tbl_fato_R.csv*']})
        driver.execute_cdp_cmd.assert_any_call('Browser.setDownloadBehavior', {'behavior': 'deny'})
        driver.quit.assert_called_once()

    @unittest.skipUnless(importlib.util.find_spec('selenium'), 'Selenium opcional não instalado')
    def test_fluxo_rola_painel_e_confirma_download_na_nova_janela(self):
        import json
        import descobrir_link_cnj as navegador
        driver = MagicMock()
        base = self.config['url_tabela_fato']
        url = base + '?Signature=demo&Expires=4102444800'
        driver.current_url = 'https://exemplo.cnj.jus.br/painel/'
        driver.window_handles = ['principal']
        driver.get_log.side_effect = [[], [], [], [{'message': json.dumps({'message': {
            'method': 'Network.requestWillBeSent', 'params': {'request': {'url': url}}}})}]]
        downloads, tabela, confirmar = MagicMock(), MagicMock(), MagicMock()
        tabela.click.side_effect = lambda: setattr(driver, 'window_handles', ['principal', 'nova'])
        config = dict(self.config, url_objeto=base, url_painel=driver.current_url)
        with patch('selenium.webdriver.chrome.service.Service'), patch('selenium.webdriver.Chrome', return_value=driver):
            with patch.object(navegador, 'procurar_no_documento', side_effect=[
                    (None, downloads), (None, tabela), (None, None), (None, confirmar)]) as procurar:
                with patch.object(navegador, 'rolar_painel') as rolar, patch.object(navegador.time, 'sleep'):
                    self.assertEqual(navegador.descobrir_link(config), url)
        rolar.assert_called_once_with(driver)
        downloads.click.assert_called_once()
        tabela.click.assert_called_once()
        confirmar.click.assert_called_once()
        driver.switch_to.window.assert_any_call('nova')
        self.assertEqual([c.args[1] for c in procurar.call_args_list],
                         ['Downloads', 'Tabela de alimentação do painel', 'Download', 'Download'])

    @unittest.skipUnless(importlib.util.find_spec('selenium'), 'Selenium opcional não instalado')
    def test_cancelamento_chrome_nao_envia_comando_a_sessao_encerrada(self):
        from descobrir_link_cnj import descobrir_link
        driver = MagicMock()
        driver.get.side_effect = KeyboardInterrupt
        config = dict(self.config, url_objeto=self.config['url_tabela_fato'],
                      url_painel='https://exemplo.cnj.jus.br/painel/')
        with patch('selenium.webdriver.chrome.service.Service'), patch('selenium.webdriver.Chrome', return_value=driver):
            with self.assertRaises(KeyboardInterrupt):
                descobrir_link(config)
        driver.quit.assert_not_called()
        driver.service.stop.assert_called_once()
        driver.command_executor.close.assert_called_once()

    @unittest.skipUnless(importlib.util.find_spec('selenium'), 'Selenium opcional não instalado')
    def test_falha_ao_fechar_chrome_nao_perde_link_encontrado(self):
        import json
        from descobrir_link_cnj import descobrir_link
        driver = MagicMock()
        driver.quit.side_effect = RuntimeError('serviço encerrado')
        base = self.config['url_tabela_fato']
        url = base + '?Signature=demo&Expires=4102444800'
        driver.get_log.return_value = [{'message': json.dumps({'message': {
            'method': 'Network.requestWillBeSent', 'params': {'request': {'url': url}}}})}]
        config = dict(self.config, url_objeto=base, url_painel='https://exemplo.cnj.jus.br/painel/')
        with patch('selenium.webdriver.chrome.service.Service'), patch('selenium.webdriver.Chrome', return_value=driver):
            self.assertEqual(descobrir_link(config), url)
        driver.service.stop.assert_called_once()

    @unittest.skipUnless(importlib.util.find_spec('selenium'), 'Selenium opcional não instalado')
    def test_diagnostico_registra_rotulos_e_frames_sem_query_da_url(self):
        import descobrir_link_cnj as navegador
        driver = MagicMock()
        driver.current_url = 'https://exemplo.cnj.jus.br/painel/?Signature=segredo'
        driver.execute_script.side_effect = [
            {'titulo': 'CNJ', 'controles': [['Downloads'], ['https://exemplo/?Signature=segredo']]},
            {'titulo': 'Relatório', 'controles': [['Tabela de alimentação do painel']]},
        ]
        driver.find_elements.side_effect = [[MagicMock()], []]
        with patch.object(navegador, 'RAIZ', self.dados):
            navegador.salvar_diagnostico(driver, 'Downloads')
        arquivo = self.dados / 'logs' / 'diagnostico_painel_cnj.json'
        dados = app.ler_json(arquivo)
        self.assertEqual(dados['passo'], 'Downloads')
        self.assertEqual(dados['pagina'], 'https://exemplo.cnj.jus.br/painel/')
        self.assertEqual(len(dados['documentos']), 2)
        self.assertEqual(dados['documentos'][1]['frame'], 'principal/0')
        self.assertNotIn('segredo', arquivo.read_text())
        driver.save_screenshot.assert_called_once()

    def test_cli_permite_acompanhar_navegador_sem_alterar_configuracao(self):
        config = dict(self.config, navegador_headless=True)
        argumentos = ['atualizar_cnj.py', '--mostrar-navegador', '--timeout-painel', '30']
        with patch('sys.argv', argumentos), patch.object(app, 'carregar_config', return_value=dict(config)):
            with patch.object(app, 'executar') as executar:
                self.assertEqual(app.main(), 0)
        recebida = executar.call_args.args[0]
        self.assertFalse(recebida['navegador_headless'])
        self.assertEqual(recebida['timeout_painel_segundos'], 30)
        self.assertFalse(executar.call_args.kwargs['aplicar'])
        self.assertTrue(config['navegador_headless'])

    def test_cli_cancelamento_nao_exibe_traceback(self):
        with patch('sys.argv', ['atualizar_cnj.py']), patch.object(app, 'carregar_config', return_value=self.config):
            with patch.object(app, 'executar', side_effect=KeyboardInterrupt):
                self.assertEqual(app.main(), 130)


if __name__ == '__main__':
    unittest.main()
