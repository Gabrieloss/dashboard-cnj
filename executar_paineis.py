"""Inicia os painéis e reinicia os dois históricos após publicação de dados.

Execute no lugar de iniciar dashboard_app.py e dashboard_auditorias.py separados.
Ctrl+C encerra apenas os subprocessos criados por este supervisor.
"""
import argparse
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from atualizar_cnj import RAIZ, ler_json, recuperar, trava

LOG = logging.getLogger('paineis')


def assinatura(caminho):
    return ler_json(caminho).get('publicacao_id')


def iniciar(script):
    env = dict(os.environ)
    env['DEBUG'] = '0'
    LOG.info('Iniciando %s', script)
    return subprocess.Popen([sys.executable, str(RAIZ / script)], env=env)


def parar(processo):
    if processo.poll() is None:
        processo.terminate()
        try:
            processo.wait(timeout=10)
        except subprocess.TimeoutExpired:
            processo.kill()
            processo.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--com-consolidado', action='store_true', help='Também inicia o painel da Corregedoria.')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    scripts = ['dashboard_app.py', 'dashboard_auditorias.py']
    if args.com_consolidado:
        scripts.append('dashboard_corregedoria.py')
    controle = RAIZ / 'planilhas' / '.atualizacao_cnj'
    processos = {}

    def encerrar(_sig, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, encerrar)
    try:
        # Não inicia com uma publicação parcial deixada por uma interrupção.
        with trava(controle, aguardar=True):
            recuperar(RAIZ / 'planilhas', controle)
            anterior = assinatura(controle / 'estado.json')
            for script in scripts:
                processos[script] = iniciar(script)
        while True:
            time.sleep(5)
            for script, processo in processos.items():
                if processo.poll() is not None:
                    raise RuntimeError('{} encerrou com código {}. Confira os logs acima.'.format(script, processo.returncode))
            atual = assinatura(controle / 'estado.json')
            if atual != anterior and not (controle / 'publicacao.json').exists():
                # estado.json só é publicado depois dos três CSVs; a trava impede
                # uma nova atualização enquanto iniciamos os processos.
                with trava(controle, aguardar=True):
                    for script in scripts[:2]:
                        parar(processos[script])
                        processos[script] = iniciar(script)
                    anterior = assinatura(controle / 'estado.json')
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        LOG.error('%s', exc)
        return 1
    finally:
        for processo in processos.values():
            parar(processo)


if __name__ == '__main__':
    raise SystemExit(main())
