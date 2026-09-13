# Take físico de 60 segundos — 12/09/2026

> Historical recording report. These measurements describe the offline learned
> flight controller and geometric navigator. They do not validate browser
> seeking or flight; current work follows the [delivery plan](embodied-roadmap.md).

[Abrir vídeo](https://github.com/bitdeep/fly-netsphere/releases/download/v0.1.0/city_final_60s-fly_city.mp4) ·
[Validação automática](https://github.com/bitdeep/fly-netsphere/releases/download/v0.1.0/city_final_60s-validation.json) ·
[Métricas da física](https://github.com/bitdeep/fly-netsphere/releases/download/v0.1.0/city_final_60s-metrics.json) ·
[Comparação dos desvios](https://github.com/bitdeep/fly-netsphere/releases/download/v0.1.0/city_final_60s-avoidance.json)

O take foi integrado continuamente em MuJoCo Warp na RTX 4090, dentro do Docker.
A policy oficial de voo, portada para CUDA, controla os atuadores e o batimento
das asas. O mundo brutalista é geometria 3D do próprio modelo físico.
Não há reposicionamento do corpo durante a integração, reinício de episódio
ou composição da mosca sobre imagem de fundo.

| Medida | Resultado |
|---|---:|
| Tempo físico e duração decodificada do vídeo | 60,000 s |
| Vídeo | 1280×720, 30 fps, 1.800 quadros |
| Passos físicos / controles | 1.200.000 / 300.000 |
| Contatos com o mundo / reinícios | 0 / 0 |
| Flags de limite do solver | 0 |
| Distância percorrida | 12,0065 m |
| Altitude observada | 3,91–7,23 cm |
| Maior erro de acompanhamento observado | 0,380 mm |
| Menor margem conservadora em torno da anatomia | 8,36 mm |
| Estados físicos usados nas exposições | 14.400 |
| Menor área visível da mosca na checagem dos quadros | 2.890 pixels |
| Tempo de cálculo da física, após inicialização | 942,66 s |

A posição, altitude e distância às superfícies são medidas a 100 Hz. O contador
de contatos observa cada subpasso físico na GPU. A margem conservadora subtrai
da menor distância do corpo ao cenário o maior raio que envolve todas as geometrias
da mosca, calculado nas 14.400 poses de exposição. Os hashes dos estados e do
modelo compilado foram conferidos antes da aceitação.

O registro hardware.csv identifica a
RTX 4090 durante a execução. O minuto simulado levou aproximadamente 15,7 minutos
de cálculo; esta execução não é em tempo real. Navegação geométrica e leitura
inicial do checkpoint usam CPU. Física, MLP, WPG e render EGL usam GPU;
a codificação H.264 usa CPU.

## Desvio que responde aos obstáculos

Foram comparadas execuções com a mesma pose inicial e seed:

- Com desvio ativo: o take de 60 s terminou sem contato.
- Movendo somente o primeiro pilar em −3 cm: a trajetória física mudou até
  3,955 cm nos primeiros 1,2 s, também sem contato ou flags do solver.
- Desligando o desvio: a mosca atingiu o pilar e a execução foi rejeitada em
  0,77 s. O contador acumulou 655 contatos; isso conta subpassos, não 655
  obstáculos. Houve limite de iterações após o impacto, portanto a dinâmica
  posterior à colisão não é um resultado aceito.

O navegador consulta a geometria conhecida a 100 Hz e escolhe curvas e subidas
para explorar quatro regiões do distrito. Ele não vê por uma rede visual
treinada e não representa o cérebro/connectome. Os testes sustentam voo estável
e desvio neste cenário e nas perturbações descritas; não demonstram equivalência
com todo o comportamento espontâneo de uma mosca viva.

Também passaram os testes de voo contínuo em curva na CPU e GPU, a comparação
numérica da inferência CUDA com a referência NumPy e a execução completa curta
por `docker compose` usando a imagem reconstruída com o lock de dependências.

## Gravação e inspeção

O renderer carrega o `model.mjb` salvo e as poses físicas de `states.npz`.
Cada quadro combina oito poses efetivamente integradas, com exposição de
1/120 s. O relógio do vídeo acompanha o físico; não há alongamento de um
episódio curto para preencher um minuto.

A visibilidade foi medida nos 1.800 quadros com a mesma geometria e câmera.
Esse buffer de identificação usa antialiasing desligado, pois a mistura de
cores nas bordas corrompe códigos de objetos. A imagem do vídeo preserva o
antialiasing original. A falha foi reproduzida no quadro 11 e corrigida no
renderer, sem alterar os estados físicos ou substituir pixels do vídeo.

Foram inspecionados os quadros inicial, intermediários e final, uma
[folha de contato](https://github.com/bitdeep/fly-netsphere/releases/download/v0.1.0/city_final_60s-contact_sheet.png) cobrindo o minuto e
o [quadro de menor visibilidade](https://github.com/bitdeep/fly-netsphere/releases/download/v0.1.0/city_final_60s-frame_least_visible.png).
O FFprobe decodificou todos os 1.800 quadros.

SHA-256 do vídeo:
`5c04e45f0269ed05f179838f5509431942f3e76847b3c9fa0c87ab35ba28dd29`

## Reproduzir

```bash
docker compose build fly
docker compose run --rm fly bash scripts/simulate_city.sh 60 out/novo_take
```

O script simula, renderiza e valida; falhas preservam o diagnóstico. Use um
diretório novo. Dados, malhas e checkpoints anteriores foram preservados.

Os 66 wheels Python estão fixados por versão e hash em `requirements.lock`;
as origens conferidas estão em
[dependency-provenance.json](dependency-provenance.json). O Docker exige os
hashes ao instalar. Nenhum Python ou pacote de runtime foi instalado no host.
