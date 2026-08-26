"""
Interface grafica do Zagoview: captura a tela de instrumentos SCPI.

Uso:
    python gui_captura.py
    (ou duplo clique em "Zagoview.bat")

Requisitos: uma implementacao VISA (Keysight IO Libraries, NI-VISA ou a do
fabricante do seu instrumento) + pip install pyvisa
Toda a comunicacao com o instrumento fica em instrumento.py.
"""

import contextlib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import traceback
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import pyvisa

import instrumento

ARQUIVO_CONFIG = os.path.join(os.path.expanduser("~"), ".zagoview.json")
# Nome antigo, de quando o programa era so do DSO-X: lido uma vez para nao
# perder as preferencias de quem ja usava.
CONFIG_ANTIGO = os.path.join(os.path.expanduser("~"), ".captura_dsox.json")
PREVIA_LARGURA = 560
PREVIA_ALTURA = 340
SEM_DISPOSITIVO = "Nenhum dispositivo selecionado."

# Empacotado com PyInstaller em arquivo unico, o programa roda a partir de uma
# pasta temporaria de extracao, e __file__ nao aponta mais para os arquivos de
# apoio: eles ficam onde o _MEIPASS indica.
PASTA_APP = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
LOGO = os.path.join(PASTA_APP, "assets", "logo-zagonel-verde.png")
# O "Z" da marca, o mesmo simbolo do favicon do site. Varios tamanhos porque
# o Windows pede um para a barra de titulo (16) e outro para a barra de
# tarefas e o Alt+Tab (32/48).
ICONES = [os.path.join(PASTA_APP, "assets", f"icone-z-{n}.png")
          for n in (16, 32, 48, 64)]
VERDE = "#128c4f"          # verde de acao da marca Zagonel
CINZA_TEXTO = "#5a5a5a"


def carregar_config():
    for caminho in (ARQUIVO_CONFIG, CONFIG_ANTIGO):
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return {}


def salvar_config(dados):
    try:
        with open(ARQUIVO_CONFIG, "w", encoding="utf-8") as f:
            json.dump(dados, f, indent=2)
    except OSError:
        pass


def abrir_no_windows(caminho):
    """Abre um arquivo ou pasta com o programa padrao do sistema."""
    if sys.platform == "win32":
        os.startfile(caminho)
    else:
        subprocess.Popen(["xdg-open", caminho])


def copiar_imagem(caminho):
    """Copia a imagem para a area de transferencia usando o .NET do Windows."""
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
        "$i=[System.Drawing.Image]::FromFile('" + caminho + "'); "
        "[System.Windows.Forms.Clipboard]::SetImage($i); $i.Dispose()"
    )
    subprocess.run(
        ["powershell", "-STA", "-NoProfile", "-Command", ps],
        check=True, capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def converter_para_png(origem):
    """Converte uma imagem para PNG num arquivo temporario, e devolve o caminho.

    O Tk so exibe PNG e GIF, e ha instrumento que so entrega BMP (o Rigol
    DSA832E, por exemplo). Sem isto a captura salva certo mas fica sem previa.
    """
    destino = os.path.join(tempfile.gettempdir(), "zagoview_previa.png")
    ps = (
        "Add-Type -AssemblyName System.Drawing; "
        "$i=[System.Drawing.Image]::FromFile('" + origem + "'); "
        "$i.Save('" + destino + "', "
        "[System.Drawing.Imaging.ImageFormat]::Png); $i.Dispose()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        check=True, capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return destino


def texto_do_erro(e):
    """Traduz as falhas mais comuns para uma mensagem util ao operador."""
    if isinstance(e, pyvisa.errors.VisaIOError):
        return ("Falha de comunicacao VISA:\n"
                f"{e}\n\n"
                "Verifique o cabo, se o instrumento esta ligado e se ele aparece "
                "no seu utilitario VISA (Keysight Connection Expert, NI MAX ou "
                "equivalente do fabricante).")
    if isinstance(e, PermissionError):
        return (f"Sem permissao para gravar em:\n{e.filename}\n\n"
                "Causa comum: 'Acesso controlado a pastas' do Windows Defender "
                "protegendo Desktop/Documentos, ou o arquivo aberto em outro "
                "programa. Escolha outra pasta de destino.")
    return f"{type(e).__name__}: {e}"


class Aplicacao(ttk.Frame):
    def __init__(self, mestre):
        super().__init__(mestre, padding=12)
        self.grid(row=1, column=0, sticky="nsew")
        mestre.columnconfigure(0, weight=1)
        mestre.rowconfigure(1, weight=1)

        cfg = carregar_config()
        self.fila = queue.Queue()
        self.ocupado = False
        self.conectado = False
        self.ultimo_arquivo = None
        self.imagem_tk = None

        self.var_recurso = tk.StringVar(
            value=cfg.get("recurso", instrumento.RECURSO_PADRAO))
        self.var_pasta = tk.StringVar(value=cfg.get("pasta", instrumento.PASTA_PADRAO))
        self.var_prefixo = tk.StringVar(value=cfg.get("prefixo", "tela"))
        self.var_formato = tk.StringVar(value=cfg.get("formato", "PNG"))
        self.var_cinza = tk.BooleanVar(value=cfg.get("cinza", False))
        self.var_inksaver = tk.BooleanVar(value=cfg.get("inksaver", False))
        self.var_abrir_apos = tk.BooleanVar(value=cfg.get("abrir_apos", False))
        self.var_copiar = tk.BooleanVar(value=cfg.get("copiar", True))
        self.var_status = tk.StringVar(value="Pronto.")

        self._montar()
        self.after(100, self._processar_fila)
        # No inicio a sessao VISA e nova: nao ha o que reenumerar.
        self.after(300, lambda: self.procurar_instrumentos(False))

    # ------------------------------------------------------------------ UI
    def _montar(self):
        self.columnconfigure(0, weight=1)

        # --- Instrumento ------------------------------------------------
        g = ttk.LabelFrame(self, text="Instrumento", padding=10)
        g.grid(row=0, column=0, sticky="ew")
        g.columnconfigure(1, weight=1)

        ttk.Label(g, text="Endereco VISA:").grid(row=0, column=0, sticky="w",
                                                 padx=(0, 8))
        self.cb_recurso = ttk.Combobox(g, textvariable=self.var_recurso)
        self.cb_recurso.grid(row=0, column=1, sticky="ew")
        self.bt_procurar = ttk.Button(g, text="Procurar", width=12,
                                      command=self.procurar_instrumentos)
        self.bt_procurar.grid(row=0, column=2, padx=(8, 0))
        self.bt_testar = ttk.Button(g, text="Testar conexao", width=16,
                                    command=lambda: self.testar_conexao(True))
        self.bt_testar.grid(row=0, column=3, padx=(8, 0))

        self.lb_idn = ttk.Label(g, text="Nao conectado.", foreground="gray")
        self.lb_idn.grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))

        # Trocar de endereco invalida a conexao atual: o que esta na tela
        # so pode dizer "conectado" sobre o endereco que respondeu ao *IDN?.
        self.cb_recurso.bind("<<ComboboxSelected>>",
                             lambda _e: self.testar_conexao())
        self.var_recurso.trace_add(
            "write", lambda *_: self._marcar_desconectado("Nao verificado."))

        # --- Destino ----------------------------------------------------
        g = ttk.LabelFrame(self, text="Destino", padding=10)
        g.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        g.columnconfigure(1, weight=1)

        ttk.Label(g, text="Pasta:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(g, textvariable=self.var_pasta).grid(row=0, column=1, sticky="ew")
        ttk.Button(g, text="Escolher...", width=12,
                   command=self.escolher_pasta).grid(row=0, column=2, padx=(8, 0))

        ttk.Label(g, text="Prefixo:").grid(row=1, column=0, sticky="w",
                                           padx=(0, 8), pady=(8, 0))
        ttk.Entry(g, textvariable=self.var_prefixo, width=20).grid(
            row=1, column=1, sticky="w", pady=(8, 0))
        self.lb_exemplo = ttk.Label(g, text="", foreground="gray")
        self.lb_exemplo.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))

        for var in (self.var_prefixo, self.var_formato, self.var_pasta):
            var.trace_add("write", lambda *_: self._atualizar_exemplo())

        # --- Opcoes de imagem -------------------------------------------
        g = ttk.LabelFrame(self, text="Imagem", padding=10)
        g.grid(row=2, column=0, sticky="ew", pady=(10, 0))

        ttk.Label(g, text="Formato:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Combobox(g, textvariable=self.var_formato, values=instrumento.FORMATOS,
                     state="readonly", width=10).grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(g, text="Escala de cinza", variable=self.var_cinza).grid(
            row=0, column=2, sticky="w", padx=(20, 0))
        ttk.Checkbutton(g, text="Fundo branco (INKSaver)",
                        variable=self.var_inksaver).grid(row=0, column=3,
                                                         sticky="w", padx=(20, 0))
        ttk.Checkbutton(g, text="Abrir a imagem apos capturar",
                        variable=self.var_abrir_apos).grid(row=1, column=0,
                                                           columnspan=4,
                                                           sticky="w", pady=(8, 0))
        ttk.Checkbutton(g, text="Copiar imagem para a area de transferencia",
                variable=self.var_copiar).grid(row=2, column=0,
                                   columnspan=4,
                                   sticky="w", pady=(8, 0))

        # --- Acao -------------------------------------------------------
        g = ttk.Frame(self)
        g.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        g.columnconfigure(0, weight=1)

        self.bt_capturar = ttk.Button(g, text="CAPTURAR  (F5)", command=self.capturar)
        self.bt_capturar.grid(row=0, column=0, sticky="ew", ipady=8)
        self.bt_abrir_img = ttk.Button(g, text="Abrir imagem", width=14,
                                       state="disabled", command=self.abrir_imagem)
        self.bt_abrir_img.grid(row=0, column=1, padx=(8, 0))
        self.bt_copiar = ttk.Button(g, text="Copiar", width=10,
                                    state="disabled", command=self.copiar)
        self.bt_copiar.grid(row=0, column=2, padx=(8, 0))
        self.bt_abrir_pasta = ttk.Button(g, text="Abrir pasta", width=12,
                                         command=self.abrir_pasta)
        self.bt_abrir_pasta.grid(row=0, column=3, padx=(8, 0))

        self.barra = ttk.Progressbar(self, mode="indeterminate")
        self.barra.grid(row=4, column=0, sticky="ew", pady=(8, 0))

        # --- Previa -----------------------------------------------------
        g = ttk.LabelFrame(self, text="Previa", padding=6)
        g.grid(row=5, column=0, sticky="nsew", pady=(10, 0))
        self.rowconfigure(5, weight=1)
        g.columnconfigure(0, weight=1)
        g.rowconfigure(0, weight=1)
        self.lb_previa = ttk.Label(g, text="(nenhuma captura ainda)",
                                   anchor="center", foreground="gray")
        self.lb_previa.grid(row=0, column=0, sticky="nsew")

        # --- Registro ---------------------------------------------------
        g = ttk.LabelFrame(self, text="Registro", padding=6)
        g.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        g.columnconfigure(0, weight=1)
        self.txt_log = tk.Text(g, height=6, wrap="word", state="disabled")
        self.txt_log.grid(row=0, column=0, sticky="ew")
        rolagem = ttk.Scrollbar(g, orient="vertical", command=self.txt_log.yview)
        rolagem.grid(row=0, column=1, sticky="ns")
        self.txt_log.configure(yscrollcommand=rolagem.set)

        ttk.Label(self, textvariable=self.var_status, relief="sunken",
                  anchor="w", padding=4).grid(row=7, column=0, sticky="ew",
                                              pady=(10, 0))

        self.winfo_toplevel().bind("<F5>", lambda _e: self.capturar())
        self._atualizar_exemplo()

    def _atualizar_exemplo(self):
        exemplo = instrumento.nome_automatico(self.var_pasta.get(),
                                            self.var_prefixo.get() or "tela",
                                            self.var_formato.get())
        self.lb_exemplo.configure(text="Proximo arquivo:  " + exemplo)

    def log(self, texto):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", f"[{datetime.now():%H:%M:%S}] {texto}\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _travar(self, ocupado, status=""):
        self.ocupado = ocupado
        estado = "disabled" if ocupado else "normal"
        for b in (self.bt_testar, self.bt_procurar):
            b.configure(state=estado)
        self._atualizar_estado_captura()
        if ocupado:
            self.barra.start(12)
        else:
            self.barra.stop()
        if status:
            self.var_status.set(status)

    # ------------------------------------------------------- conexao
    def _atualizar_estado_captura(self):
        """So deixa capturar quando o endereco atual respondeu ao *IDN?."""
        bt = getattr(self, "bt_capturar", None)
        if bt is not None:
            bt.configure(state="normal"
                         if self.conectado and not self.ocupado else "disabled")

    def _marcar_conectado(self, idn):
        self.conectado = True
        self.lb_idn.configure(text=idn, foreground="green")
        self._atualizar_estado_captura()

    def _marcar_desconectado(self, texto="Nao conectado.", vermelho=False):
        self.conectado = False
        self.lb_idn.configure(text=texto, foreground="red" if vermelho else "gray")
        self._atualizar_estado_captura()

    # -------------------------------------------------------- threading
    def _executar(self, funcao, tag, status):
        """Roda funcao em segundo plano para nao congelar a janela."""
        if self.ocupado:
            return
        self._travar(True, status)

        def alvo():
            try:
                self.fila.put((tag, True, funcao()))
            except Exception as e:
                traceback.print_exc()
                self.fila.put((tag, False, e))

        threading.Thread(target=alvo, daemon=True).start()

    def _processar_fila(self):
        try:
            while True:
                tag, ok, dados = self.fila.get_nowait()
                self._travar(False)
                getattr(self, f"_fim_{tag}")(ok, dados)
        except queue.Empty:
            pass
        self.after(100, self._processar_fila)

    # ----------------------------------------------------------- acoes
    def procurar_instrumentos(self, reenumerar=True):
        """Varre os instrumentos VISA.

        Com reenumerar=True a sessao VISA e descartada antes da varredura,
        como o 'Rescan' do Connection Expert. E o que recupera o programa
        depois que o cabo USB e retirado e recolocado, sem fechar a janela.
        """
        self._executar(lambda: instrumento.listar_recursos(reenumerar), "procura",
                       "Reconectando ao VISA..." if reenumerar
                       else "Procurando instrumentos VISA...")

    def _fim_procura(self, ok, dados):
        if not ok:
            self.cb_recurso["values"] = []
            self._marcar_desconectado("Falha ao consultar o VISA.", vermelho=True)
            self.var_status.set("Nao foi possivel listar os instrumentos.")
            self.log("Falha ao listar instrumentos VISA. " + texto_do_erro(dados))
            return

        self.cb_recurso["values"] = dados
        if not dados:
            # A mensagem informa claramente que ainda nao ha instrumento selecionado.
            self.var_recurso.set(SEM_DISPOSITIVO)
            self._marcar_desconectado("Nenhum instrumento conectado.", vermelho=True)
            self.var_status.set("Nenhum instrumento VISA encontrado.")
            self.log("Nenhum instrumento VISA encontrado. Verifique o cabo USB.")
            return

        self.var_status.set(f"{len(dados)} instrumento(s) encontrado(s).")
        self.log("Instrumentos: " + ", ".join(dados))
        if self.var_recurso.get() not in dados:
            self.var_recurso.set(dados[0])
        # Estar na lista do VISA nao garante que responde: confirma com *IDN?.
        self.testar_conexao()

    def testar_conexao(self, avisar=False):
        recurso = self.var_recurso.get().strip()
        if not recurso or recurso == SEM_DISPOSITIVO:
            self._marcar_desconectado("Nenhum instrumento conectado.", vermelho=True)
            return
        self._avisar_falha_teste = avisar
        self._executar(lambda: instrumento.identificar(recurso), "teste",
                       "Consultando *IDN?...")

    def _fim_teste(self, ok, dados):
        if ok:
            self._marcar_conectado(dados)
            self.var_status.set("Conectado.")
            self.log("Conectado: " + dados)
            return
        self._marcar_desconectado("Nao responde ao *IDN?.", vermelho=True)
        self.var_status.set("Falha na conexao.")
        self.log(texto_do_erro(dados))
        if getattr(self, "_avisar_falha_teste", False):
            messagebox.showerror("Falha na conexao", texto_do_erro(dados))

    def escolher_pasta(self):
        pasta = filedialog.askdirectory(title="Pasta de destino",
                                        initialdir=self.var_pasta.get())
        if pasta:
            self.var_pasta.set(os.path.normpath(pasta))

    def capturar(self):
        if self.ocupado:
            return
        if not self.conectado:
            self.var_status.set("Nenhum instrumento conectado. Clique em Procurar.")
            return
        recurso = self.var_recurso.get().strip()
        formato = self.var_formato.get()
        paleta = "GRAYscale" if self.var_cinza.get() else "COLor"
        inksaver = self.var_inksaver.get()
        destino = instrumento.nome_automatico(self.var_pasta.get(),
                                            self.var_prefixo.get() or "tela",
                                            formato)
        self._executar(
            lambda: instrumento.capturar(recurso, destino, formato, paleta, inksaver),
            "captura", "Capturando a tela do osciloscopio...")

    def _fim_captura(self, ok, dados):
        if not ok:
            self._marcar_desconectado("Conexao perdida durante a captura.",
                                      vermelho=True)
            self.var_status.set("Falha na captura.")
            self.log(texto_do_erro(dados))
            messagebox.showerror("Falha na captura", texto_do_erro(dados))
            return
        caminho, tamanho = dados
        self.ultimo_arquivo = caminho
        self.bt_abrir_img.configure(state="normal")
        self.bt_copiar.configure(state="normal")
        self.var_status.set("Salvo: " + caminho)
        self.log(f"Imagem salva ({tamanho / 1024:.0f} KB): {caminho}")
        entregue = os.path.splitext(caminho)[1].lstrip(".").upper()
        pedido = self.var_formato.get()
        if entregue and entregue not in pedido.upper():
            # Nem todo instrumento sabe entregar o formato escolhido; quem
            # manda e o aparelho, e o nome do arquivo segue o que veio.
            self.log(f"O instrumento so entrega {entregue}; o formato {pedido} "
                     f"nao se aplica a ele.")
        self._mostrar_previa(caminho)
        self._atualizar_exemplo()
        if self.var_copiar.get():
            self.copiar()
        if self.var_abrir_apos.get():
            self.abrir_imagem()

    def _mostrar_previa(self, caminho):
        try:
            img = self._carregar_previa(caminho)
            fator = max(1,
                        -(-img.width() // PREVIA_LARGURA),
                        -(-img.height() // PREVIA_ALTURA))
            if fator > 1:
                img = img.subsample(fator)
            self.imagem_tk = img
            self.lb_previa.configure(image=img, text="")
        except Exception as e:
            self.imagem_tk = None
            self.lb_previa.configure(image="",
                                     text="(nao foi possivel exibir a previa)")
            self.log(f"Previa indisponivel: {e}")

    def _carregar_previa(self, caminho):
        try:
            return tk.PhotoImage(file=caminho)
        except tk.TclError:
            # Tk nao le BMP: converte uma copia so para mostrar na tela. O
            # arquivo salvo continua sendo o que o instrumento mandou.
            return tk.PhotoImage(file=converter_para_png(caminho))

    def abrir_imagem(self):
        if self.ultimo_arquivo and os.path.exists(self.ultimo_arquivo):
            abrir_no_windows(self.ultimo_arquivo)

    def abrir_pasta(self):
        pasta = self.var_pasta.get()
        try:
            os.makedirs(pasta, exist_ok=True)
            abrir_no_windows(pasta)
        except OSError as e:
            messagebox.showerror("Erro", f"Nao foi possivel abrir a pasta:\n{e}")

    def copiar(self):
        if not self.ultimo_arquivo:
            return
        try:
            copiar_imagem(self.ultimo_arquivo)
            self.var_status.set("Imagem copiada para a area de transferencia.")
            self.log("Imagem copiada para a area de transferencia.")
        except Exception as e:
            self.log(f"Falha ao copiar: {e}")
            messagebox.showwarning("Copiar", "Nao foi possivel copiar a imagem.")

    # ---------------------------------------------------------- fechar
    def ao_fechar(self):
        salvar_config({
            "recurso": self.var_recurso.get(),
            "pasta": self.var_pasta.get(),
            "prefixo": self.var_prefixo.get(),
            "formato": self.var_formato.get(),
            "cinza": self.var_cinza.get(),
            "inksaver": self.var_inksaver.get(),
            "abrir_apos": self.var_abrir_apos.get(),
            "copiar": self.var_copiar.get(),
        })
        self.winfo_toplevel().destroy()


def montar_cabecalho(raiz):
    """Faixa superior com a marca. Devolve a imagem, que precisa continuar
    referenciada: o Tk descarta o PhotoImage recolhido pelo coletor."""
    faixa = tk.Frame(raiz, bg="white", padx=16, pady=10)
    faixa.grid(row=0, column=0, sticky="ew")
    faixa.columnconfigure(1, weight=1)

    imagem = None
    try:
        imagem = tk.PhotoImage(file=LOGO)
        tk.Label(faixa, image=imagem, bg="white").grid(row=0, column=0,
                                                       rowspan=2, sticky="w")
    except tk.TclError:
        # Sem o PNG a janela abre do mesmo jeito, so que com a marca em texto.
        tk.Label(faixa, text="ZAGONEL", bg="white", fg=VERDE,
                 font=("Segoe UI", 16, "bold")).grid(row=0, column=0,
                                                     rowspan=2, sticky="w")

    tk.Label(faixa, text="Zagoview", bg="white", fg=VERDE,
             font=("Segoe UI", 13, "bold")).grid(row=0, column=1, sticky="sw",
                                                 padx=(14, 0))
    tk.Label(faixa, text="Captura de tela", bg="white",
             fg=CINZA_TEXTO, font=("Segoe UI", 9)).grid(row=1, column=1,
                                                        sticky="nw", padx=(14, 0))

    tk.Frame(raiz, bg=VERDE, height=3).grid(row=0, column=0, sticky="sew")
    return imagem


def definir_icone(raiz):
    """Poe o "Z" da marca na barra de titulo e na barra de tarefas.

    Devolve a lista de imagens, que precisa continuar referenciada enquanto a
    janela existir. Sem os arquivos, a janela abre com o icone padrao do Tk.
    """
    imagens = []
    for caminho in ICONES:
        try:
            imagens.append(tk.PhotoImage(file=caminho))
        except tk.TclError:
            pass
    if imagens:
        with contextlib.suppress(tk.TclError):
            raiz.iconphoto(True, *imagens)
    return imagens


def main():
    raiz = tk.Tk()
    raiz.title("Zagoview")
    raiz.minsize(700, 760)
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    raiz.logo = montar_cabecalho(raiz)
    raiz.icones = definir_icone(raiz)
    app = Aplicacao(raiz)
    raiz.protocol("WM_DELETE_WINDOW", app.ao_fechar)
    raiz.mainloop()


if __name__ == "__main__":
    main()
