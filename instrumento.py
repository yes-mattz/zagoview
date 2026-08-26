"""
Nucleo de comunicacao com instrumentos SCPI via VISA.

Serve qualquer aparelho que o VISA enxergue e que atenda ao comando
:DISPlay:DATA? - osciloscopios, geradores, analisadores. Foi escrito contra
um Keysight DSO-X 3024T, entao os padroes seguem o dialeto da Keysight.

Este modulo nao tem interface: e usado tanto pela linha de comando
(cli_captura.py) quanto pela interface grafica (gui_captura.py).

Sobre a sessao VISA
-------------------
O ResourceManager do pyvisa e um singleton por biblioteca VISA, e o close()
dele derruba TODAS as conexoes do processo. Por isso mantemos um unico
gerenciador vivo aqui, em vez de abrir e fechar um a cada operacao.

Quando o cabo USB e retirado e recolocado, a sessao antiga fica invalida e a
enumeracao do VISA fica desatualizada: reiniciar() descarta a sessao e forca
uma nova varredura. As operacoes ja fazem isso sozinhas, uma vez, quando
recebem um erro tipico de dispositivo removido.
"""

import contextlib
import datetime
import os
import threading

import pyvisa
from pyvisa import constants

# Sem endereco fixo: a varredura acha o instrumento, seja ele qual for.
# Um endereco chumbado aqui so acertaria em um aparelho, e ficaria errado no
# dia em que ele fosse trocado. Enderecos de rede tambem valem, no formato
# 'TCPIP0::192.168.0.10::inst0::INSTR'.
RECURSO_PADRAO = ""

FORMATOS = ["PNG", "BMP", "BMP8bit"]
EXTENSAO = {"PNG": ".png", "BMP": ".bmp", "BMP8bit": ".bmp"}

PASTA_PADRAO = os.path.join(os.path.expanduser("~"), "Capturas_DSOX")

# Erros que indicam sessao/enumeracao velha (cabo retirado, instrumento
# reiniciado, sessao presa por uma transferencia abortada).
ERROS_DE_SESSAO = {
    constants.StatusCode.error_system_error,
    constants.StatusCode.error_resource_not_found,
    constants.StatusCode.error_resource_busy,
    constants.StatusCode.error_connection_lost,
    constants.StatusCode.error_invalid_object,
    constants.StatusCode.error_io,
}

# Tempo dado a cada leitura de descarte. Nao adianta ser generoso: quando nao
# ha resto nenhum na fila, este e exatamente o tempo que se perde esperando.
DESCARTE_MS = 200
DESCARTE_MAX = 20        # teto de leituras, para nao girar sem fim

_trava = threading.RLock()
_gerenciador = None


def gerenciador():
    """Devolve o ResourceManager unico do processo, criando-o se preciso."""
    global _gerenciador
    with _trava:
        if _gerenciador is not None:
            try:
                _gerenciador.session          # levanta se ja foi fechado
            except pyvisa.errors.InvalidSession:
                _gerenciador = None
        if _gerenciador is None:
            _gerenciador = pyvisa.ResourceManager()
        return _gerenciador


def reiniciar():
    """Fecha a sessao VISA. A proxima operacao reenumera os instrumentos.

    E o equivalente ao 'Rescan' do Connection Expert, feito de dentro do
    programa: resolve o caso do cabo USB retirado e recolocado sem precisar
    fechar a janela.
    """
    global _gerenciador
    with _trava:
        if _gerenciador is not None:
            with contextlib.suppress(Exception):
                _gerenciador.close()
            _gerenciador = None


def _com_retentativa(funcao):
    """Executa funcao; se o erro for de sessao velha, reinicia e tenta 1 vez."""
    try:
        return funcao()
    except pyvisa.errors.VisaIOError as e:
        if e.error_code not in ERROS_DE_SESSAO:
            raise
        reiniciar()
        return funcao()


def _limpar_buffers(scope):
    """Descarta restos de uma transferencia interrompida.

    Se uma captura for abortada no meio (cabo retirado, timeout), a fila de
    saida do instrumento continua com o resto da imagem. Sem isso, a proxima
    leitura devolve os bytes velhos e a imagem sai corrompida.

    Nao usa scope.clear() (viClear) de proposito. O viClear nao respeita o
    timeout da sessao: com um Rigol DSA832E recem-conectado, ele ficou
    120,02 s bloqueado antes de falhar com VI_ERROR_IO, o que aparecia como
    a janela travada em "Consultando *IDN?". Ler ate esvaziar tem o mesmo
    efeito e o prazo esta sob nosso controle.
    """
    with contextlib.suppress(Exception):
        scope.write("*CLS")           # limpa os registradores de status

    antigo = getattr(scope, "timeout", None)
    try:
        scope.timeout = DESCARTE_MS
        for _ in range(DESCARTE_MAX):
            scope.read_raw()          # estoura o timeout quando a fila esvazia
    except Exception:
        pass                          # fila vazia: e o fim esperado
    finally:
        if antigo is not None:
            with contextlib.suppress(Exception):
                scope.timeout = antigo


@contextlib.contextmanager
def sessao(recurso, timeout=20000, limpar=True):
    """Abre o instrumento, garante a limpeza e fecha ao final."""
    with _trava:
        scope = gerenciador().open_resource(recurso)
        try:
            scope.timeout = timeout   # ms - a transferencia da imagem e lenta
            scope.chunk_size = 1024 * 1024
            if limpar:
                _limpar_buffers(scope)
            yield scope
        finally:
            with contextlib.suppress(Exception):
                scope.close()


# Um instrumento ocupado por outro programa continua conectado; nao pode
# sumir da lista so porque nao pode atender agora.
ERROS_DE_OCUPADO = {
    constants.StatusCode.error_resource_busy,
    constants.StatusCode.error_resource_locked,
}


def responde(recurso, timeout=2000, tentativas=2):
    """Confirma que o endereco existe de fato, com um *IDN? curto.

    Nao limpa nada aqui: a varredura passa por todos os instrumentos do PC, e
    mexer na E/S de um aparelho que outro programa esta usando abortaria a
    transferencia dele.

    Tenta duas vezes porque a primeira conversa com um instrumento recem
    conectado pode falhar com VI_ERROR_SYSTEM_ERROR e funcionar em seguida -
    uma unica tentativa apagaria da lista um aparelho que esta ali.
    """
    for restantes in range(tentativas - 1, -1, -1):
        try:
            with sessao(recurso, timeout, limpar=False) as scope:
                return bool(scope.query("*IDN?").strip())
        except pyvisa.errors.VisaIOError as e:
            if e.error_code in ERROS_DE_OCUPADO:
                return True
            if not restantes:
                return False
        except Exception:
            return False
    return False


def listar_recursos(reenumerar=False, validar=True):
    """Lista os instrumentos VISA presentes.

    Com validar=True devolve so os que respondem: o VISA pode continuar
    anunciando um endereco de aparelho ja desligado ou desconectado.
    """
    if reenumerar:
        reiniciar()
    achados = _com_retentativa(lambda: list(gerenciador().list_resources()))
    if not validar:
        return achados
    return [r for r in achados if responde(r)]


def identificar(recurso, timeout=5000):
    """Retorna a resposta de *IDN? (fabricante, modelo, serie, firmware)."""
    def consulta():
        with sessao(recurso, timeout) as scope:
            return scope.query("*IDN?").strip()

    return _com_retentativa(consulta)


def capturar_bytes(recurso, formato="PNG", paleta="COLor", inksaver=False,
                   timeout=20000):
    """Le a imagem da tela do osciloscopio e devolve os bytes brutos."""
    def leitura():
        with sessao(recurso, timeout) as scope:
            # INKSaver ON inverte o fundo para branco (economia de tinta).
            scope.write(f":HARDcopy:INKSaver {'ON' if inksaver else 'OFF'}")
            return scope.query_binary_values(
                f":DISPlay:DATA? {formato},{paleta}",
                datatype="B",
                container=bytes,
            )

    return _com_retentativa(leitura)


def salvar(dados, arquivo):
    """Grava os bytes no disco e devolve o caminho absoluto."""
    destino = os.path.abspath(arquivo)
    pasta = os.path.dirname(destino)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with open(destino, "wb") as f:
        f.write(dados)
    return destino


def nome_automatico(pasta=PASTA_PADRAO, prefixo="tela", formato="PNG"):
    """Monta um caminho com data/hora: <pasta>/<prefixo>_AAAAMMDD_HHMMSS.<ext>"""
    carimbo = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(pasta, f"{prefixo}_{carimbo}{EXTENSAO.get(formato, '.png')}")


def capturar(recurso, arquivo, formato="PNG", paleta="COLor", inksaver=False,
             timeout=20000):
    """Captura e salva em disco. Devolve (caminho, tamanho_em_bytes)."""
    dados = capturar_bytes(recurso, formato, paleta, inksaver, timeout)
    return salvar(dados, arquivo), len(dados)
