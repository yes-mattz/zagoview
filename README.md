# Zagoview

Captura a tela de instrumentos de bancada (osciloscópios, analisadores de
espectro) pela porta USB ou pela rede, e salva a imagem em disco.

O programa identifica o fabricante pelo `*IDN?` e usa o comando que aquele
aparelho entende, sem configuração manual. Também permite iniciar e parar a
aquisição sem encostar no instrumento.

## Requisitos

- **Windows**
- Uma implementação **VISA** compatível com o padrão IVI. Ela fornece o driver
  de comunicação e não acompanha o programa:

  | Implementação | Tamanho |
  |---|---|
  | R&S VISA | 61 MB |
  | Keysight IO Libraries Suite | 462 MB |
  | NI-VISA | ~1 GB |

  Instale **apenas uma**. Duas implementações disputam o mesmo instrumento USB,
  e o aparelho passa a aparecer duplicado na lista.

Se nenhuma estiver instalada, o programa avisa e oferece instalar o R&S VISA,
que acompanha o executável.

Para rodar a partir do código-fonte, é preciso também Python 3 e as
dependências em `requirements.txt`. O Tkinter já vem com o Python no Windows.

## Uso

Execute o `Zagoview.exe`, ou o código-fonte:

```bash
python gui_captura.py
```

1. Ligue o instrumento e conecte o cabo.
2. **Procurar** — lista os instrumentos e confirma qual respondeu.
3. **Destino** — escolha a pasta e o prefixo do arquivo. O nome recebe data e
   hora automaticamente.
4. **CAPTURAR** (ou `F5`) — salva a imagem e mostra a prévia.

O botão ao lado do CAPTURAR alterna a aquisição e indica o estado pela cor:
verde para rodando, vermelho para parado. **Ajuda**, no cabeçalho, resume tudo
isso dentro do programa.

As preferências ficam em `%USERPROFILE%\.zagoview.json`.

### Linha de comando

```bash
python cli_captura.py
```

Sem argumentos, encontra o instrumento e salva com nome automático. Opções:
`--recurso`, `--formato {PNG,BMP,BMP8bit}`, `--cinza`, `--inksaver`,
`--listar`, `--sem-pausa`.

## Instrumentos suportados

| Aparelho | Captura | Aquisição |
|---|---|---|
| Keysight / Agilent | `:DISPlay:DATA? <fmt>,<paleta>` — PNG, BMP, BMP8bit | `:RUN` / `:STOP` |
| Rigol DSA800 (analisadores) | `:PRIV:SNAP? BMP` — BMP | `:INITiate:CONTinuous ON\|OFF` |
| Rigol DHO800/900 (osciloscópios) | `:DISPlay:DATA? <fmt>` — PNG, BMP, JPG | `:RUN` / `:STOP` |

O dialeto é escolhido pelo **fabricante e pelo modelo**, porque um mesmo
fabricante pode ter linhas incompatíveis: no Rigol, o analisador DSA800 e o
osciloscópio DHO800 não capturam com o mesmo comando.

Verificado em um Keysight DSO-X 3024T e em um Rigol DSA832E. O dialeto do
DHO800 vem do manual de programação e ainda não foi testado no aparelho.
Fabricantes não reconhecidos usam o dialeto Keysight, que pode ou não
funcionar — Tektronix, por exemplo, usa outra sequência e não é suportado.

O `*IDN?` é perguntado uma vez, ao conectar, e esse mesmo valor acompanha a
captura e o Run/Stop. Perguntar de novo a cada operação custava uma ida e
volta que, com a sessão fora de sincronia, devolvia a resposta da rodada
anterior — foi assim que um DHO804 foi classificado como Keysight e recebeu
um comando que não entende. Quando a resposta não é reconhecível, nenhum
comando de dialeto é enviado: a operação falha com mensagem clara em vez de
sujar a sessão.

O formato escolhido na janela é uma preferência: quando o aparelho não sabe
produzi-lo, vale o que ele entrega, e a extensão do arquivo é corrigida pela
assinatura dos bytes.

Para acrescentar um aparelho, basta uma entrada em `DIALETOS` e uma regra em
`REGRAS_DE_DIALETO`, em `instrumento.py`. As regras casam por fabricante e por
padrão de modelo, e a primeira que servir vence — as mais específicas primeiro.

## Gerar o executável

```bash
pyinstaller zagoview.spec
```

Sai um `dist/Zagoview.exe` de arquivo único (~48 MB), com a logo, os ícones e o
instalador do VISA embutidos. O instalador deve estar em `visa/` antes de
compilar — ele não está no repositório, por ser binário de terceiro de 61 MB.
Sem ele, o executável sai com ~13 MB e o programa apenas explica o que
instalar, em vez de oferecer.

O executável não é assinado digitalmente. O Windows pode exibir aviso do
SmartScreen, e antivírus baseados em heurística ocasionalmente marcam
executáveis do PyInstaller como suspeitos.

## Solução de problemas

**O instrumento não aparece.** Confirme que o Windows o reconhece:

```bash
powershell "Get-PnpDevice -PresentOnly | ? { $_.Class -eq 'USBTestAndMeasurementDevice' } | fl FriendlyName, Status"
```

Se não aparecer aqui, o problema é físico — cabo, porta ou o próprio aparelho.

**A conexão caiu depois de trocar o cabo.** O botão **Procurar** descarta a
sessão VISA e refaz a varredura, sem precisar fechar o programa.

**Instrumento ligado por cabo serial.** Não é suportado. A varredura ignora
portas COM (`ASRL`) de propósito: o VISA lista todas as portas da máquina,
tenha ou não instrumento atrás, e sondá-las trava — num notebook com Bluetooth
apareceram quatro portas, todas sem resposta.

**Falhou na máquina de outra pessoa.** O script de diagnóstico levanta o que o
Windows e o VISA enxergam naquela máquina e gera um relatório para análise:

```bash
powershell -ExecutionPolicy Bypass -File diagnostico.ps1
```

## Estrutura

| Arquivo | Conteúdo |
|---|---|
| `gui_captura.py` | Interface gráfica |
| `cli_captura.py` | Linha de comando |
| `instrumento.py` | Comunicação SCPI e dialetos por fabricante |
| `teste_instrumento.py` | Testes do núcleo, com sessões simuladas |
| `teste_interface.py` | Testes da interface |
| `zagoview.spec` | Receita do PyInstaller |
| `diagnostico.ps1` | Relatório de diagnóstico |
| `assets/` | Logo e ícones, com o gerador que os produz |

## Testes

```bash
python teste_instrumento.py
```

```bash
python teste_interface.py
```

Rodam sem instrumento conectado: o núcleo com sessões VISA simuladas, a
interface percorrendo os estados da janela.

## Autor

Mateus Von Grafen — mtmateus0@gmail.com
