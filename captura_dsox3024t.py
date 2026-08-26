"""
Captura da tela do osciloscopio Keysight DSO-X 3024T via USB (SCPI / pyvisa).

Uso:
    python captura_dsox3024t.py
    python captura_dsox3024t.py minha_medida.png
    python captura_dsox3024t.py medida.png --inksaver     # fundo branco (impressao)
    python captura_dsox3024t.py medida.bmp --formato BMP
    python captura_dsox3024t.py medida.png --cinza        # escala de cinza
    python captura_dsox3024t.py --listar                  # ver instrumentos VISA

Interface grafica: python gui_captura.py

Requisitos: Keysight IO Libraries Suite + pip install pyvisa
"""

import argparse
import sys
import traceback

import pyvisa

import dsox_core


def main():
    # Pasta de saida fora de Desktop/Documentos: essas pastas costumam estar
    # protegidas pelo "Acesso controlado a pastas" do Windows Defender,
    # o que causa PermissionError [Errno 13].
    padrao = dsox_core.nome_automatico()

    p = argparse.ArgumentParser(description="Captura a tela do DSO-X 3024T.")
    p.add_argument("arquivo", nargs="?", default=padrao,
                   help="nome do arquivo de saida (padrao: tela_AAAAMMDD_HHMMSS.png)")
    p.add_argument("--recurso", default=dsox_core.RECURSO_PADRAO,
                   help="string VISA do instrumento")
    p.add_argument("--formato", default="PNG", choices=dsox_core.FORMATOS,
                   help="formato da imagem (padrao: PNG)")
    p.add_argument("--cinza", action="store_true", help="salvar em escala de cinza")
    p.add_argument("--inksaver", action="store_true",
                   help="fundo branco, para impressao")
    p.add_argument("--listar", action="store_true",
                   help="listar os instrumentos VISA encontrados e sair")
    p.add_argument("--sem-pausa", action="store_true",
                   help="nao esperar Enter no final (para uso em scripts)")
    args = p.parse_args()

    if args.listar:
        recursos = dsox_core.listar_recursos()
        print("Instrumentos VISA encontrados:" if recursos
              else "Nenhum instrumento VISA encontrado.")
        for r in recursos:
            print("   ", r)
        sys.exit(0)

    paleta = "GRAYscale" if args.cinza else "COLor"
    codigo = 0

    try:
        print(f"Conectado: {dsox_core.identificar(args.recurso)}")
        destino, tamanho = dsox_core.capturar(
            args.recurso, args.arquivo, args.formato, paleta, args.inksaver)
        print(f"Imagem salva em: {destino}  ({tamanho} bytes)")
    except pyvisa.errors.VisaIOError as e:
        print(f"\nERRO de comunicacao VISA: {e}")
        print("Verifique o cabo USB e se o instrumento aparece no Connection Expert.")
        codigo = 1
    except PermissionError as e:
        print(f"\nERRO: sem permissao para gravar o arquivo: {e.filename}")
        print("A imagem foi lida do osciloscopio, mas o Windows bloqueou a gravacao.")
        print("Causa comum: 'Acesso controlado a pastas' (Windows Defender) protegendo")
        print("Desktop/Documentos, ou um arquivo de mesmo nome aberto em outro programa.")
        print("Solucao: gravar em outra pasta, ex.:")
        print(r"    python captura_dsox3024t.py C:\Capturas\medida.png")
        codigo = 1
    except Exception:
        print("\nERRO inesperado:")
        traceback.print_exc()
        codigo = 1

    # Mantem a janela aberta quando o script e aberto com duplo clique.
    if not args.sem_pausa:
        try:
            input("\nPressione Enter para fechar...")
        except EOFError:
            pass

    sys.exit(codigo)


if __name__ == "__main__":
    main()
