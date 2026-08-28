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
import glob
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

NOME = "Zagoview"
VERSAO = "1.2.2"
DESCRICAO = "Captura a tela de instrumentos SCPI via VISA"
AUTOR = "Mateus Von Grafen"
EMAIL = "mtmateus0@gmail.com"

AJUDA = """
COMO USAR

1. Ligue o instrumento e conecte o cabo (USB ou rede).
2. Clique em Procurar. O endereco aparece na lista e a linha verde mostra
   o modelo que respondeu.
3. Escolha a pasta e o prefixo do arquivo em Destino.
4. Clique em CAPTURAR (ou tecle F5). A imagem e salva e aparece na previa.

O botao ao lado do CAPTURAR alterna a aquisicao do instrumento: verde
"Rodando", vermelho "Parado" - a mesma convencao da tecla do painel.

SE NAO ENCONTRAR O INSTRUMENTO

E preciso ter uma implementacao VISA instalada (R&S VISA, Keysight IO
Libraries ou NI-VISA). Se nao houver nenhuma, o programa avisa e oferece
instalar. Instale apenas uma: duas disputam o mesmo aparelho.

Se o instrumento nao aparecer mesmo com VISA instalado, o problema
costuma ser o cabo ou a porta - confira se o Windows o reconhece.

ONDE FICAM AS COISAS

As capturas vao para a pasta escolhida em Destino.
As preferencias ficam em %USERPROFILE%\\.zagoview.json.

PARA RELATAR UM PROBLEMA

Copie o texto do quadro Registro da janela principal e envie junto. Ele
diz o que o programa tentou e o que o instrumento respondeu.
"""

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
# Cores do botao Run/Stop, na convencao do painel do instrumento.
VERDE_RUN = "#1e8e3e"
VERMELHO_STOP = "#c5221f"
CINZA_BOTAO = "#e0e0e0"
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


def achar_instalador_visa():
    """Procura o instalador do VISA que acompanha o programa.

    Empacotado, ele vem dentro do executavel (PASTA_APP aponta para a pasta
    de extracao). Rodando como script, fica em visa/ ao lado do codigo. Como
    o nome traz a versao, procura por padrao em vez de nome fixo.
    """
    for pasta in (os.path.join(PASTA_APP, "visa"), PASTA_APP,
                  os.path.dirname(sys.executable)):
        try:
            achados = sorted(glob.glob(os.path.join(pasta, "RS_VISA_Setup*.exe")))
        except OSError:
            continue
        if achados:
            return achados[-1]          # o de versao mais alta
    return None


def texto_do_erro(e):
    """Traduz as falhas mais comuns para uma mensagem util ao operador."""
    if isinstance(e, instrumento.RespostaInvalida):
        return (f"{e}\n\n"
                "Costuma ser sessao fora de sincronia ou comando que este "
                "modelo nao entende. Clique em Procurar para refazer a "
                "conexao; se repetir, envie o Registro para o suporte.")
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
        self.rodando = None        # None ate saber o estado do instrumento
        self.idn = None            # o *IDN? confirmado na conexao

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
        # tk.Button classico, e nao ttk: o tema do Windows ignora cor de fundo
        # em botao ttk, e a cor e justamente o que este botao comunica.
        self.bt_run = tk.Button(g, text="Rodando", width=11, relief="raised",
                                font=("Segoe UI", 9, "bold"),
                                state="disabled", command=self.alternar_run)
        self.bt_run.grid(row=0, column=1, padx=(8, 0), sticky="ns")
        self.bt_abrir_img = ttk.Button(g, text="Abrir imagem", width=14,
                                       state="disabled", command=self.abrir_imagem)
        self.bt_abrir_img.grid(row=0, column=2, padx=(8, 0))
        self.bt_copiar = ttk.Button(g, text="Copiar", width=10,
                                    state="disabled", command=self.copiar)
        self.bt_copiar.grid(row=0, column=3, padx=(8, 0))
        self.bt_abrir_pasta = ttk.Button(g, text="Abrir pasta", width=12,
                                         command=self.abrir_pasta)
        self.bt_abrir_pasta.grid(row=0, column=4, padx=(8, 0))
        self._pintar_run()

        self.barra = ttk.Progressbar(self, mode="indeterminate")
        self.barra.grid(row=4, column=0, sticky="ew", pady=(8, 0))

        # --- Previa -----------------------------------------------------
        g = ttk.LabelFrame(self, text="Previa", padding=6)
        g.grid(row=5, column=0, sticky="nsew", pady=(10, 0))
        self.rowconfigure(5, weight=1)
        g.columnconfigure(0, weight=1)
        g.rowconfigure(0, weight=1)
        # A imagem vai num canvas so para poder ser rolada. O canvas pede
        # exatamente o tamanho da imagem, como o rotulo pedia antes, para a
        # janela continuar com a mesma geometria; a barra so entra em acao
        # quando a janela encolhe e sobra menos espaco que a imagem.
        fundo = ttk.Style().lookup("TFrame", "background") or "#f0f0f0"
        self.cv_previa = tk.Canvas(g, highlightthickness=0, borderwidth=0,
                                   background=fundo)
        self.cv_previa.grid(row=0, column=0, sticky="nsew")
        self.rol_previa = ttk.Scrollbar(g, orient="vertical",
                                        command=self.cv_previa.yview)
        self.rol_previa.grid(row=0, column=1, sticky="ns")
        self.cv_previa.configure(yscrollcommand=self._ajustar_barra)
        self.cv_previa.bind(
            "<MouseWheel>",
            lambda e: self.cv_previa.yview_scroll(-e.delta // 120, "units"))
        self.cv_previa.bind("<Configure>", lambda _e: self._centralizar_aviso())
        self._desenhar_previa(None)

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
        self._pintar_run()
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
        # Guardado para as operacoes seguintes: perguntar o *IDN? de novo a
        # cada captura e uma ida e volta a mais que, se voltar fora de
        # sincronia, escolhe o dialeto errado.
        self.idn = idn
        self.lb_idn.configure(text=idn, foreground="green")
        self._atualizar_estado_captura()
        recurso = self.var_recurso.get().strip()
        idn = self.idn
        self._executar(lambda: instrumento.estado_aquisicao(recurso, idn=idn),
                       "estado",
                       "Lendo o estado da aquisicao...")

    def _marcar_desconectado(self, texto="Nao conectado.", vermelho=False):
        self.conectado = False
        self.rodando = None
        self.idn = None
        self._pintar_run()
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
            if isinstance(dados, instrumento.VisaAusente):
                # Sem VISA nao ha o que procurar, e mandar conferir o cabo
                # seria enganoso: o que falta e a biblioteca, nao o aparelho.
                self._marcar_desconectado("VISA nao instalado.", vermelho=True)
                self.var_status.set("Nenhuma implementacao VISA encontrada.")
                self.log("VISA ausente: " + str(dados).splitlines()[0])
                self._oferecer_visa()
                return
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

    # ------------------------------------------------- aquisicao (Run/Stop)
    def _pintar_run(self):
        """Verde rodando, vermelho parado - a mesma convencao do painel do
        instrumento, onde a tecla Run/Stop acende nessas duas cores."""
        if getattr(self, "bt_run", None) is None:
            return                     # ainda montando a janela
        if not self.conectado or self.rodando is None:
            self.bt_run.configure(text="Run/Stop", bg=CINZA_BOTAO,
                                  fg="black", activebackground=CINZA_BOTAO,
                                  state="disabled")
            return
        if self.rodando:
            cor, texto = VERDE_RUN, "Rodando"
        else:
            cor, texto = VERMELHO_STOP, "Parado"
        self.bt_run.configure(text=texto, bg=cor, fg="white",
                              activebackground=cor, activeforeground="white",
                              state="disabled" if self.ocupado else "normal")

    def alternar_run(self):
        if self.ocupado or not self.conectado or self.rodando is None:
            return
        recurso = self.var_recurso.get().strip()
        rodando = self.rodando
        idn = self.idn
        self._executar(lambda: instrumento.run_stop(recurso, rodando, idn=idn),
                       "run",
                       "Parando a aquisicao..." if rodando
                       else "Retomando a aquisicao...")

    def _fim_run(self, ok, dados):
        if not ok:
            self.log("Falha ao alternar a aquisicao. " + texto_do_erro(dados))
            self.var_status.set("Nao foi possivel alternar a aquisicao.")
            self._pintar_run()
            return
        self.rodando = dados
        self.var_status.set("Aquisicao em andamento." if dados
                            else "Aquisicao parada.")
        self.log(":RUN" if dados else ":STOP")
        self._pintar_run()

    def _fim_estado(self, ok, dados):
        """Estado lido do instrumento ao conectar.

        Ha aparelho que nao sabe responder - o DSO-X 3024T deste firmware e um
        deles. Nesse caso assume-se rodando, que e como um instrumento fica
        quando ninguem mexeu nele, e o botao passa a acompanhar os comandos
        que ele proprio manda.
        """
        self.rodando = dados if ok and dados is not None else True
        if not (ok and dados is not None):
            self.log("O instrumento nao informa o estado da aquisicao; "
                     "assumindo que esta rodando.")
        self._pintar_run()

    def _oferecer_visa(self):
        """Pergunta se o operador quer instalar o VISA que veio junto.

        O programa fala com o despachante neutro da IVI Foundation, entao
        qualquer implementacao serve; o R&S acompanha o pacote por ser a
        menor. Quem ja tiver Keysight IO Libraries ou NI-VISA nao ve isto.
        """
        instalador = achar_instalador_visa()
        if instalador is None:
            messagebox.showerror(
                "VISA nao instalado",
                "Nenhuma implementacao VISA foi encontrada nesta maquina, e o\n"
                "instalador nao veio junto do programa.\n\n"
                "Instale uma destas e abra o programa de novo:\n"
                "  - R&S VISA (a menor)\n"
                "  - Keysight IO Libraries Suite\n"
                "  - NI-VISA")
            return

        tamanho = os.path.getsize(instalador) / (1024 * 1024)
        if not messagebox.askyesno(
                "VISA nao instalado",
                "Para falar com o instrumento e preciso uma implementacao VISA,\n"
                "e nenhuma foi encontrada nesta maquina.\n\n"
                f"Instalar o R&S VISA agora? ({tamanho:.0f} MB, incluso no "
                "programa)\n\n"
                "A instalacao pede permissao de administrador. Ao terminar,\n"
                "clique em Procurar de novo."):
            self.log("Instalacao do VISA recusada pelo operador.")
            return

        try:
            abrir_no_windows(instalador)
            self.var_status.set("Instalador do VISA aberto. Ao terminar, "
                                "clique em Procurar.")
            self.log(f"Instalador aberto: {instalador}")
        except OSError as e:
            self.log(f"Nao foi possivel abrir o instalador: {e}")
            messagebox.showerror(
                "Instalador",
                f"Nao foi possivel abrir o instalador:\n{instalador}\n\n{e}")

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
            lambda: instrumento.capturar(recurso, destino, formato, paleta,
                                         inksaver, idn=self.idn),
            "captura", "Executando...")

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
            self._desenhar_previa(img)
        except Exception as e:
            self.imagem_tk = None
            self._desenhar_previa(None, "(nao foi possivel exibir a previa)")
            self.log(f"Previa indisponivel: {e}")

    def _desenhar_previa(self, imagem, aviso="(nenhuma captura ainda)"):
        """Poe a imagem no canvas e define o que da para rolar.

        O canvas passa a pedir o tamanho da imagem, que e o que o rotulo pedia
        antes: assim a janela mantem a mesma altura natural, e a rolagem so
        existe quando o espaco disponivel fica menor que a imagem.
        """
        self.cv_previa.delete("all")
        if imagem is None:
            # Sem imagem o canvas pede so uma linha de texto. O tamanho padrao
            # dele e bem maior e esticaria a janela sem nada para mostrar.
            self.cv_previa.configure(scrollregion=(0, 0, 0, 0),
                                     width=1, height=20)
            self.cv_previa.create_text(0, 0, text=aviso, fill="gray",
                                       tags="aviso")
            self._centralizar_aviso()
            return
        largura, altura = imagem.width(), imagem.height()
        self.cv_previa.create_image(0, 0, anchor="n", image=imagem,
                                    tags="previa")
        self.cv_previa.configure(width=largura, height=altura)
        self._centralizar_previa()
        self.cv_previa.yview_moveto(0)

    def _ajustar_barra(self, primeiro, ultimo):
        """Mostra a barra so quando ha o que rolar.

        Uma barra vertical tem altura minima propria, maior que a do canvas
        vazio: deixa-la sempre visivel esticaria a janela em 32 px so para
        exibir uma barra inutil.
        """
        self.rol_previa.set(primeiro, ultimo)
        if float(primeiro) <= 0.0 and float(ultimo) >= 1.0:
            self.rol_previa.grid_remove()
        else:
            self.rol_previa.grid()

    def _centralizar_aviso(self):
        if self.cv_previa.find_withtag("aviso"):
            self.cv_previa.coords("aviso",
                                  self.cv_previa.winfo_width() / 2,
                                  self.cv_previa.winfo_height() / 2)
        self._centralizar_previa()

    def _centralizar_previa(self):
        """Mantem a imagem no meio quando sobra largura.

        A area rolavel acompanha: sem isso, centralizar a imagem deixaria
        metade dela fora do alcance da rolagem.
        """
        if self.imagem_tk is None or not self.cv_previa.find_withtag("previa"):
            return
        largura = max(self.cv_previa.winfo_width(), self.imagem_tk.width())
        self.cv_previa.coords("previa", largura / 2, 0)
        self.cv_previa.configure(
            scrollregion=(0, 0, largura, self.imagem_tk.height()))

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

    tk.Button(faixa, text="Ajuda", width=8, relief="groove", bg="white",
               font=("Segoe UI", 9), command=lambda: mostrar_ajuda(raiz)
               ).grid(row=0, column=2, rowspan=2, sticky="e")

    tk.Frame(raiz, bg=VERDE, height=3).grid(row=0, column=0, sticky="sew")
    return imagem


def mostrar_ajuda(pai):
    """Janela de ajuda, com o essencial de uso, a autoria e o contato.

    Usa um Text em vez de messagebox para o e-mail poder ser selecionado e
    copiado - numa caixa de mensagem o texto nao se copia em pedacos.
    """
    janela = tk.Toplevel(pai)
    janela.title(f"Ajuda - {NOME} {VERSAO}")
    janela.transient(pai)
    janela.resizable(False, False)
    with contextlib.suppress(tk.TclError):
        janela.iconphoto(False, *[tk.PhotoImage(file=c) for c in ICONES[:2]])

    quadro = ttk.Frame(janela, padding=14)
    quadro.grid(sticky="nsew")

    ttk.Label(quadro, text=f"{NOME} {VERSAO}",
              font=("Segoe UI", 12, "bold")).grid(row=0, column=0,
                                                  columnspan=2, sticky="w")
    ttk.Label(quadro, text=DESCRICAO, foreground=CINZA_TEXTO).grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

    # Com rolagem: o texto cresce quando alguem editar a ajuda, e a caixa
    # continua do mesmo tamanho em vez de cortar o fim sem avisar.
    texto = tk.Text(quadro, width=64, height=20, wrap="word", relief="flat",
                    background=janela.cget("bg"), font=("Segoe UI", 9))
    texto.grid(row=2, column=0, sticky="nsew")
    rolagem = ttk.Scrollbar(quadro, orient="vertical", command=texto.yview)
    rolagem.grid(row=2, column=1, sticky="ns")
    texto.configure(yscrollcommand=rolagem.set)
    texto.insert("1.0", AJUDA.strip())
    texto.configure(state="disabled")      # so leitura, mas ainda selecionavel
    texto.bind("<MouseWheel>",
               lambda e: texto.yview_scroll(-e.delta // 120, "units"))

    linha = ttk.Frame(quadro)
    linha.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
    linha.columnconfigure(0, weight=1)
    ttk.Label(linha, text=f"{AUTOR}  <{EMAIL}>",
              foreground=CINZA_TEXTO).grid(row=0, column=0, sticky="w")

    def copiar_email():
        janela.clipboard_clear()
        janela.clipboard_append(EMAIL)
        bt_copiar.configure(text="Copiado!")
        janela.after(1500, lambda: bt_copiar.configure(text="Copiar e-mail"))

    bt_copiar = ttk.Button(linha, text="Copiar e-mail", width=15,
                           command=copiar_email)
    bt_copiar.grid(row=0, column=1, padx=(8, 0))
    ttk.Button(linha, text="Fechar", width=10,
               command=janela.destroy).grid(row=0, column=2, padx=(8, 0))

    janela.bind("<Escape>", lambda _e: janela.destroy())
    janela.update_idletasks()
    # centraliza sobre a janela principal
    x = pai.winfo_rootx() + (pai.winfo_width() - janela.winfo_reqwidth()) // 2
    y = pai.winfo_rooty() + (pai.winfo_height() - janela.winfo_reqheight()) // 3
    janela.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    janela.grab_set()
    return janela


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
    raiz.title(f"{NOME} {VERSAO}")
    raiz.minsize(700, 760)
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    # O conteudo vive num corpo de largura natural, centralizado na janela:
    # maximizar passa a sobrar margem dos dois lados em vez de esticar os
    # botoes e os campos ate a largura da tela. O "ns" preserva o
    # comportamento vertical - a previa continua absorvendo o que sobra.
    corpo = ttk.Frame(raiz)
    corpo.grid(row=0, column=0, sticky="ns")
    raiz.columnconfigure(0, weight=1)
    raiz.rowconfigure(0, weight=1)

    raiz.logo = montar_cabecalho(corpo)
    raiz.icones = definir_icone(raiz)
    app = Aplicacao(corpo)
    raiz.protocol("WM_DELETE_WINDOW", app.ao_fechar)
    raiz.mainloop()


if __name__ == "__main__":
    main()
