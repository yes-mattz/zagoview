"""Gera o icone do Zagoview a partir do 'Z' do wordmark, em vetor.

O favicon oficial do site e um raster de 69x106; usar o mesmo glifo em vetor
da o mesmo desenho, mas nitido em 16 px, que e o tamanho da barra de titulo.

Produz:
  icone-z.svg          o vetor, fonte de tudo
  icone-z-<n>.png      os tamanhos que a janela do Tk carrega
  zagoview.ico         o icone do executavel, com todos os tamanhos dentro
"""
import os
import re
import struct
import subprocess
import tkinter as tk

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
AQUI = os.path.dirname(os.path.abspath(__file__))
ORIGEM = os.path.join(AQUI, "logo-zagonel-verde.svg")
DESTINO = AQUI
VERDE_ICONE = "#009a42"        # verde exato do favicon oficial

# A janela do Tk carrega estes; o .ico leva estes e mais os grandes, que o
# Explorer usa nos modos de exibicao com icone gigante.
TAMANHOS_JANELA = (16, 32, 48, 64)
TAMANHOS_ICO = (16, 24, 32, 48, 64, 128, 256)

# Caixa do glifo medida no render ampliado, em unidades do viewBox original.
LARG, ALT = 21.125, 34.0
LADO = ALT / 0.82              # margem para o Z nao encostar na borda
X0 = -(LADO - LARG) / 2
Y0 = -(LADO - ALT) / 2

# O Chrome headless tem largura minima de janela: pedir --window-size=256,256
# nao encolhe a janela para 256, e a arte centralizada acaba fora do recorte.
# Por isso todo render sai de uma pagina folgada, com a imagem ancorada no
# canto superior esquerdo, e depois se recorta o quadrado exato.
JANELA = 800


def montar_svg():
    corpo = open(ORIGEM, encoding="utf-8").read()
    d = re.findall(r'<path[^>]*?d="([^"]+)"', corpo)[0]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
            f'height="100%" viewBox="{X0:.4f} {Y0:.4f} {LADO:.4f} {LADO:.4f}">'
            f'<path fill-rule="evenodd" clip-rule="evenodd" d="{d}" '
            f'fill="{VERDE_ICONE}"/></svg>')


def renderizar(caminho_svg, lado, destino):
    """Rasteriza a SVG num quadrado de lado px, com fundo transparente."""
    html = os.path.join(DESTINO, "_render.html")
    with open(html, "w", encoding="utf-8") as f:
        f.write('<!doctype html><style>html,body{margin:0;padding:0;'
                'background:transparent}img{display:block}</style>'
                f'<img src="{os.path.basename(caminho_svg)}" '
                f'width="{lado}" height="{lado}">')
    bruto = os.path.join(DESTINO, "_bruto.png")
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--default-background-color=00000000",
                    f"--window-size={max(lado, JANELA)},{max(lado, JANELA)}",
                    f"--screenshot={bruto}", "file:///" + html.replace("\\", "/")],
                   check=True, capture_output=True)
    recortar(bruto, destino, lado)
    for lixo in (html, bruto):
        os.remove(lixo)


def recortar(origem, destino, lado):
    """Recorta o quadrado do canto superior esquerdo, com o .NET do Windows."""
    ps = ("Add-Type -AssemblyName System.Drawing; "
          f"$b=[System.Drawing.Bitmap]::FromFile('{origem}'); "
          f"$r=New-Object System.Drawing.Rectangle(0,0,{lado},{lado}); "
          "$c=$b.Clone($r, $b.PixelFormat); "
          f"$c.Save('{destino}', [System.Drawing.Imaging.ImageFormat]::Png); "
          "$c.Dispose(); $b.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   check=True, capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def extrair_bgra(caminho_png, lado):
    """Devolve os pixels do PNG como BGRA cru, linha a linha, de cima para baixo."""
    cru = caminho_png + ".raw"
    ps = ("Add-Type -AssemblyName System.Drawing; "
          f"$b=[System.Drawing.Bitmap]::FromFile('{caminho_png}'); "
          "$r=New-Object System.Drawing.Rectangle(0,0,$b.Width,$b.Height); "
          "$d=$b.LockBits($r, "
          "[System.Drawing.Imaging.ImageLockMode]::ReadOnly, "
          "[System.Drawing.Imaging.PixelFormat]::Format32bppArgb); "
          "$n=$d.Stride*$b.Height; $a=New-Object byte[] $n; "
          "[System.Runtime.InteropServices.Marshal]::Copy($d.Scan0,$a,0,$n); "
          "$b.UnlockBits($d); "
          f"[System.IO.File]::WriteAllBytes('{cru}',$a); "
          "$b.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   check=True, capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    with open(cru, "rb") as f:
        dados = f.read()
    os.remove(cru)
    esperado = lado * lado * 4
    if len(dados) != esperado:
        raise RuntimeError(f"{caminho_png}: {len(dados)} bytes, esperava {esperado}")
    return dados


def montar_ico(pngs, destino):
    """Empacota varios tamanhos num unico .ico, com payload DIB.

    O formato tambem aceita PNG embutido desde o Vista, mas nem todo leitor
    entende: o System.Drawing do .NET devolve cor embaralhada, e o icone do
    executavel passa por leitores assim. DIB e o formato que todos leem.
    """
    entradas, dados, deslocamento = [], [], 6 + 16 * len(pngs)
    for lado, caminho in pngs:
        bgra = extrair_bgra(caminho, lado)
        # BITMAPINFOHEADER: a altura vem dobrada porque o formato conta a
        # imagem mais a mascara AND, mesmo quando ela nao e usada.
        cabecalho = struct.pack("<IiiHHIIiiII", 40, lado, lado * 2, 1, 32,
                                0, lado * lado * 4, 0, 0, 0, 0)
        # O DIB e de baixo para cima; o PNG veio de cima para baixo.
        linhas = [bgra[y * lado * 4:(y + 1) * lado * 4]
                  for y in range(lado)][::-1]
        # Mascara AND zerada: com 32 bits por pixel, quem manda e o canal alfa.
        por_linha = ((lado + 31) // 32) * 4
        mascara = b"\x00" * (por_linha * lado)
        bloco = cabecalho + b"".join(linhas) + mascara

        entradas.append(struct.pack("<BBBBHHII",
                                    0 if lado >= 256 else lado,
                                    0 if lado >= 256 else lado,
                                    0, 0, 1, 32, len(bloco), deslocamento))
        dados.append(bloco)
        deslocamento += len(bloco)

    with open(destino, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(pngs)))
        for e in entradas:
            f.write(e)
        for b in dados:
            f.write(b)


def main():
    os.makedirs(DESTINO, exist_ok=True)
    caminho_svg = os.path.join(DESTINO, "icone-z.svg")
    with open(caminho_svg, "w", encoding="utf-8") as f:
        f.write(montar_svg())
    print("vetor:", caminho_svg)

    raiz = tk.Tk()
    raiz.withdraw()
    temporarios, para_ico = [], []
    for lado in sorted(set(TAMANHOS_ICO) | set(TAMANHOS_JANELA)):
        permanente = lado in TAMANHOS_JANELA
        png = os.path.join(DESTINO, f"icone-z-{lado}.png" if permanente
                           else f"_ico-{lado}.png")
        renderizar(caminho_svg, lado, png)
        img = tk.PhotoImage(file=png)
        opacos = sum(1 for y in range(img.height()) for x in range(img.width())
                     if not img.transparency_get(x, y))
        centrado = "-"
        xs = [x for y in range(lado) for x in range(lado)
              if not img.transparency_get(x, y)]
        if xs:
            centrado = "sim" if abs(min(xs) - (lado - 1 - max(xs))) <= 1 else "NAO"
        print(f"  {lado:>3}px -> {img.width()}x{img.height()}, "
              f"{100 * opacos / (lado * lado):.0f}% de tinta, centrado: {centrado}")
        if lado in TAMANHOS_ICO:
            para_ico.append((lado, png))
        if not permanente:
            temporarios.append(png)
    raiz.destroy()

    ico = os.path.join(DESTINO, "zagoview.ico")
    montar_ico(para_ico, ico)
    print(f"icone do executavel: {ico} ({os.path.getsize(ico)} bytes, "
          f"{len(para_ico)} tamanhos)")
    for lixo in temporarios:
        os.remove(lixo)


if __name__ == "__main__":
    main()
