"""
Captura da tela de um instrumento SCPI via VISA (linha de comando).

Sem --recurso, encontra sozinho o unico instrumento conectado.

Uso:
    python cli_captura.py
    python cli_captura.py minha_medida.png
    python cli_captura.py medida.png --inksaver     # fundo branco (impressao)
    python cli_captura.py medida.bmp --formato BMP
    python cli_captura.py medida.png --cinza        # escala de cinza
    python cli_captura.py --listar                  # ver instrumentos VISA

Interface grafica: python gui_captura.py

Requisitos: uma implementacao VISA (Keysight IO Libraries, NI-VISA ou a do
fabricante do seu instrumento) + pip install pyvisa
"""

import argparse
import sys
import traceback

import pyvisa

import instrumento


def escolher_instrumento():
    """Acha o instrumento sozinho quando --recurso nao foi informado.

    Com mais de um conectado nao ha como adivinhar qual, entao lista os
    enderecos e pede que o operador escolha.
    """
    achados = instrumento.listar_recursos()
    if not achados:
        raise RuntimeError("nenhum instrumento VISA encontrado. Verifique o cabo "
                           "e se o aparelho esta ligado.")
    if len(achados) > 1:
        raise RuntimeError("mais de um instrumento encontrado; escolha um com "
                           "--recurso:\n    " + "\n    ".join(achados))
    return achados[0]


def main():
    # Pasta de saida fora de Desktop/Documentos: essas pastas costumam estar
    # protegidas pelo "Acesso controlado a pastas" do Windows Defender,
    # o que causa PermissionError [Errno 13].
    padrao = instrumento.nome_automatico()

    p = argparse.ArgumentParser(
        description="Captura a tela de um instrumento SCPI via VISA.")
    p.add_argument("arquivo", nargs="?", default=padrao,
                   help="nome do arquivo de saida (padrao: tela_AAAAMMDD_HHMMSS.png)")
    p.add_argument("--recurso", default=instrumento.RECURSO_PADRAO,
                   help="string VISA do instrumento (padrao: o unico encontrado)")
    p.add_argument("--formato", default="PNG", choices=instrumento.FORMATOS,
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
        recursos = instrumento.listar_recursos()
        print("Instrumentos VISA encontrados:" if recursos
              else "Nenhum instrumento VISA encontrado.")
        for r in recursos:
            print("   ", r)
        sys.exit(0)

    paleta = "GRAYscale" if args.cinza else "COLor"
    codigo = 0

    try:
        recurso = args.recurso or escolher_instrumento()
        print(f"Conectado: {instrumento.identificar(recurso)}")
        destino, tamanho = instrumento.capturar(
            recurso, args.arquivo, args.formato, paleta, args.inksaver)
        print(f"Imagem salva em: {destino}  ({tamanho} bytes)")
    except RuntimeError as e:
        print(f"\nERRO: {e}")
        codigo = 1
    except pyvisa.errors.VisaIOError as e:
        print(f"\nERRO de comunicacao VISA: {e}")
        print("Verifique o cabo, se o instrumento esta ligado e se ele aparece")
        print("no utilitario VISA do fabricante.")
        codigo = 1
    except PermissionError as e:
        print(f"\nERRO: sem permissao para gravar o arquivo: {e.filename}")
        print("A imagem foi lida do osciloscopio, mas o Windows bloqueou a gravacao.")
        print("Causa comum: 'Acesso controlado a pastas' (Windows Defender) protegendo")
        print("Desktop/Documentos, ou um arquivo de mesmo nome aberto em outro programa.")
        print("Solucao: gravar em outra pasta, ex.:")
        print(r"    python cli_captura.py C:\Capturas\medida.png")
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
