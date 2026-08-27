"""Teste da interface sem precisar do osciloscopio.

Cobre a previa da imagem, o tratamento de erro e a maquina de estados da
conexao: a tela so pode dizer "conectado" sobre um endereco que respondeu
ao *IDN?.
"""
import os
import struct
import time
import tkinter as tk
import zlib

import pyvisa
from pyvisa import constants

import gui_captura as G

# evita caixas de dialogo modais no teste automatico
G.messagebox.showerror = lambda *a, **k: print("DIALOGO ERRO:", a[0])
G.messagebox.showwarning = lambda *a, **k: None


def _sem_instrumento(*_a, **_k):
    raise pyvisa.errors.VisaIOError(
        int(constants.StatusCode.error_resource_not_found))


# O resultado nao pode mudar conforme o osciloscopio esteja ligado ou nao:
# o teste simula a ausencia de hardware e injeta as respostas ele mesmo.
G.instrumento.listar_recursos = lambda *a, **k: []
G.instrumento.identificar = _sem_instrumento
# Conectar dispara a leitura do estado da aquisicao; sem simular, o teste
# sairia falando com o instrumento de verdade.
G.instrumento.estado_aquisicao = lambda *a, **k: None

# O teste comeca sempre dos padroes: lendo o ~/.zagoview.json de quem roda,
# o resultado mudaria conforme as preferencias da pessoa - foi o que
# aconteceu quando "copiar" estava desligado nesta maquina. E nao gravar
# nada, para nao mexer nas preferencias de ninguem.
G.carregar_config = lambda: {}
G.salvar_config = lambda dados: None


def gerar_png(path, w=1280, h=768):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw += bytes(((x + y) % 256, (x * 2) % 256, 90))

    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c))

    hdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", hdr)
                + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b""))


def checar(descricao, obtido, esperado):
    ok = obtido == esperado
    print(("  ok  " if ok else "FALHOU") + f"  {descricao}: {obtido!r}")
    assert ok, f"{descricao}: esperado {esperado!r}, obtido {obtido!r}"


destino = os.path.join(os.environ["TEMP"], "teste_previa.png")
gerar_png(destino)

def bombear(limite=15.0):
    """Roda o loop do Tk ate a operacao em andamento terminar.

    update() so despacha os callbacks de after() que ja venceram; sem isso a
    varredura inicial ficaria eternamente marcada como em andamento.
    """
    fim = time.time() + limite
    while time.time() < fim:
        raiz.update()
        if not app.ocupado:
            return
        time.sleep(0.05)
    raise AssertionError("operacao nao terminou em %.0fs" % limite)


def esperar_ate(condicao, limite=5.0):
    fim = time.time() + limite
    while time.time() < fim:
        raiz.update()
        if condicao():
            return True
        time.sleep(0.02)
    return False


raiz = tk.Tk()
app = G.Aplicacao(raiz)
# A varredura inicial e agendada com after(300): esperar so por "ocupado"
# sairia antes de ela comecar, e o resultado dela cairia no meio de um teste
# posterior, zerando o estado da conexao. Espera comecar, depois terminar.
esperar_ate(lambda: app.ocupado)
bombear()

print("\n[1] varredura sem nenhum instrumento presente")
app._fim_procura(True, [])
raiz.update()
checar("endereco VISA sem dispositivo", app.var_recurso.get(), G.SEM_DISPOSITIVO)
checar("rotulo", app.lb_idn["text"], "Nenhum instrumento conectado.")
checar("lista do combo", app.cb_recurso["values"], "")
checar("CAPTURAR desabilitado", str(app.bt_capturar["state"]), "disabled")

print("\n[2] F5 nao captura sem instrumento")
app.capturar()
raiz.update()
checar("status", app.var_status.get(),
       "Nenhum instrumento conectado. Clique em Procurar.")

print("\n[3] instrumento encontrado, mas ainda sem responder ao *IDN?")
app._fim_procura(True, ["USB0::0x2A8D::0x1766::MY55280502::0::INSTR"])
raiz.update()
checar("endereco preenchido", app.var_recurso.get(),
       "USB0::0x2A8D::0x1766::MY55280502::0::INSTR")
checar("ainda nao confirmado", app.conectado, False)
checar("CAPTURAR ainda desabilitado", str(app.bt_capturar["state"]), "disabled")
# a varredura dispara o *IDN? sozinha; aqui ele falha (sem instrumento) e
# nao pode abrir caixa de dialogo, porque ninguem clicou em nada
bombear()
checar("estar na lista nao basta", app.lb_idn["text"], "Nao responde ao *IDN?.")
checar("sem confirmar", app.conectado, False)

print("\n[4] *IDN? respondeu")
app._fim_teste(True, "KEYSIGHT TECHNOLOGIES,DSO-X 3024T,MY55280502,07.30")
bombear()          # conectar dispara a leitura do estado da aquisicao
checar("conectado", app.conectado, True)
checar("rotulo verde", str(app.lb_idn["foreground"]), "green")
checar("CAPTURAR liberado", str(app.bt_capturar["state"]), "normal")

print("\n[5] captura com sucesso")
copias = []
G.copiar_imagem = lambda caminho: copias.append(caminho)
app._fim_captura(True, (destino, 123456))
raiz.update()
checar("previa 1280x768 reduzida", (app.imagem_tk.width(), app.imagem_tk.height()),
       (427, 256))
checar("botao abrir imagem", str(app.bt_abrir_img["state"]), "normal")
checar("copia automatica habilitada", copias, [destino])

app.var_copiar.set(False)
app._fim_captura(True, (destino, 123456))
raiz.update()
checar("copia automatica desabilitada", copias, [destino])

print("\n[6] cabo arrancado no meio da captura")
app._fim_captura(False, PermissionError(13, "negado", destino))
raiz.update()
checar("marcado como desconectado", app.conectado, False)
checar("rotulo", app.lb_idn["text"], "Conexao perdida durante a captura.")
checar("CAPTURAR bloqueado de novo", str(app.bt_capturar["state"]), "disabled")

print("\n[7] editar o endereco na mao invalida a conexao")
app._marcar_conectado("KEYSIGHT,DSO-X 3024T,MY55280502,07.30")
app.var_recurso.set("TCPIP0::192.168.0.10::inst0::INSTR")
raiz.update()
checar("volta para nao verificado", app.lb_idn["text"], "Nao verificado.")
checar("CAPTURAR bloqueado", str(app.bt_capturar["state"]), "disabled")

print("\n[9] o botao Run/Stop mostra o estado pela cor")
app._marcar_conectado("KEYSIGHT TECHNOLOGIES,DSO-X 3024T,MY5528,07.30")
bombear()          # conectar dispara a leitura do estado; deixa terminar

# Estado desconhecido: verificado pintando direto, e nao no intervalo entre
# conectar e a resposta chegar - esse intervalo e uma corrida, e a asserção
# passava ou falhava conforme a velocidade da maquina.
app.rodando = None
app._pintar_run()
raiz.update()
checar("desconhecido: cinza e travado", (app.bt_run["text"],
       str(app.bt_run["state"])), ("Run/Stop", "disabled"))

# instrumento que nao sabe informar o estado: assume-se rodando
app._fim_estado(True, None)
raiz.update()
checar("assume rodando", app.rodando, True)
checar("verde", (app.bt_run["text"], app.bt_run["bg"]), ("Rodando", G.VERDE_RUN))

app._fim_run(True, False)
raiz.update()
checar("apos parar, vermelho", (app.bt_run["text"], app.bt_run["bg"]),
       ("Parado", G.VERMELHO_STOP))

app._fim_run(True, True)
raiz.update()
checar("apos rodar, verde de novo", (app.bt_run["text"], app.bt_run["bg"]),
       ("Rodando", G.VERDE_RUN))

# instrumento que sabe informar
app._fim_estado(True, False)
raiz.update()
checar("estado lido do aparelho", (app.bt_run["text"], app.bt_run["bg"]),
       ("Parado", G.VERMELHO_STOP))

print("\n[10] perder a conexao apaga o botao")
app._marcar_desconectado("Dispositivo desconectado.", vermelho=True)
raiz.update()
checar("volta a cinza", (app.bt_run["text"], str(app.bt_run["state"])),
       ("Run/Stop", "disabled"))
checar("estado esquecido", app.rodando, None)

print("\n[11] a barra da previa aparece so quando ha o que rolar")
app._mostrar_previa(destino)
raiz.update()
# A largura da area rolavel acompanha o canvas, porque a imagem fica
# centralizada; o que precisa casar com a imagem e a altura.
_, _, rol_larg, rol_alt = [int(float(v))
                           for v in app.cv_previa["scrollregion"].split()]
checar("area rolavel cobre a altura da imagem", rol_alt, 256)
checar("e nao e mais estreita que a imagem", rol_larg >= 427, True)
checar("imagem centralizada na largura",
       app.cv_previa.coords("previa")[0], rol_larg / 2)
checar("o canvas pede o tamanho da imagem, como o rotulo pedia",
       (app.cv_previa.winfo_reqwidth(), app.cv_previa.winfo_reqheight()),
       (427, 256))

# Encolher o canvas de verdade, em vez de chamar o callback na mao: o
# proprio Tk dispara o yscrollcommand com os valores reais, e e esse caminho
# que interessa. grid_info() vazio = fora do layout; winfo_ismapped nao
# serve, porque depende de a janela estar visivel.
raiz.geometry("700x760")
for _ in range(20):
    raiz.update()
    time.sleep(0.02)
checar("cortando, com barra", bool(app.rol_previa.grid_info()), True)
visivel = app.cv_previa.yview()
checar("so parte da imagem a vista", visivel[1] < 1.0, True)

# Devolver espaco a janela, e nao ao canvas: pedir mais altura de nada
# adianta se a janela nao tem o que dar.
raiz.geometry("700x1100")
for _ in range(20):
    raiz.update()
    time.sleep(0.02)
checar("com espaco de sobra, sem barra", bool(app.rol_previa.grid_info()), False)
checar("imagem inteira a vista", app.cv_previa.yview(), (0.0, 1.0))

raiz.destroy()
print("\nTODOS OS TESTES PASSARAM")
