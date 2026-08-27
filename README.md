# Zagoview — Captura de tela de instrumentos

Captura a imagem da tela de um instrumento SCPI via VISA (USB ou rede) e salva
em disco — osciloscópios, geradores, analisadores. Reconhece o fabricante pelo
`*IDN?` e usa o comando que ele entende; veja **Instrumentos e dialetos**.
Verificado contra um Keysight DSO-X 3024T e um Rigol DSA832E.

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `gui_captura.py` | Interface gráfica (Tkinter) |
| `Zagoview.bat` | Atalho de duplo clique, abre a interface sem console |
| `cli_captura.py` | Linha de comando (uso em scripts/automação) |
| `instrumento.py` | Comunicação SCPI — usado pela interface e pela CLI |
| `teste_interface.py` | Teste da interface sem precisar do instrumento |
| `assets/` | Logo e ícones: SVG (vetor), PNG (janela) e `.ico` (executável) |
| `zagoview.spec` | Receita do PyInstaller para gerar o executável |

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
centralizado num quadrado e rasterizado nos tamanhos que o Windows pede: 16 px
para a barra de título, 32/48 para a barra de tarefas e o Alt+Tab. A cor é o
`#009a42` do favicon.

O mesmo gerador monta o `zagoview.ico` do executável, com sete tamanhos de 16 a
256 px. O payload é DIB, e não PNG embutido: o formato aceita os dois desde o
Vista, mas nem todo leitor entende PNG — o `System.Drawing` do .NET devolve cor
embaralhada, e o ícone de um `.exe` passa por leitores assim. Para regerar:

```bash
python assets/gerar_icone.py
```

## Executável

Para distribuir a quem não tem Python instalado:

```bash
pyinstaller zagoview.spec
```

Antes de compilar, coloque o instalador do R&S VISA em `visa/` — ele **não
está no repositório**, por ser binário de terceiro de 61 MB:

```
visa/RS_VISA_Setup_Win_7_2_6.exe
```

Sai um `dist/Zagoview.exe` de ~48 MB, arquivo único, com a logo, os ícones e o
instalador do VISA dentro. Sem o instalador em `visa/`, o executável sai com
~13 MB e a janela apenas explica o que instalar, em vez de oferecer.

Medido: a janela abre em **0,7–0,9 s**, apesar da descompactação.

**A biblioteca VISA não vai dentro** — só o instalador dela. O programa fala
com o despachante `visa32.dll` da IVI Foundation, que roteia para a
implementação instalada na máquina. Nenhuma implementação é embutida, e
nenhuma é exigida em particular.

Por ser arquivo único, cada abertura descompacta o conteúdo numa pasta
temporária. Por isso o código procura os arquivos de apoio em `sys._MEIPASS`
quando existe, e ao lado do `.py` quando roda como script.

## Requisitos

- Uma implementação VISA qualquer, compatível com o padrão IVI:
  **R&S VISA** (61 MB, a menor), Keysight IO Libraries (462 MB), NI-VISA ou a
  do fabricante do seu instrumento — é ela que fornece o driver.
  Instale **apenas uma**: duas implementações disputam o mesmo instrumento USB
  e o mesmo aparelho passa a aparecer duas vezes na lista, com nomes
  diferentes (`...::SERIE::INSTR` e `...::SERIE::0::INSTR`).
- Se nenhuma estiver instalada, a janela detecta e oferece instalar o R&S VISA
  que acompanha o executável.
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

Antes de cada operação a fila de saída é esvaziada: se uma captura for abortada
no meio, o resto da imagem fica lá e a leitura seguinte sairia corrompida. Isso
é feito lendo até esvaziar (200 ms por leitura, no máximo 20), e **não** com
`viClear` — o viClear não respeita o timeout da sessão e, com um Rigol DSA832E
recém-conectado, ficou 120,02 s bloqueado antes de falhar.

Se mesmo assim não aparecer, o problema é físico. Confira com:

```bash
powershell "Get-PnpDevice | ? { $_.InstanceId -match 'VID_2A8D' } | fl Present, Status, FriendlyName"
```

`Present: False` significa que o Windows não enumerou o aparelho — cabo, porta
ou a porta USB de dispositivo do instrumento, nada que o software resolva.

## Instrumentos e dialetos

Cada fabricante entrega a imagem da tela de um jeito. O núcleo lê o fabricante
no `*IDN?` e escolhe o comando; o que não for reconhecido cai no dialeto
Keysight.

| Fabricante | Comando | Formatos | Observação |
|---|---|---|---|
| Keysight / Agilent | `:DISPlay:DATA? <formato>,<paleta>` | PNG, BMP, BMP8bit | aceita INKSaver e escala de cinza |
| Rigol | `:PRIV:SNAP? BMP` | BMP | ~1,1 MB, ~4,4 s por captura |

O formato escolhido na janela é uma **preferência**: se o aparelho não souber
produzi-lo, vale o que ele entrega, e a extensão do arquivo é corrigida pela
assinatura dos bytes — pedir PNG a um Rigol salva `.bmp`, não um `.png` que
nenhum visualizador abriria. O registro avisa quando isso acontece.

O comando do Rigol **não está no manual de programação da série DSA800**. Lá só
existe `:MMEMory:STORe:SCReen`, que grava num pendrive espetado no aparelho e
não manda nada pelo cabo; não há `:MMEM:DATA?` para ler o arquivo de volta, e
`:DISPlay:DATA` não aparece nas 251 páginas. O `:PRIV:SNAP?` vem do
[lxi-tools](https://github.com/lxi-tools/lxi-tools/blob/master/src/plugins/screenshot_rigol-dsa.c)
e foi verificado contra um DSA832E.

Para adicionar outro fabricante, basta uma entrada em `DIALETOS` e outra em
`FABRICANTES`, em `instrumento.py`.

## O que conta como "conectado"

A lista do combo mostra só os endereços que **responderam ao `*IDN?`** na
varredura — o VISA pode continuar anunciando um instrumento já desligado. Quem
falha por estar ocupado (`RSRC_BUSY`/`RSRC_LOCKED`) permanece na lista: está
conectado, só não pode atender agora.

A validação abre cada endereço sem esvaziar fila nenhuma, de propósito — a
varredura passa por todos os instrumentos do PC, e mexer na E/S de um aparelho
que outro programa está usando abortaria a transferência dele.

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

- A prévia usa o Tk, que só exibe PNG. Em BMP a interface converte uma cópia
  para exibir; o arquivo salvo continua sendo o que o instrumento mandou.
- `--inksaver` inverte o fundo para branco (economia de tinta na impressão).
