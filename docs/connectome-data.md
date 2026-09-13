# Connectome data: sources and offline preparation

The public datasets can help resolve the sensory and descending-neuron mappings
needed by [delivery gate 1](embodied-roadmap.md#delivery-order). This inventory,
checked on **2026-09-13**, prepares that investigation. It does not change the
FlyWire 630 reference, the experimental dynamics or the browser's motor control.

## Which dataset is which?

| Dataset | Specimen and coverage | Relevance here |
|---|---|---|
| FAFB / FlyWire 630 | Female brain; current Shiu/Spiller model input | Preserve the numerical reference and its IDs |
| FAFB / FlyWire 783 | Later reconstruction release of the FAFB brain | Updated anatomical labels and connectivity for comparison |
| BANC 888 | A different female; brain and nerve cord in one reconstruction | Compare sensory-to-descending and descending-to-premotor pathways |
| MANC 1.2.1 | Male nerve cord | Compare premotor organization; it supplies no brain |
| MAOL 1.1 | Male right optic lobe | Visual anatomy; this specimen was extended into MaleCNS |
| MaleCNS 1.0 / MCNS | Male brain and nerve cord | Whole-CNS comparison, with sex and specimen differences explicit |

Dataset labels and current interface versions are listed by
[Codex](https://codex.flywire.ai/). The
[BANC paper](https://www.nature.com/articles/s41586-026-10735-w) and
[Janelia optic-lobe description](https://www.janelia.org/project-team/flyem/optic-lobe)
clarify the anatomical coverage. Shared cell-type names do not make root IDs,
connectivity weights or body coordinates interchangeable.

## Access without the interactive login

Codex is Princeton's Connectome Data Explorer. Its
[access explanation](https://codex.flywire.ai/) describes Google sign-in for
interactive services. During this check, unauthenticated requests to
`/api/download?dataset=fafb` and `dataset=banc` returned the sign-in HTML after
redirects, despite download examples in the
[FAQ](https://codex.flywire.ai/faq). HTTP success alone did not mean data had
downloaded.

Use the authors' static deposits or public object URLs below. A
`console.cloud.google.com/storage/browser/...` link opens Google's console and
can ask for login even when the corresponding object is publicly readable at
`https://storage.googleapis.com/BUCKET/OBJECT`. The successful downloads here used
ordinary HTTPS with no account, cloud CLI, CAVE token or installed SDK.

The [FlyConnectome tutorial](https://github.com/seung-lab/FlyConnectome) remains
useful for programmatic access, and the annotation authors also link their
[public CATMAID instance](https://fafb-flywire.catmaid.org/).

## Downloaded and verified

The following files are stored separately under the ignored
`data/connectome-catalog/` directory. Sizes are exact bytes; the source-file total
is **439,639,533 bytes** including the annotation READMEs, column dictionaries
and ten comparative skeletons.
`downloads.json` records URLs, SHA-256, source MD5 or Git blob hashes, and sizes.

| File | Bytes | Source/version |
|---|---:|---|
| FAFB neuron annotations v2.1.0 | 27,015,208 | [Pinned publication-era TSV](https://raw.githubusercontent.com/flyconnectome/flywire_annotations/ebd66db2596fcc39c6950fb54ea3efa00f7fe8a0/supplemental_files/Supplemental_file1_neuron_annotations.tsv) |
| FAFB neuron annotations v3.1.0 | 31,718,505 | [Pinned updated TSV](https://raw.githubusercontent.com/flyconnectome/flywire_annotations/8587524c1748ce5ef2080822a2fc890fc03bf597/supplemental_files/Supplemental_file1_neuron_annotations.tsv) |
| `banc_888_edgelist_simple_v2.feather` | 305,250,378 | [Author bucket, generation 1780396134870867](https://storage.googleapis.com/lee-lab_brain-and-nerve-cord-fly-connectome/compiled_data/banc_888/banc_888_edgelist_simple_v2.feather?generation=1780396134870867) |
| `banc_888_meta.feather` | 57,503,026 | [Author bucket, generation 1787336614757441](https://storage.googleapis.com/lee-lab_brain-and-nerve-cord-fly-connectome/compiled_data/banc_888/banc_888_meta.feather?generation=1787336614757441) |
| MaleCNS 1.0 body annotations | 14,483,314 | [Janelia bucket, generation 1780494878811468](https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome/body-annotations-male-cns-v1.0-minconf-0.5.feather?generation=1780494878811468) |
| Ten MaleCNS descending-neuron SWCs | 3,629,513 | Individual objects from the [documented native skeleton collection](https://male-cns.janelia.org/download/); generation and MD5 recorded per file |

The [annotation changelog](https://github.com/flyconnectome/flywire_annotations)
distinguishes v1.1.0's materialization 630 from the later annotation releases,
which use 783. Annotation version and segmentation release are separate axes.
The existing v1.1.0 TSV remains in `data/neural-reference/`; it was checksum
verified and reused without making another source copy.

The BANC paper's static deposit is
[Harvard Dataverse 10.7910/DVN/7WTH1N](https://doi.org/10.7910/DVN/7WTH1N),
superseding the preprint deposit `8TFGGB`. Its metadata API was accessible;
the attempted file download returned HTTP 403. The
[authors document their public bucket](https://github.com/htem/bancpipeline)
as another source.

The downloaded BANC edge file matches Dataverse version 3.0's size and MD5
`394406f8a9bdf093c895f95aff4f6c49`. The bucket metadata is a later snapshot,
modified 2026-08-21: MD5 `8c2b93a608c7163ec9d94d68e0756ff4`. It differs from
Dataverse file 14033740, whose 57,550,610 bytes have MD5
`6275eda42f98c49539d1ab513d979d09`. Do not describe this combination as the
unchanged paper snapshot. Metadata contains both `root_888` and `root_890`;
choose the ID column that matches the edge release and measure join coverage.

The BANC deposit and
[MaleCNS download page](https://male-cns.janelia.org/download/) specify CC BY.
Keep the original attribution and applicable paper citations with derivatives.
Check the annotation repository's citation guidance and each deposit's license
before redistributing data. Raw datasets are not included in this repository.

## What the local inspection found

The two FAFB TSVs contain 139,255 and 139,248 rows respectively. Matching unique
`supervoxel_id` anchors against v1.1.0 produced 127,860 and 127,812 annotation
correspondences. Three duplicated v630 anchors were excluded. These are offline
anchor correspondences, not a complete CAVE split/merge history or proof that
every mapped neuron retained identical segmentation.

All **145** neurons used in the odor feasibility probe have anchor matches:
135 sensory inputs and ten descending candidates. **Ten root IDs changed**
between 630 and 783. The candidate export preserves IDs, original column names,
sides and labels from both releases. Examples from v3.1.0:

| v630 annotation | v783 `cell_type` | Interpretation |
|---|---|---|
| `cell_type=DNae003`, `hemibrain_type=DNa01` | `DNae001` | Do not collapse this into the separate `cell_type=DNa01` pair |
| `cell_type=DNpe060`, `hemibrain_type=DNp09` | `DNp71` | Distinct from the pair now explicitly typed `DNp09` |
| Blank `cell_type`, `hemibrain_type=DNa02` | `DNa02` | Later annotation supplies the explicit type |

The v3.1.0 table also contains **74 hygrosensory candidates**, all with anchor
matches to IDs present in the current v630 graph. These provide a concrete
starting list for investigating a moisture channel. An annotation alone
does not establish water seeking, sensor gain, deprivation signaling or a useful
continuous neural response.

The downloaded BANC metadata contains **188,508 rows and 81 columns**, including
glia, non-neurons and unclassified rows. It is not a count of simulated neurons.
Its edge file contains **11,752,828 rows**, summing to **35,733,096** in `count`;
**156,311 rows are self-connections**, and **8,582,509 have count below three**.
Preserve the actual file semantics. The
[linked dataset tutorial](https://github.com/sjcabs/fly_connectome_data_tutorial/blob/main/data/dataset_documentation/banc_data.md)
describes different dimensions and says autapses are excluded; that statement
does not describe these checksum-verified bytes.

MaleCNS body annotations contain **211,577 rows and 36 columns**. As with BANC,
table rows are not the curated neuron count displayed in Codex. The archived
schemas identify the available cross-dataset type, side and quality fields.
Ten candidate skeletons contain 106,239 nodes in total; all parsed as seven-column
SWC with finite coordinates, unique node IDs and valid parent references.
Their native coordinates use 8 nm units. This checks file structure, not anatomy
registration or functional homology.

Codex also has dataset-specific connection thresholds; the FAQ lists five
synapses for FAFB and three for BANC. In addition,
[Codex's source credits](https://codex.flywire.ai/about_flywire) describe a change
of synapse predictions after July 2025. Thus the label “783” by itself does not
make current Codex connectivity equivalent to the 2024 Zenodo file or to our
signed v630 model weights.

## Located, but not downloaded

| Resource | Direct source | Reason/status |
|---|---|---|
| FAFB 783 aggregated connections, about 852 MB | [Feather](https://zenodo.org/records/10676866/files/proofread_connections_783.feather?download=1) | Zenodo returned HTTP 504 on metadata and direct-file probes |
| FAFB 783 proofread root IDs, about 1.1 MB | [NumPy array](https://zenodo.org/records/10676866/files/proofread_root_ids_783.npy?download=1) | Same access failure; retry with the connections file |
| FAFB individual synapses, about 9.5 GB | [Feather](https://zenodo.org/records/10676866/files/flywire_synapses_783.feather?download=1) | Defer until synapse coordinates or individual predictions are needed |
| FAFB skeletons, about 5.4 GB | [Parquet](https://zenodo.org/records/10877326/files/sk_lod1_783_healed_ds2.parquet?download=1) | Prefer selected candidate morphology before a complete download |
| FAFB NBLAST matrices, about 809, 212 and 223 MB | [Zenodo file list](https://zenodo.org/records/10877326) | Defer all-by-all morphology analysis |
| BANC full synapse/skeleton collections | [Dataverse snapshot](https://doi.org/10.7910/DVN/7WTH1N) | Indexed locally; large bundles are not needed for the initial mapping review |
| MaleCNS full connectivity and additional skeletons | [Janelia downloads](https://male-cns.janelia.org/download/) | Annotations and ten candidate skeletons acquired; full graph deferred |
| MANC and MAOL bulk data | [MANC](https://www.janelia.org/project-team/flyem/manc-connectome), [MAOL](https://www.janelia.org/project-team/flyem/optic-lobe) | Official bucket entry points recorded; no additional specimen graph acquired |

[Zenodo 10676866](https://zenodo.org/records/10676866) publishes MD5
`f48f972d262323a102aed49af1396b8a` for the aggregated connections and
`e0e6c19732fd8c7a4e39a2d170105421` for the proofread IDs. Its connection rows are
neuron-pair-and-neuropil aggregates, not individual synapses.
[Zenodo 10877326](https://zenodo.org/records/10877326) identifies the skeleton
coordinates as nanometres in the FAFB space and the IDs as release 783.
Do not confuse these with the annotation anchors' 4×4×40 nm voxel units or with
BANC, MaleCNS and flybody coordinates.

## Resume the investigation

The local `data/connectome-catalog/README.md` indexes the acquisition manifest,
source metadata, measured schemas, anchor tables and small candidate exports.
Downloads ran sequentially at a 4 MiB/s ceiling; data inspection used the existing
bounded Docker tooling, with a measured process peak of 447.7 MiB. No downloaded
notebook or source program was executed.

First review the ten descending mappings and the moisture candidates against
their anatomy and published functional evidence. Use the BANC and MaleCNS type
exports as comparative hypotheses; verify side and matching annotations before
following their pathways. Retain v630 IDs when probing the current model.
Then return to the repeated-cue and removal checks in
[sensory feasibility](sensory-feasibility.md). More anatomical data does not
by itself resolve the failed second-cue response.

The [whatisabrain fly page](https://whatisabrain.com/fly) is a useful BANC anatomy
presentation. Its own credits identify NeuroMechFly as a separate body, describe
manual nervous-system placement and explain that walking replays recorded leg
strides. Those visuals do not establish connectome-driven locomotion.
