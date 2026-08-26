"""
Nucleo de comunicacao com o osciloscopio Keysight DSO-X (serie 3000T) via SCPI.

Este modulo nao tem interface: e usado tanto pela linha de comando
(captura_dsox3024t.py) quanto pela interface grafica (gui_captura.py).

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

# String VISA padrao (Connection Expert).
# Para conexao por rede, use algo como 'TCPIP0::192.168.0.10::inst0::INSTR'
RECURSO_PADRAO = "USB0::0x2A8D::0x1766::MY55280502::0::INSTR"

FORMATOS = ["PNG", "BMP", "BMP8bit"]
EXTENSAO = {"PNG": ".png", "BMP": ".bmp", "BMP8bit": ".bmp"}

PASTA_PADRAO = os.path.join(os.path.expanduser("~"), "Capturas_DSOX")

# Erros que indicam sessao/enumeracao velha (cabo retirado, instrumento
# reiniciado, sessao presa por uma transferencia abortada).
ERROS_DE_SESSAO = {
    constants.StatusCode.error_resource_not_found,
    constants.StatusCode.error_resource_busy,
    constants.StatusCode.error_connection_lost,
    constants.StatusCode.error_invalid_object,
    constants.StatusCode.error_io,
}

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
    """
    with contextlib.suppress(Exception):
        scope.clear()                 # viClear: limpa a E/S do USBTMC
    with contextlib.suppress(Exception):
        scope.write("*CLS")           # limpa os registradores de status


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


def responde(recurso, timeout=2000):
    """Confirma que o endereco existe de fato, com um *IDN? curto.

    Nao usa viClear aqui: a varredura passa por todos os instrumentos do PC e
    limpar a E/S de um aparelho que outro programa esta usando abortaria a
    transferencia dele.
    """
    try:
        with sessao(recurso, timeout, limpar=False) as scope:
            return bool(scope.query("*IDN?").strip())
    except pyvisa.errors.VisaIOError as e:
        return e.error_code in ERROS_DE_OCUPADO
    except Exception:
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
