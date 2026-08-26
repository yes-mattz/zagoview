"""Teste do instrumento sem precisar do osciloscopio (sessoes simuladas)."""
import contextlib

import pyvisa
from pyvisa import constants

import instrumento


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
    """Substitui instrumento.sessao por um dicionario endereco -> FalsoScope."""
    limpezas = []

    @contextlib.contextmanager
    def sessao(recurso, timeout=20000, limpar=True):
        limpezas.append((recurso, limpar))
        alvo = mapa[recurso]
        if isinstance(alvo, Exception):
            raise alvo
        yield alvo

    instrumento.sessao = sessao
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
checar("instrumento presente", instrumento.responde(VIVO), True)
checar("endereco fantasma", instrumento.responde(FANTASMA), False)
checar("ocupado por outro programa continua listado",
       instrumento.responde(OCUPADO), True)

print("\n[2] a validacao nao pode perturbar quem esta no meio de uma medida")
checar("nenhum viClear durante a varredura",
       [r for r, limpar in limpezas if limpar], [])

print("\n[3] listar_recursos filtra os que nao respondem")
instrumento.gerenciador = lambda: type("RM", (), {
    "list_resources": staticmethod(lambda: (VIVO, FANTASMA, OCUPADO))})()
checar("so os presentes", instrumento.listar_recursos(validar=True),
       [VIVO, OCUPADO])
checar("sem validar, lista crua", instrumento.listar_recursos(validar=False),
       [VIVO, FANTASMA, OCUPADO])

print("\n[4] o dialeto sai do fabricante declarado no *IDN?")
for idn, esperado in [
    ("KEYSIGHT TECHNOLOGIES,DSO-X 3024T,MY55280502,07.30", "keysight"),
    ("Agilent Technologies,DSO-X 2002A,MY123,02.40", "keysight"),
    ("Rigol Technologies,DSA832E,DSA8G225200243,00.01.04.00.00", "rigol"),
    ("RIGOL TECHNOLOGIES,DS1104Z,DS1ZA1,00.04.04", "rigol"),
    ("Tektronix,TDS2024C,C000000,CF:91.1CT", "keysight"),   # cai no padrao
]:
    checar(f"{idn.split(',')[0][:22]:<22}", instrumento.familia(idn), esperado)

print("\n[5] cada aparelho recebe o comando que entende")
KEYSIGHT = FalsoScope("KEYSIGHT TECHNOLOGIES,DSO-X 3024T,MY5528,07.30")
RIGOL = FalsoScope("Rigol Technologies,DSA832E,DSA8G22,00.01.04")
KEYSIGHT.binario = b"\x89PNG\r\n\x1a\n" + b"0" * 40
RIGOL.binario = b"BM" + b"0" * 60


def query_binary_values(self, cmd, **_k):
    self.comandos.append(cmd)
    return self.binario


FalsoScope.query_binary_values = query_binary_values
simular({"key": KEYSIGHT, "rig": RIGOL})

dados = instrumento.capturar_bytes("key", "PNG", "COLor", inksaver=True)
checar("comando Keysight", KEYSIGHT.comandos[-1], ":DISPlay:DATA? PNG,COLor")
checar("INKSaver so na Keysight", ":HARDcopy:INKSaver ON" in KEYSIGHT.comandos, True)
checar("assinatura reconhecida", instrumento.formato_dos_dados(dados), "PNG")

dados = instrumento.capturar_bytes("rig", "PNG", "COLor", inksaver=True)
checar("comando Rigol", RIGOL.comandos[-1], ":PRIV:SNAP? BMP")
checar("pedir PNG a um Rigol nao manda INKSaver",
       [c for c in RIGOL.comandos if "INKSaver" in c], [])
checar("assinatura reconhecida", instrumento.formato_dos_dados(dados), "BMP")

print("\n[6] a extensao segue o que o aparelho entregou, nao o que foi pedido")
checar("BMP salvo como .png vira .bmp",
       instrumento.ajustar_extensao(r"C:\medidas\tela.png", b"BM" + b"0" * 40),
       r"C:\medidas\tela.bmp")
checar("PNG pedido e PNG entregue: nao mexe",
       instrumento.ajustar_extensao(r"C:\medidas\tela.png",
                                    b"\x89PNG\r\n\x1a\n" + b"0" * 40),
       r"C:\medidas\tela.png")
checar("bytes irreconheciveis: nao inventa extensao",
       instrumento.ajustar_extensao(r"C:\medidas\tela.png", b"???"),
       r"C:\medidas\tela.png")

print("\nTODOS OS TESTES PASSARAM")
