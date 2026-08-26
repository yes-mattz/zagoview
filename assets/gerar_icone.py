"""Gera o icone da janela a partir do 'Z' do wordmark, em vetor.

O favicon oficial do site e um raster de 69x106; usar o mesmo glifo em vetor
da o mesmo desenho, mas nitido em 16 px, que e o tamanho da barra de titulo.
"""
import os
import re
import subprocess
import tkinter as tk

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
AQUI = os.path.dirname(os.path.abspath(__file__))
ORIGEM = os.path.join(AQUI, "logo-zagonel-verde.svg")
DESTINO = AQUI
VERDE_ICONE = "#009a42"        # verde exato do favicon oficial

# Acima de ~64 o Chrome headless impoe uma largura minima de janela e
# centraliza a arte fora do recorte. De 16 a 64 cobre todos os tamanhos que
# o Windows usa para icone de janela.
TAMANHOS = (16, 32, 48, 64)

# Caixa do glifo medida no render ampliado, em unidades do viewBox original.
LARG, ALT = 21.125, 34.0
LADO = ALT / 0.82              # margem para o Z nao encostar na borda
X0 = -(LADO - LARG) / 2
Y0 = -(LADO - ALT) / 2

d = re.findall(r'<path[^>]*?d="([^"]+)"', open(ORIGEM, encoding="utf-8").read())[0]
# width/height em 100%: com tamanho fixo o Chrome renderiza a SVG no tamanho
# intrinseco e ignora a janela, o que recortava o Z nos tamanhos pequenos.
svg = (f'<svg width="100%" height="100%" '
       f'viewBox="{X0:.4f} {Y0:.4f} {LADO:.4f} {LADO:.4f}" '
       f'xmlns="http://www.w3.org/2000/svg">'
       f'<path fill-rule="evenodd" clip-rule="evenodd" d="{d}" '
       f'fill="{VERDE_ICONE}"/></svg>')

os.makedirs(DESTINO, exist_ok=True)
caminho_svg = os.path.join(DESTINO, "icone-z.svg")
with open(caminho_svg, "w", encoding="utf-8") as f:
    f.write(svg)
print("vetor:", caminho_svg)

raiz = tk.Tk()
raiz.withdraw()
for lado in TAMANHOS:
    png = os.path.join(DESTINO, f"icone-z-{lado}.png")
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--default-background-color=00000000",
                    f"--window-size={lado},{lado}",
                    f"--screenshot={png}", "file:///" + caminho_svg.replace("\\", "/")],
                   check=True, capture_output=True)
    img = tk.PhotoImage(file=png)
    opacos = sum(1 for y in range(img.height()) for x in range(img.width())
                 if not img.transparency_get(x, y))
    print(f"  {lado:>3}px -> {img.width()}x{img.height()}, "
          f"{100 * opacos / (img.width() * img.height()):.0f}% de tinta, "
          f"{os.path.getsize(png)} bytes")
raiz.destroy()
