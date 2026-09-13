# Fábrica de software com agentes: Codex + Astra

> Historical method idea, not the active implementation queue. Food seeking,
> physical flight, landing and consumption take priority under the
> [delivery plan](embodied-roadmap.md). Nothing here replaces the validated
> gates; it is an option for future components or a sibling project.

Registrado em 13/09/2026, a partir de um texto público de dzhng ("How to build
your own fly simulator with Codex and Astra"). É uma **possibilidade de
método**, não um plano ativo: um fluxo de fábrica de software em que as
decisões se concentram no início (e são revisadas no fim), enquanto a
implementação roda assíncrona e autônoma. O autor enfatiza que não é um botão
fácil — exige trabalho real nas pontas.

## O método descrito

1. **Pré-requisito**: Codex Pro com acesso ao Astra (renderização 3D).
   Definir o tipo de simulador desejado (jogo similar ou outra coisa).
2. **Referência de dados**: apontar o agente para o post do Google Research,
   ["A connectomics milestone: mapping the complete male fruit fly brain"](https://research.google/blog/a-connectomics-milestone-mapping-the-complete-male-fruit-fly-brain/)
   (connectoma masculino completo; o inventário de dados do projeto já cobre
   as fontes masculinas em [connectome-data.md](connectome-data.md)).
3. **Spikes antes da implementação**: protótipos descartáveis de cada mecânica
   (visão, olfato, voo etc.), em qualquer linguagem, só para desriskar.
   Documentar resultados; o código do spike não vai para o produto.
4. **Explorar incógnitas**: skill
   [`/explore-unknowns`](https://github.com/dzhng/skills) — ida e volta com o
   agente para mapear todas as incógnitas (15 min a 2 h). Saída: mapa de
   incógnitas para revisão. Neste ponto entram referências (outros jogos,
   o tweet original do autor).
5. **Spec**: skill `/write-specs` do mesmo repositório — subagentes com
   revisão adversária produzem a spec completa (também pode demorar).
6. **Revisão da spec**: opcional; o desrisk já cobriu o essencial.
7. **Implementação como goal**: não chamar a skill diretamente, e sim
   `/goal /implement-spec` — o agente itera em loop até implementar a spec
   inteira (1–2 dias). A skill traz sub-skills de teste automatizado e
   automação de browser, com o objetivo de entregar o produto pronto.
8. **Revisão pós-implementação**: ler o **choices file** escrito ao final,
   com todas as decisões que o agente tomou por conta própria e que a spec
   não cobriu — entender arquitetura e tradeoffs sem ler o código.

## Mapeamento com a prática atual do projeto

| Etapa do método | Equivalente aqui |
|---|---|
| Spikes desriskando mecânicas | Probes isolados já praticados; [sensory-feasibility.md](sensory-feasibility.md) |
| Explore unknowns | Gates ordenados no [delivery plan](embodied-roadmap.md) |
| Spec com revisão adversária | Guias de produto em `docs/` |
| Testes/automação embutidos | Validadores em contêineres descartáveis; checks de browser |
| Choices file | Ausente — ideia aproveitável: registro explícito das decisões tomadas fora da spec |

## O que aproveitar como possibilidade

- **`/goal` loop com spec fechada** para componentes novos e bem delimitados,
  mantendo os gates de validação do projeto como critério de aceite.
- **Choices file**: registrar decisões de implementação tomadas fora do
  planejamento, para revisão sem leitura de código.
- **Spikes documentados e descartáveis** como etapa formal antes de portar
  algo ao produto.
- **Post do Google sobre o connectoma masculino** como referência quando o
  alvo anatômico masculino avançar (ver [connectome-data.md](connectome-data.md)).

## O que não aproveitar sem cuidado

- O método começa do zero e prioriza velocidade de fábrica; este projeto é
  validação-primeiro (checkpoints oficiais, comparação numérica com a
  referência, gates de forrageamento pela UI real). Nunca trocar um gate
  validado por entrega rápida de fábrica.
- Astra e Codex Pro não fazem parte do stack atual — é possibilidade de
  ferramenta, não infraestrutura deste repositório.
- Renderização gerada por IA não substitui física nativa: o produto exige
  MuJoCo, não visual sintético.
