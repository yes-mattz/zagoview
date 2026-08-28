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
import re
import threading

import pyvisa
from pyvisa import constants

# Sem endereco fixo: a varredura acha o instrumento, seja ele qual for.
# Um endereco chumbado aqui so acertaria em um aparelho, e ficaria errado no
# dia em que ele fosse trocado. Enderecos de rede tambem valem, no formato
# 'TCPIP0::192.168.0.10::inst0::INSTR'.
RECURSO_PADRAO = ""

FORMATOS = ["PNG", "BMP", "BMP8bit"]
EXTENSAO = {"PNG": ".png", "BMP": ".bmp", "BMP8bit": ".bmp", "JPG": ".jpg"}

# Cada fabricante entrega a tela de um jeito. Os comandos abaixo foram
# verificados contra os aparelhos, nao deduzidos do manual:
#
#   Keysight  :DISPlay:DATA? <formato>,<paleta>   PNG ou BMP, com INKSaver
#   Rigol     :PRIV:SNAP? BMP                     so BMP, ~1,1 MB, ~4,4 s
#
# O comando do Rigol nao esta no manual de programacao da serie DSA800 - la
# so existe :MMEMory:STORe:SCReen, que grava num pendrive espetado no
# aparelho e nao manda nada pelo cabo. O :PRIV:SNAP? vem do lxi-tools
# (plugins/screenshot_rigol-dsa.c) e responde certo no DSA832E.
DIALETOS = {
    "keysight": {
        "formatos": ["PNG", "BMP", "BMP8bit"],
        "inksaver": True,
        "comando": lambda formato, paleta: f":DISPlay:DATA? {formato},{paleta}",
        # O :RSTate? existe na documentacao da serie, mas nao responde no
        # DSO-X 3024T com firmware 04.06.2015 - nem o :OPERegister:CONDition?
        # muda entre rodando e parado. Por isso a consulta fica vazia.
        "aquisicao": {"rodar": ":RUN", "parar": ":STOP", "consulta": None},
    },
    # Analisadores de espectro da serie DSA800.
    "rigol-dsa": {
        "formatos": ["BMP"],
        "inksaver": False,
        "comando": lambda formato, paleta: ":PRIV:SNAP? BMP",
        # A serie DSA800 nao tem :RUN; a aquisicao liga e desliga pelo
        # :INITiate:CONTinuous, que ainda por cima sabe informar o estado.
        "aquisicao": {"rodar": ":INITiate:CONTinuous ON",
                      "parar": ":INITiate:CONTinuous OFF",
                      "consulta": ":INITiate:CONTinuous?"},
    },
    # Osciloscopios DHO800/DHO900. Nao falam a mesma lingua dos analisadores:
    # aqui o comando e documentado, aceita PNG e devolve bloco com cabecalho
    # TMC (#9...), o mesmo formato que ja lemos.
    "rigol-dho": {
        "formatos": ["PNG", "BMP", "JPG"],
        "inksaver": False,
        "comando": lambda formato, paleta: f":DISPlay:DATA? {formato}",
        "aquisicao": {"rodar": ":RUN", "parar": ":STOP",
                      "consulta": ":TRIGger:STATus?"},
    },
}

# So o fabricante nao basta para escolher o dialeto: a Rigol tem familias que
# nao falam a mesma lingua. A primeira regra que servir vence, e as mais
# especificas vem antes.
REGRAS_DE_DIALETO = (
    # (marcas no fabricante, padrao do modelo, dialeto)
    (("rigol",), r"DSA", "rigol-dsa"),
    (("rigol",), r"DHO", "rigol-dho"),
    # Outros Rigol caem no dialeto dos osciloscopios: o :DISPlay:DATA? e
    # documentado e comum a varias linhas, enquanto o :PRIV:SNAP? nao esta em
    # manual nenhum. Nao verificado fora do DHO800.
    (("rigol",), None, "rigol-dho"),
    # Agilent e o nome antigo da Keysight, e os aparelhos falam o mesmo dialeto.
    (("keysight", "agilent", "hewlett"), None, "keysight"),
)
DIALETO_PADRAO = "keysight"

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


class RespostaInvalida(RuntimeError):
    """O instrumento respondeu algo que nao da para interpretar.

    Acontece quando a sessao sai de sincronia e cada leitura devolve a
    resposta da rodada anterior - foi assim que um Rigol DHO804 recebeu um
    comando do dialeto Keysight e devolveu o eco dele.
    """


class VisaAusente(RuntimeError):
    """Nao ha implementacao VISA utilizavel nesta maquina.

    E diferente de "nenhum instrumento encontrado": sem VISA nao existe nem
    como procurar, e a saida e instalar uma implementacao - qualquer uma que
    siga o padrao IVI.
    """


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
            _gerenciador = _abrir_gerenciador()
        return _gerenciador


def _abrir_gerenciador():
    """Abre o ResourceManager, traduzindo a falta de VISA num erro proprio."""
    try:
        return pyvisa.ResourceManager()
    except pyvisa.errors.VisaIOError as e:
        if e.error_code == constants.StatusCode.error_library_not_found:
            raise VisaAusente(str(e)) from e
        raise
    except OSError as e:
        # LibraryError herda de OSError; e o que sai quando nao ha DLL alguma.
        raise VisaAusente(str(e)) from e


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


def listar_recursos(reenumerar=False, validar=True, incluir_seriais=False):
    """Lista os instrumentos VISA presentes.

    Com validar=True devolve so os que respondem: o VISA pode continuar
    anunciando um endereco de aparelho ja desligado ou desconectado.

    Portas seriais (ASRL) ficam de fora por padrao. O VISA lista toda porta
    COM da maquina, tenha ou nao instrumento do outro lado, e sondar cada uma
    custa caro: num notebook com Bluetooth ativo apareceram quatro portas, e
    todas travaram - duas no tempo de escrita, duas sem nem abrir. Como esta
    sessao tambem nao configura velocidade nem terminacao, um instrumento
    serial de verdade nao funcionaria; sondar ASRL hoje e so custo.
    """
    if reenumerar:
        reiniciar()
    achados = _com_retentativa(lambda: list(gerenciador().list_resources()))
    if not incluir_seriais:
        achados = [r for r in achados if not r.upper().startswith("ASRL")]
    if not validar:
        return achados
    return [r for r in achados if responde(r)]


def identificar(recurso, timeout=5000):
    """Retorna a resposta de *IDN? (fabricante, modelo, serie, firmware)."""
    def consulta():
        with sessao(recurso, timeout) as scope:
            return scope.query("*IDN?").strip()

    return _com_retentativa(consulta)


def idn_utilizavel(idn):
    """Diz se a resposta parece mesmo um *IDN?.

    O formato e "FABRICANTE,MODELO,SERIE,FIRMWARE". Quando a sessao esta
    dessincronizada, a leitura devolve o eco do comando anterior em vez da
    resposta - e ai escolher dialeto pelo conteudo seria pior que nao
    escolher: cairia no padrao Keysight, o unico que escreve um comando a
    mais antes de ler, sujando a sessao ainda mais.
    """
    return bool(idn) and idn.count(",") >= 2


def _dialeto_de(scope, idn):
    """Escolhe o dialeto a partir do idn ja conhecido, ou perguntando."""
    if not idn:
        idn = scope.query("*IDN?").strip()
    if not idn_utilizavel(idn):
        raise RespostaInvalida(
            "O instrumento nao respondeu ao *IDN? de forma reconhecivel.\n"
            f"Veio: {idn[:120]!r}")
    return DIALETOS[familia(idn)]


def run_stop(recurso, rodando, timeout=5000, idn=None):
    """Alterna a aquisicao e devolve o novo estado.

    O comando muda com o aparelho: o Keysight usa :RUN/:STOP, e o Rigol da
    serie DSA800 nao tem :RUN - a aquisicao dele liga e desliga por
    :INITiate:CONTinuous. Passe o idn ja confirmado na conexao para evitar
    uma consulta a mais.
    """
    def acao():
        with sessao(recurso, timeout) as scope:
            aquisicao = _dialeto_de(scope, idn)["aquisicao"]
            scope.write(aquisicao["parar"] if rodando else aquisicao["rodar"])
        return not rodando

    return _com_retentativa(acao)


def estado_aquisicao(recurso, timeout=3000, idn=None):
    """Pergunta ao instrumento se esta adquirindo. None = ele nao sabe dizer.

    Nem todo aparelho responde: no DSO-X 3024T com firmware 04.06.2015 o
    :RSTate? nao existe, e nenhum outro registrador distingue rodando de
    parado. Nesse caso quem chama assume um estado e acompanha os comandos
    que ele proprio manda.
    """
    def consulta():
        with sessao(recurso, timeout) as scope:
            pergunta = _dialeto_de(scope, idn)["aquisicao"]
            if not pergunta["consulta"]:
                return None
            resposta = scope.query(pergunta["consulta"]).strip().upper()
            # O :TRIGger:STATus? do DHO800 responde TD, WAIT, RUN ou AUTO
            # enquanto adquire, e STOP quando parado.
            if resposta in ("1", "+1", "ON", "RUN", "TD", "WAIT", "AUTO"):
                return True
            if resposta in ("0", "+0", "OFF", "STOP"):
                return False
            return None

    try:
        return _com_retentativa(consulta)
    except Exception:
        return None            # sem resposta e um estado valido: desconhecido


def familia(idn):
    """Escolhe o dialeto pelo fabricante e pelo modelo declarados no *IDN?.

    O *IDN? vem como "FABRICANTE,MODELO,SERIE,FIRMWARE". O modelo entra na
    decisao porque um mesmo fabricante pode ter linhas incompativeis: no
    Rigol, o DSA800 captura com :PRIV:SNAP? e o DHO800 com :DISPlay:DATA?.
    """
    campos = [c.strip() for c in idn.split(",")]
    fabricante = campos[0].lower() if campos else ""
    modelo = campos[1].upper() if len(campos) > 1 else ""
    for marcas, padrao, dialeto in REGRAS_DE_DIALETO:
        if not any(m in fabricante for m in marcas):
            continue
        if padrao is None or re.search(padrao, modelo):
            return dialeto
    return DIALETO_PADRAO


def formato_dos_dados(dados):
    """Le a assinatura dos bytes. O que o aparelho mandou manda no nome."""
    if dados[:4] == b"\x89PNG":
        return "PNG"
    if dados[:2] == b"BM":
        return "BMP"
    if dados[:3] == bytes((0xFF, 0xD8, 0xFF)):
        return "JPG"
    return None


def capturar_bytes(recurso, formato="PNG", paleta="COLor", inksaver=False,
                   timeout=20000, idn=None):
    """Le a imagem da tela do instrumento e devolve os bytes brutos.

    O formato pedido e apenas uma preferencia: se o aparelho nao souber
    produzi-lo, vale o primeiro que ele aceita.

    Passe o idn ja confirmado na conexao. Sem ele, esta funcao pergunta de
    novo, e uma resposta fora de sincronia levaria ao dialeto errado.
    """
    def leitura():
        with sessao(recurso, timeout) as scope:
            dialeto = _dialeto_de(scope, idn)
            escolhido = (formato if formato in dialeto["formatos"]
                         else dialeto["formatos"][0])
            if dialeto["inksaver"]:
                # INKSaver ON inverte o fundo para branco (economia de tinta).
                scope.write(f":HARDcopy:INKSaver {'ON' if inksaver else 'OFF'}")
            comando = dialeto["comando"](escolhido, paleta)
            try:
                return scope.query_binary_values(comando, datatype="B",
                                                 container=bytes)
            except ValueError as e:
                # O pyvisa reclama do bloco sem o "#" inicial. A mensagem dele
                # nao diz o que foi pedido, e e justamente isso que importa:
                # bloco ausente costuma significar comando nao entendido.
                raise RespostaInvalida(
                    f"O instrumento nao devolveu imagem para {comando}.\n"
                    f"{e}") from e

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


def ajustar_extensao(arquivo, dados):
    """Faz a extensao combinar com o que o aparelho realmente mandou.

    Pedir PNG a um Rigol devolve BMP: salvar esses bytes num arquivo .png
    daria um arquivo que nenhum visualizador abre.
    """
    real = formato_dos_dados(dados)
    if real is None:
        return arquivo
    certa = EXTENSAO[real]
    raiz, atual = os.path.splitext(arquivo)
    return arquivo if atual.lower() == certa else raiz + certa


def capturar(recurso, arquivo, formato="PNG", paleta="COLor", inksaver=False,
             timeout=20000, idn=None):
    """Captura e salva em disco. Devolve (caminho, tamanho_em_bytes)."""
    dados = capturar_bytes(recurso, formato, paleta, inksaver, timeout, idn)
    return salvar(dados, ajustar_extensao(arquivo, dados)), len(dados)
