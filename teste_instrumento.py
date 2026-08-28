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
        # Resposta por comando: sem isto, mudar a resposta para simular o
        # estado da aquisicao tambem mudaria o *IDN?, e o dialeto sairia errado.
        self.respostas = {}

    def query(self, cmd):
        self.comandos.append(cmd)
        if self.excecao:
            raise self.excecao
        return self.respostas.get(cmd, self.resposta)

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
SERIAL = "ASRL4::INSTR"
instrumento.gerenciador = lambda: type("RM", (), {
    "list_resources": staticmethod(
        lambda: (VIVO, FANTASMA, OCUPADO, SERIAL))})()
checar("so os presentes", instrumento.listar_recursos(validar=True),
       [VIVO, OCUPADO])
checar("sem validar, lista crua", instrumento.listar_recursos(validar=False),
       [VIVO, FANTASMA, OCUPADO])

print("\n[3b] portas seriais ficam de fora, e nem sao sondadas")
# Sondar ASRL custa caro e nao serve: numa maquina com Bluetooth aparecem
# varias portas, todas travando. Como a sessao nao configura velocidade nem
# terminacao, instrumento serial tambem nao funcionaria.
sondados = simular({VIVO: FalsoScope("KEYSIGHT,DSO-X,MY5528,07.30"),
                    FANTASMA: erro(constants.StatusCode.error_resource_not_found),
                    OCUPADO: erro(constants.StatusCode.error_resource_busy),
                    SERIAL: erro(constants.StatusCode.error_timeout)})
instrumento.listar_recursos(validar=True)
checar("nenhuma sessao aberta em ASRL",
       [r for r, _ in sondados if r.startswith("ASRL")], [])
checar("com incluir_seriais, a porta volta a lista",
       instrumento.listar_recursos(validar=False, incluir_seriais=True),
       [VIVO, FANTASMA, OCUPADO, SERIAL])

print("\n[4] o dialeto sai do fabricante E do modelo")
for idn, esperado in [
    ("KEYSIGHT TECHNOLOGIES,DSO-X 3024T,MY55280502,07.30", "keysight"),
    ("Agilent Technologies,DSO-X 2002A,MY123,02.40", "keysight"),
    # A Rigol tem familias incompativeis: analisador e osciloscopio nao
    # capturam com o mesmo comando.
    ("Rigol Technologies,DSA832E,DSA8G225200243,00.01.04.00.00", "rigol-dsa"),
    ("Rigol Technologies,DHO814,DHO8A253801426,00.01.02", "rigol-dho"),
    ("RIGOL TECHNOLOGIES,DS1104Z,DS1ZA1,00.04.04", "rigol-dho"),
    ("Tektronix,TDS2024C,C000000,CF:91.1CT", "keysight"),   # cai no padrao
]:
    checar(f"{idn.split(',')[1]:<12}", instrumento.familia(idn), esperado)

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
checar("comando Rigol DSA", RIGOL.comandos[-1], ":PRIV:SNAP? BMP")
checar("pedir PNG a um Rigol nao manda INKSaver",
       [c for c in RIGOL.comandos if "INKSaver" in c], [])
checar("assinatura reconhecida", instrumento.formato_dos_dados(dados), "BMP")

# O osciloscopio da Rigol nao entende o comando do analisador: pede a tela
# com :DISPlay:DATA?, sem o argumento de paleta que a Keysight exige.
DHO = FalsoScope("Rigol Technologies,DHO814,DHO8A253801426,00.01.02")
DHO.binario = bytes((0xFF, 0xD8, 0xFF)) + b"0" * 40
simular({"key": KEYSIGHT, "rig": RIGOL, "dho": DHO})
dados = instrumento.capturar_bytes("dho", "PNG", "COLor")
checar("comando Rigol DHO", DHO.comandos[-1], ":DISPlay:DATA? PNG")
checar("sem argumento de paleta", "COLor" in DHO.comandos[-1], False)
checar("assinatura JPEG reconhecida",
       instrumento.formato_dos_dados(dados), "JPG")
checar("e ganha a extensao certa",
       instrumento.ajustar_extensao(r"C:\m\tela.png", dados), r"C:\m\tela.jpg")

instrumento.run_stop("dho", False)
checar("DHO roda com :RUN", DHO.comandos[-1], ":RUN")
DHO.respostas[":TRIGger:STATus?"] = "TD"
checar("TD conta como rodando", instrumento.estado_aquisicao("dho"), True)
DHO.respostas[":TRIGger:STATus?"] = "STOP"
checar("STOP conta como parado", instrumento.estado_aquisicao("dho"), False)

print("\n[7] Run/Stop usa o comando de cada fabricante")
checar("novo estado apos RUN", instrumento.run_stop("key", False), True)
checar("Keysight roda com :RUN", KEYSIGHT.comandos[-1], ":RUN")
checar("novo estado apos STOP", instrumento.run_stop("key", True), False)
checar("Keysight para com :STOP", KEYSIGHT.comandos[-1], ":STOP")

# O DSA800 nao tem :RUN; a aquisicao dele e :INITiate:CONTinuous.
instrumento.run_stop("rig", False)
checar("Rigol roda com INIT:CONT", RIGOL.comandos[-1], ":INITiate:CONTinuous ON")
instrumento.run_stop("rig", True)
checar("Rigol para com INIT:CONT", RIGOL.comandos[-1], ":INITiate:CONTinuous OFF")

print("\n[7b] estado da aquisicao: quem sabe responder, e quem nao sabe")
RIGOL.respostas[":INITiate:CONTinuous?"] = "1"
checar("Rigol diz que esta rodando", instrumento.estado_aquisicao("rig"), True)
RIGOL.respostas[":INITiate:CONTinuous?"] = "0"
checar("Rigol diz que esta parado", instrumento.estado_aquisicao("rig"), False)
RIGOL.respostas[":INITiate:CONTinuous?"] = "lixo"
checar("resposta ininteligivel vira desconhecido",
       instrumento.estado_aquisicao("rig"), None)
# O Keysight deste firmware nao tem consulta: o dialeto traz None.
checar("Keysight nao sabe informar", instrumento.estado_aquisicao("key"), None)
checar("e nem chega a perguntar",
       [c for c in KEYSIGHT.comandos if "CONT" in c or "RSTate" in c], [])

print("\n[7c] o idn ja confirmado evita perguntar de novo")
# Foi o segundo *IDN?, dentro da captura, que voltou fora de sincronia num
# Rigol DHO804: o programa classificou o osciloscopio como Keysight e mandou
# :HARDcopy:INKSaver, que o aparelho devolveu como eco.
DHO.comandos.clear()
instrumento.capturar_bytes("dho", "PNG", "COLor",
                           idn="Rigol Technologies,DHO814,DHO8A25,00.01")
checar("nao perguntou o *IDN? de novo",
       [c for c in DHO.comandos if "IDN" in c], [])
checar("e usou o dialeto certo", DHO.comandos[-1], ":DISPlay:DATA? PNG")

DHO.comandos.clear()
instrumento.capturar_bytes("dho", "PNG", "COLor")
checar("sem idn, pergunta", [c for c in DHO.comandos if "IDN" in c], ["*IDN?"])

print("\n[7d] resposta fora de sincronia falha em vez de chutar Keysight")
for ruim in ("", ":HARDcopy:INKSaver OFF", "*IDN?", "lixo"):
    checar(f"{ruim[:24]!r:<28} nao serve como idn",
           instrumento.idn_utilizavel(ruim), False)
checar("um *IDN? de verdade serve",
       instrumento.idn_utilizavel("Rigol Technologies,DHO814,DHO8A25,00.01"),
       True)

ECO = FalsoScope(":HARDcopy:INKSaver OFF")     # devolve o eco do comando
ECO.binario = b"BM" + b"0" * 40
simular({"eco": ECO})
try:
    instrumento.capturar_bytes("eco", "PNG", "COLor")
    checar("deveria ter falhado", True, False)
except instrumento.RespostaInvalida as e:
    checar("vira RespostaInvalida", "nao respondeu ao *IDN?" in str(e), True)
checar("e nenhum comando de dialeto foi enviado",
       [c for c in ECO.comandos if "INKSaver" in c or "DISPlay" in c], [])

print("\n[8] a extensao segue o que o aparelho entregou, nao o que foi pedido")
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
