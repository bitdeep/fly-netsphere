# fly living on NETSPHERE — ajuste de postura e materiais

> Historical recording report. These measurements describe the offline learned
> flight controller and geometric navigator. They do not validate browser
> seeking or flight; current work follows the [delivery plan](embodied-roadmap.md).

[Vídeo de um minuto](https://github.com/bitdeep/fly-netsphere/releases/download/v0.1.0/netsphere_60s-fly_city.mp4) ·
[Validação automática](https://github.com/bitdeep/fly-netsphere/releases/download/v0.1.0/netsphere_60s-validation.json) ·
[Métricas físicas](https://github.com/bitdeep/fly-netsphere/releases/download/v0.1.0/netsphere_60s-metrics.json) ·
[Comparação de postura](https://github.com/bitdeep/fly-netsphere/releases/download/v0.1.0/netsphere_60s-posture_comparison.json) ·
[Teste de desvio](https://github.com/bitdeep/fly-netsphere/releases/download/v0.1.0/netsphere_60s-avoidance.json)

O ambiente ganhou chapas de acesso, grelhas, fixadores, juntas, marcas de
serviço e desgaste. As texturas são desenhadas em coordenadas de superfície
e aplicadas aos sólidos 3D. Placas físicas identificam a NETSPHERE; novos
módulos de parede e anéis dos pilares também têm colisão. O modelo contém
412 geometrias, incluindo a anatomia da mosca.

Não foram baixados assets, pacotes ou código externo para esta alteração.
Pillow e a fonte DejaVu já estavam na imagem Docker usada pelo projeto.

## Execução contínua

A RTX 4090 integrou 60 segundos contínuos de física no Docker, com 1.200.000
passos físicos, 300.000 controles e zero reinícios, contatos com o cenário
ou flags de limite do solver. O cálculo levou 886,11 segundos, após a
inicialização. A mosca percorreu 12,0162 metros, com altitude entre 3,92 e
7,25 cm e erro máximo de acompanhamento de 0,659 mm.

A inclinação anatômica mediana caiu de **47,46° para 35,32°**. No novo
take, 95% das medidas ficaram abaixo de 36,38°, e o máximo foi 38,67°.
A comparação usa 14.400 poses físicas em cada minuto, com a mesma definição
anatômica do ângulo. Os hashes dos fontes e do checkpoint coincidem com os
registrados no início da execução.

O teste de perturbação também passou com a nova postura: mover o primeiro
pilar em −3 cm mudou a trajetória em até 3,894 cm nos primeiros 1,2 s, sem
contato. Com o desvio desligado, a mosca atingiu o pilar e a execução foi
rejeitada em 0,76 s. Os 2.141 contatos contam ocorrências nos subpassos,
não obstáculos diferentes. Houve flag do solver após o impacto; a dinâmica
posterior à colisão não é um resultado aceito.

## Gravação validada

O FFprobe decodificou os 1.800 quadros em 1280×720 a 30 fps, com duração
de 60,000 segundos. Cada quadro combina oito poses efetivamente integradas,
com exposição de 1/120 s. O modelo compilado com suas texturas é o mesmo
que produziu os estados físicos.

A checagem de visibilidade percorreu todos os quadros: o mínimo foi de
3.619 pixels da mosca. A margem conservadora em torno da anatomia completa
ficou em 8,44 mm. Essa margem usa a distância ao cenário medida a 100 Hz
e o maior raio da anatomia nas 14.400 poses de exposição; o contador de
contatos observa cada subpasso na GPU.

Foram inspecionados os quadros inicial, intermediário e final, a
[folha de contato do minuto](https://github.com/bitdeep/fly-netsphere/releases/download/v0.1.0/netsphere_60s-contact_sheet.png) e o
[quadro com menor visibilidade](https://github.com/bitdeep/fly-netsphere/releases/download/v0.1.0/netsphere_60s-frame_least_visible.png).
O hash do renderer foi conferido com o registro da gravação.

SHA-256 do vídeo:
`fc6aeea817390b5e0cbd48a23ab14115d08c582dae26d19216cf341f28cc1570`

O registro de hardware identifica a RTX 4090.
Física, policy, WPG e renderização usam GPU; navegação geométrica e codificação
H.264 usam CPU. Todos os processos de runtime foram executados no Docker.

## Postura física e câmera

O primeiro minuto tinha inclinação anatômica mediana de **47,46°**. A medida
usa o vetor entre o centro do abdômen e o da cabeça em cada uma das 14.400
poses físicas das exposições; 0° significa horizontal. A câmera quase por
trás ainda encurtava a projeção do corpo.

Agora o controlador recebe uma referência de cruzeiro com 30° de elevação
do tórax. A policy responde por meio dos atuadores; não há rotação corretiva
do corpo no renderer nem reposicionamento durante a integração. A inclinação
anatômica resultante difere da referência do tórax e é medida separadamente.

A câmera passa a observar quase de lado, com azimute de 85° em relação à
direção do voo e elevação de 2°. Um raio contra os sólidos do cenário reduz
a distância da câmera quando necessário, preservando a visão da mosca.

Foram feitos testes físicos antes de escolher a postura:

| Referência do tórax | Resultado |
|---|---|
| 15° | Perdeu estabilidade em 0,26 s; descartada |
| 25° | Completou 2 s em curva, mas excedeu o limite de erro de 0,10 cm; descartada |
| 30° | Completou 2 s em curva, erro máximo de 0,066 cm e zero contatos |
| 30°, dentro da Cidade | Teste completo de 3 s aprovado, inclinação anatômica mediana de 35,25° |

As duas sondas de 2 s usaram curvas diferentes; não são uma comparação
controlada de desempenho entre ângulos. Elas serviram para eliminar opções
que falharam e selecionar a configuração submetida ao teste na Cidade.

Uma inclinação residual é parte do voo obtido com este controlador. O ajuste
não demonstra voo nivelado a 0° nem equivalência com todo o comportamento
natural de uma mosca. O navegador continua consultando a geometria conhecida
do cenário a 100 Hz; não é visão aprendida nem um connectome.

## Referência enviada pelo usuário

O [post de Matty Hempstead](https://x.com/mattyhempstead/status/2098114728178667934)
aponta para [fly-wirehead](https://github.com/mattyhempstead/fly-wirehead).
O README desse projeto descreve uma simulação neural, com atividade traduzida
em movimentos e visualização em Three.js, e explicita aproximações na
fisiologia e no movimento. O README foi consultado como referência documental,
sem instalação ou execução de seu código.

Aqui a base permanece o [flybody oficial](https://github.com/TuragaLab/flybody):
corpo anatômico, dinâmica das asas e policy de voo dentro do mesmo mundo
de colisão que aparece na gravação.
