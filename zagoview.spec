# Receita do executavel. Gera um arquivo unico:
#     pyinstaller zagoview.spec
#
# O VISA nao vai dentro: o programa fala com o visa32.dll que a implementacao
# do fabricante (Keysight IO Libraries, NI-VISA) instala no Windows. O
# executavel dispensa Python e pyvisa na maquina de destino, nao o VISA.

a = Analysis(
    ["gui_captura.py"],
    pathex=[],
    binaries=[],
    # A logo e os icones viajam dentro do executavel e sao extraidos para a
    # pasta temporaria que o sys._MEIPASS aponta.
    datas=[("assets/logo-zagonel-verde.png", "assets"),
           ("assets/icone-z-16.png", "assets"),
           ("assets/icone-z-32.png", "assets"),
           ("assets/icone-z-48.png", "assets"),
           ("assets/icone-z-64.png", "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Modulos grandes que o programa nao usa; ficam de fora para o executavel
    # nao inchar sem motivo.
    excludes=["numpy", "matplotlib", "PIL", "pytest", "unittest", "pydoc"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Zagoview",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX comprime mais, mas e o que mais dispara antivirus
    runtime_tmpdir=None,
    console=False,          # aplicacao de janela: sem console atras
    icon="assets/zagoview.ico",
)
