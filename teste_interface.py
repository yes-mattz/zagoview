"""Teste rapido da interface (nao precisa do osciloscopio)."""
import os
import struct
import time
import tkinter as tk
import zlib

import gui_captura as G

# evita caixas de dialogo modais no teste automatico
G.messagebox.showerror = lambda *a, **k: print('DIALOGO ERRO:', a[0])
G.messagebox.showwarning = lambda *a, **k: None


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


destino = os.path.join(os.environ["TEMP"], "teste_previa.png")
gerar_png(destino)

raiz = tk.Tk()
app = G.Aplicacao(raiz)
raiz.update()
time.sleep(1.5)          # deixa a busca VISA falhar em segundo plano
raiz.update()

app._fim_captura(True, (destino, 123456))
raiz.update()
print("previa:", app.imagem_tk.width(), "x", app.imagem_tk.height())
print("botoes:", app.bt_abrir_img["state"], app.bt_copiar["state"])
print("proximo:", app.lb_exemplo["text"])
print("status:", app.var_status.get())

app._fim_captura(False, PermissionError(13, "negado", destino))
raiz.update()
print("erro tratado ->", app.var_status.get())
print("log:\n" + app.txt_log.get("1.0", "end").strip())
raiz.destroy()
print("SMOKE OK")
