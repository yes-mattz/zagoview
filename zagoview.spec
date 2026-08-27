# Receita do executavel. Gera um arquivo unico:
#     pyinstaller zagoview.spec
#
# O programa fala com o despachante visa32.dll da IVI Foundation, que roteia
# para a implementacao instalada - Keysight, NI, R&S, tanto faz. Nenhuma delas
# vai embutida como biblioteca.
#
# O que vai junto e o INSTALADOR do R&S VISA, para a maquina que nao tem
# nenhuma: a janela oferece instala-lo quando a varredura descobre que falta
# VISA. Coloque o RS_VISA_Setup_*.exe em visa/ antes de compilar; sem ele o
# executavel sai menor e a janela apenas explica o que instalar.
import glob

instalador_visa = [(p, "visa") for p in glob.glob("visa/RS_VISA_Setup*.exe")]
print("instalador do VISA embutido:", instalador_visa or "nenhum")

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
           ("assets/icone-z-64.png", "assets")] + instalador_visa,
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
