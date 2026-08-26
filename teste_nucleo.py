"""Teste do dsox_core sem precisar do osciloscopio (sessoes simuladas)."""
import contextlib

import pyvisa
from pyvisa import constants

import dsox_core


def erro(codigo):
    return pyvisa.errors.VisaIOError(int(codigo))


class FalsoScope:
    def __init__(self, resposta=None, excecao=None):
        self.resposta = resposta
        self.excecao = excecao
        self.comandos = []

    def query(self, cmd):
        self.comandos.append(cmd)
        if self.excecao:
            raise self.excecao
        return self.resposta

    def write(self, cmd):
        self.comandos.append(cmd)

    def clear(self):
        self.comandos.append("<viClear>")


def simular(mapa):
    """Substitui dsox_core.sessao por um dicionario endereco -> FalsoScope."""
    limpezas = []

    @contextlib.contextmanager
    def sessao(recurso, timeout=20000, limpar=True):
        limpezas.append((recurso, limpar))
        alvo = mapa[recurso]
        if isinstance(alvo, Exception):
            raise alvo
        yield alvo

    dsox_core.sessao = sessao
    return limpezas


def checar(descricao, obtido, esperado):
    ok = obtido == esperado
    print(("  ok  " if ok else "FALHOU") + f"  {descricao}: {obtido!r}")
    assert ok, f"{descricao}: esperado {esperado!r}, obtido {obtido!r}"


VIVO = "USB0::0x2A8D::0x1766::MY55280502::0::INSTR"
FANTASMA = "USB0::0x2A8D::0x1766::MY00000000::0::INSTR"
OCUPADO = "TCPIP0::192.168.0.10::inst0::INSTR"

limpezas = simular({
    VIVO: FalsoScope("KEYSIGHT TECHNOLOGIES,DSO-X 3024T,MY55280502,07.30"),
    FANTASMA: erro(constants.StatusCode.error_resource_not_found),
    OCUPADO: erro(constants.StatusCode.error_resource_busy),
})

print("\n[1] responde() por endereco")
checar("instrumento presente", dsox_core.responde(VIVO), True)
checar("endereco fantasma", dsox_core.responde(FANTASMA), False)
checar("ocupado por outro programa continua listado",
       dsox_core.responde(OCUPADO), True)

print("\n[2] a validacao nao pode perturbar quem esta no meio de uma medida")
checar("nenhum viClear durante a varredura",
       [r for r, limpar in limpezas if limpar], [])

print("\n[3] listar_recursos filtra os que nao respondem")
dsox_core.gerenciador = lambda: type("RM", (), {
    "list_resources": staticmethod(lambda: (VIVO, FANTASMA, OCUPADO))})()
checar("so os presentes", dsox_core.listar_recursos(validar=True),
       [VIVO, OCUPADO])
checar("sem validar, lista crua", dsox_core.listar_recursos(validar=False),
       [VIVO, FANTASMA, OCUPADO])

print("\nTODOS OS TESTES PASSARAM")
