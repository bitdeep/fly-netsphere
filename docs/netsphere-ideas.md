# Referências e próximos experimentos na NETSPHERE

> Historical ideas, not the active implementation queue. Food seeking, physical
> flight, landing and consumption take priority under the
> [delivery plan](embodied-roadmap.md). The proposals below remain deferred.

Leitura em 12/09/2026, durante o cálculo do novo minuto de voo.
Estas são propostas; não são capacidades já implementadas.

## O que o FLY ATLAS oferece

O [FLY ATLAS](https://fly-atlas.vercel.app/) informa que seu grafo de origem
tem 166.700 neurônios e 25.582.938 conexões dirigidas. A visualização inclui
139.662 posições de corpos celulares; as outras 27.038 células não têm
posição registrada. Portanto, a diferença entre as contagens tem uma
explicação explícita na própria página.

O atlas mantém até oito entradas mais fortes por célula posicionada, e as
linhas ligam os corpos celulares diretamente. Não são reconstruções de axônios
e dendritos, nem atividade neural sendo simulada. Isso é útil como referência
de inspeção: selecionar uma entidade, mostrar sua vizinhança e explicar o
significado da medida.

A página [FlyTilt](https://fly-atlas.vercel.app/flytilt) descreve gravações de
experimentos que ajustam ganhos e tempo de resposta de um joystick a partir
de atividade do modelo. Ela explicita que corpo, sensores e servos têm
aproximações e que a animação da pega não é uma reconstrução muscular.
É uma referência de apresentação de tentativas e resultados, sem confundir
o efeito visual com a grandeza que foi calculada.

Para dados e versões, a referência canônica é o
[MaleCNS da Janelia](https://male-cns.janelia.org/), com
[anotações, pesos, sinapses e morfologias disponíveis](https://male-cns.janelia.org/download/).
Nenhum dataset novo ou código desses sites foi instalado ou executado aqui.

## Ideias para mostrar em vídeo

1. **Travessia do poço.** Um distrito com profundidade vertical, cabos
   suspensos, vãos e dutos em alturas diferentes. A mosca precisaria escolher
   uma passagem em três dimensões. Testar primeiro a estabilidade nas subidas
   e descidas, mantendo a margem para as asas e a continuidade física.
2. **A Cidade muda.** Comparar duas execuções com a mesma condição inicial
   e uma passagem bloqueada em apenas uma delas. Mostrar os dois voos
   e medir a mudança de percurso e os contatos. O teste com pilar deslocado
   já fornece a base de validação; falta construir essa apresentação.
3. **Modo observatório.** Poder pausar o replay físico, selecionar a mosca
   e inspecionar velocidade, inclinação, margem até obstáculos e comando
   escolhido pelo navegador. A gravação principal continua limpa; a visão
   técnica mostra os dados registrados no mesmo instante.

## Caminho para um experimento neural

A etapa útil antes de acoplar um connectome é colocar sensores explícitos
no corpo, registrar suas leituras e avaliar um controlador que dependa
dessas observações. O navegador atual recebe a geometria do mundo.

Uma futura ligação neural exigiria definir a codificação sensorial e a
leitura motora, testar se sua saída realmente altera os atuadores e comparar
com uma versão sem essa ligação. Só depois faria sentido exibir atividade
neural sincronizada ao voo como parte do controlador. O atlas sozinho não
fornece essa integração.
