# Captura de tela — Keysight DSO-X 3024T

Captura a imagem da tela do osciloscópio via USB (SCPI/pyvisa) e salva em disco.

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `gui_captura.py` | Interface gráfica (Tkinter) |
| `Captura DSOX.bat` | Atalho de duplo clique, abre a interface sem console |
| `captura_dsox3024t.py` | Linha de comando (uso em scripts/automação) |
| `dsox_core.py` | Comunicação SCPI — usado pela interface e pela CLI |
| `teste_interface.py` | Teste da interface sem precisar do osciloscópio |

## Requisitos

- Keysight IO Libraries Suite (fornece o driver VISA)
- `pip install -r requirements.txt`

Tkinter já vem com o Python no Windows — não há dependência extra para a interface.

## Interface gráfica

```bash
python gui_captura.py
```

Ou duplo clique em `Captura DSOX.bat`.

- **Procurar** lista os instrumentos VISA visíveis; **Testar conexão** mostra o `*IDN?`.
- **Pasta** e **Prefixo** definem o destino; o nome recebe data/hora automaticamente
  (`tela_20260826_083547.png`) — a linha "Próximo arquivo" mostra como vai ficar.
- **CAPTURAR** (ou F5) faz a leitura em segundo plano, salva e exibe a prévia.
- **Copiar** joga a última imagem na área de transferência (colar direto no relatório).
- As preferências ficam em `%USERPROFILE%\.captura_dsox.json` e voltam na próxima abertura.

A pasta padrão é `%USERPROFILE%\Capturas_DSOX`, fora de Desktop/Documentos, que costumam
estar protegidos pelo "Acesso controlado a pastas" do Windows Defender.

## Linha de comando

```bash
python captura_dsox3024t.py
```

```bash
python captura_dsox3024t.py medida.png --inksaver --cinza
```

```bash
python captura_dsox3024t.py --listar
```

Opções: `--recurso`, `--formato {PNG,BMP,BMP8bit}`, `--cinza`, `--inksaver`,
`--listar`, `--sem-pausa`.

## Cabo USB retirado e recolocado

O `ResourceManager` do pyvisa é um singleton por processo e a enumeração dos
instrumentos fica presa na sessão VISA. Depois de um replug, a sessão antiga
está inválida e o programa não acha mais o osciloscópio.

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
ou a porta USB traseira (device) do osciloscópio, nada que o software resolva.

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
python teste_nucleo.py
```

```bash
python teste_interface.py
```

Rodam sem osciloscópio: o núcleo com sessões VISA simuladas, a interface
percorrendo os estados de conexão em uma janela real.

## Observações

- A prévia usa o Tk, que só exibe PNG. Em BMP a captura funciona normalmente,
  mas a prévia mostra um aviso.
- `--inksaver` inverte o fundo para branco (economia de tinta na impressão).
