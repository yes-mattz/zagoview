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

## Observações

- A prévia usa o Tk, que só exibe PNG. Em BMP a captura funciona normalmente,
  mas a prévia mostra um aviso.
- `--inksaver` inverte o fundo para branco (economia de tinta na impressão).
