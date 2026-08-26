"""
Nucleo de comunicacao com o osciloscopio Keysight DSO-X (serie 3000T) via SCPI.

Este modulo nao tem interface: e usado tanto pela linha de comando
(captura_dsox3024t.py) quanto pela interface grafica (gui_captura.py).
"""

import datetime
import os

import pyvisa

# String VISA padrao (Connection Expert).
# Para conexao por rede, use algo como 'TCPIP0::192.168.0.10::inst0::INSTR'
RECURSO_PADRAO = "USB0::0x2A8D::0x1766::MY55280502::0::INSTR"

FORMATOS = ["PNG", "BMP", "BMP8bit"]
EXTENSAO = {"PNG": ".png", "BMP": ".bmp", "BMP8bit": ".bmp"}

PASTA_PADRAO = os.path.join(os.path.expanduser("~"), "Capturas_DSOX")


def listar_recursos():
    """Devolve a lista de instrumentos VISA visiveis no PC."""
    rm = pyvisa.ResourceManager()
    try:
        return list(rm.list_resources())
    finally:
        rm.close()


def _abrir(recurso, timeout=20000):
    rm = pyvisa.ResourceManager()
    scope = rm.open_resource(recurso)
    scope.timeout = timeout
    scope.chunk_size = 1024 * 1024
    return rm, scope


def identificar(recurso, timeout=5000):
    """Retorna a resposta de *IDN? (fabricante, modelo, serie, firmware)."""
    rm, scope = _abrir(recurso, timeout)
    try:
        return scope.query("*IDN?").strip()
    finally:
        scope.close()
        rm.close()


def capturar_bytes(recurso, formato="PNG", paleta="COLor", inksaver=False,
                   timeout=20000):
    """Le a imagem da tela do osciloscopio e devolve os bytes brutos."""
    rm, scope = _abrir(recurso, timeout)
    try:
        # INKSaver ON inverte o fundo para branco (economia de tinta).
        scope.write(f":HARDcopy:INKSaver {'ON' if inksaver else 'OFF'}")
        return scope.query_binary_values(
            f":DISPlay:DATA? {formato},{paleta}",
            datatype="B",
            container=bytes,
        )
    finally:
        scope.close()
        rm.close()


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
