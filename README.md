# Zagoview — Captura de tela de instrumentos

Captura a imagem da tela de um instrumento SCPI via VISA (USB ou rede) e salva
em disco. Serve qualquer aparelho que o VISA enxergue e que atenda ao comando
`:DISPlay:DATA?` — osciloscópios, geradores, analisadores. Foi escrito e testado
contra um Keysight DSO-X 3024T, então os padrões seguem o dialeto da Keysight.

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `gui_captura.py` | Interface gráfica (Tkinter) |
| `Zagoview.bat` | Atalho de duplo clique, abre a interface sem console |
| `cli_captura.py` | Linha de comando (uso em scripts/automação) |
| `instrumento.py` | Comunicação SCPI — usado pela interface e pela CLI |
| `teste_interface.py` | Teste da interface sem precisar do instrumento |
| `assets/` | Logo da marca em SVG (vetor) e PNG (usado pela janela) |

## Identidade visual

O cabeçalho traz a marca em `#128c4f`, o verde de ação da Zagonel (o mesmo do
fundo dos botões no site). O SVG original é branco, para fundo escuro; a versão
verde foi gerada trocando os 9 `fill="white"` e rasterizada com o Edge em modo
headless, já que o Tk não renderiza SVG:

```bash
msedge --headless=new --default-background-color=00000000 --window-size=149,44 --screenshot=assets/logo-zagonel-verde.png assets/logo-zagonel-verde.svg
```

Se o PNG faltar, a janela abre do mesmo jeito, com a marca em texto.

O ícone da janela é o "Z" da marca, o mesmo símbolo do favicon do site. O
favicon oficial é um raster de 69x106 e ficaria distorcido num ícone quadrado,
então o mesmo glifo é extraído em vetor do primeiro `<path>` do wordmark,
centralizado num quadrado e rasterizado em 16/32/48/64 px — o Windows pede 16
para a barra de título e 32/48 para a barra de tarefas e o Alt+Tab. A cor é o
`#009a42` do favicon. Para regerar:

```bash
python assets/gerar_icone.py
```

## Requisitos

- Uma implementação VISA: Keysight IO Libraries, NI-VISA ou a do fabricante
  do seu instrumento (é ela que fornece o driver)
- `pip install -r requirements.txt`

Tkinter já vem com o Python no Windows — não há dependência extra para a interface.

## Interface gráfica

```bash
python gui_captura.py
```

Ou duplo clique em `Zagoview.bat`.

- **Procurar** lista os instrumentos VISA visíveis; **Testar conexão** mostra o `*IDN?`.
- **Pasta** e **Prefixo** definem o destino; o nome recebe data/hora automaticamente
  (`tela_20260826_083547.png`) — a linha "Próximo arquivo" mostra como vai ficar.
- **CAPTURAR** (ou F5) faz a leitura em segundo plano, salva e exibe a prévia.
- **Copiar** joga a última imagem na área de transferência (colar direto no relatório).
- As preferências ficam em `%USERPROFILE%\.zagoview.json` e voltam na próxima abertura.
  O arquivo antigo, `.captura_dsox.json`, ainda é lido se o novo não existir.

A pasta padrão é `%USERPROFILE%\Capturas_DSOX`, fora de Desktop/Documentos, que costumam
estar protegidos pelo "Acesso controlado a pastas" do Windows Defender.

## Linha de comando

```bash
python cli_captura.py
```

```bash
python cli_captura.py medida.png --inksaver --cinza
```

```bash
python cli_captura.py --listar
```

Opções: `--recurso`, `--formato {PNG,BMP,BMP8bit}`, `--cinza`, `--inksaver`,
`--listar`, `--sem-pausa`.

## Cabo USB retirado e recolocado

O `ResourceManager` do pyvisa é um singleton por processo e a enumeração dos
instrumentos fica presa na sessão VISA. Depois de um replug, a sessão antiga
está inválida e o programa não acha mais o instrumento.

O botão **Procurar** descarta a sessão e reenumera — é o "Rescan" do Connection
Expert feito de dentro do programa, sem fechar a janela. As operações também
tentam isso sozinhas, uma vez, quando recebem um erro típico de dispositivo
removido (`RSRC_NFOUND`, `RSRC_BUSY`, `CONN_LOST`, `INV_OBJECT`, `IO`).

Antes de cada operação é feito `viClear` + `*CLS`: se uma captura for abortada
no meio, o resto da imagem fica na fila de saída do instrumento e a leitura
seguinte sairia corrompida.

Se mesmo assim não aparecer, o problema é físico. Confira com:

```bash
powershell "Get-PnpDevice | ? { $_.InstanceId -match 'VID_2A8D' } | fl Present, Status, FriendlyName"
```

`Present: False` significa que o Windows não enumerou o aparelho — cabo, porta
ou a porta USB de dispositivo do instrumento, nada que o software resolva.

## O que conta como "conectado"

A lista do combo mostra só os endereços que **responderam ao `*IDN?`** na
varredura — o VISA pode continuar anunciando um instrumento já desligado. Quem
falha por estar ocupado (`RSRC_BUSY`/`RSRC_LOCKED`) permanece na lista: está
conectado, só não pode atender agora.

A validação abre cada endereço sem `viClear`, de propósito — a varredura passa
por todos os instrumentos do PC e limpar a E/S de um aparelho em uso por outro
programa abortaria a transferência dele.

O botão **CAPTURAR** (e o F5) só ficam ativos enquanto o endereço que está no
campo for o mesmo que respondeu ao `*IDN?`. Editar o endereço, perder a conexão
durante uma captura ou não achar nada na varredura devolve a tela para "não
conectado" e limpa o campo — assim ele nunca mostra um instrumento que não
está mais lá.

## Testes

```bash
python teste_instrumento.py
```

```bash
python teste_interface.py
```

Rodam sem instrumento: o núcleo com sessões VISA simuladas, a interface
percorrendo os estados de conexão em uma janela real.

## Observações

- A prévia usa o Tk, que só exibe PNG. Em BMP a captura funciona normalmente,
  mas a prévia mostra um aviso.
- `--inksaver` inverte o fundo para branco (economia de tinta na impressão).
