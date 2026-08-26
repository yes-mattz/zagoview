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


raiz = tk.Tk()
app = G.Aplicacao(raiz)
bombear()                # deixa a busca VISA inicial terminar

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
raiz.update()
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

raiz.destroy()
print("\nTODOS OS TESTES PASSARAM")
