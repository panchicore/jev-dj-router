# Benchmark: Jev vs Laya on `/play` routing

**Jev (hosted, via the Vercel AI Gateway) vs Laya (open source, local on Apple Silicon)**, both used as a pre-classifier for the DJ chatbot in this repo. Both get the same 25 labeled requests and the same 9 typed questions.

## TL;DR

| | Jev | Laya (English) | Laya (multilingual) |
|---|---|---|---|
| Route accuracy | **25/25** | 12/25 | 8/25 |
| Correct **and** confident (≥ 0.6) | **23/25** | 7/25 | 3/25 |
| Modifiers, precision / recall @ 0.8 | **100% / 100%** | 0% / 0% | 20% / 12% |
| Latency p50 | 544 ms | 380 ms | **183 ms** |
| Cost | ~$36 / 1M requests | **$0** (local) | **$0** (local) |
| Deterministic | no (2 route flips in 3 runs) | **yes** | **yes** |

**For this task, Laya is not a drop-in replacement for Jev.** Laya is faster, free, offline and deterministic. But it gets less than half of the routes right, its confidence is low even when it is right, and on modifiers it does no better than always answering "no". Jev gets every route right, and its confidence scores separate right from wrong cleanly enough to set thresholds.

## Setup

| | |
|---|---|
| Date | 2026-09-23 |
| Machine | Apple M1 Pro, 32 GB, macOS 15.6.1 |
| Jev | `typesafe-ai/jev` via `POST https://ai-gateway.vercel.sh/typesafe/v1/systemone` |
| Laya | [`convaiinnovations/laya`](https://huggingface.co/convaiinnovations/laya) and [`convaiinnovations/laya-multilingual`](https://huggingface.co/convaiinnovations/laya-multilingual), in-process via `laya-mlx` 0.2.0 (MLX, Apple Silicon) |
| Python | 3.14.2 |
| Dataset | the 25 `REQUESTS` in [`dj_router.py`](dj_router.py), hand-labeled in [`bench.py`](bench.py): 11 English, 14 Spanish or mixed |
| Questions | identical for both models (`dj_router.QUESTIONS`): 1 route `choice` (11 options), 7 `noul`, 1 `score` |
| Runs | 3 per request per model, after one warm-up call |
| Raw data | [`results/2026-09-23.json`](results/2026-09-23.json): every answer from every run, plus the environment |

The two backends take the same TypeSafe question shape (`state` + `{id: {type, instructions, criteria}}`) and return the same answer shape, so the benchmark sends them the exact same payload.

## Methodology

- **Route accuracy:** the top `choice` is in the accepted set for that request. Requests that are genuinely ambiguous accept more than one route. For example, "metallica one" accepts `track | artist`, and "reggaeton viejo" accepts `genre | era`.
- **Correct and confident:** a correct route whose confidence is ≥ 0.6. Below that, the router asks the user instead of acting (`ask_user_first`), so a correct but unconfident route is not useful in practice.
- **Modifiers:** `is_lyrics`, `has_exclusion`, `wants_version`, `is_queue` and `relative_ref`, each scored as a yes/no against the labels. Arguable cells are left out, for example `relative_ref` on "la que sonó hace rato". There are 122 scored cells and only 8 positives, so "always no" already scores **93% accuracy**. That is why the table reports **precision / recall** as well.
- **Modifier gap:** the lowest score of a true positive vs the highest score of a false positive. If the lowest true positive is higher, there is a threshold that separates them perfectly.
- **Latency:** wall-clock time per request. For Jev, only the successful HTTP attempt counts; waiting time between retries is left out. For Laya, the model is already loaded in memory (in-process).

## Results

| Metric | Jev | Laya | Laya multilingual |
|---|---|---|---|
| Route accuracy | **25/25** | 12/25 | 8/25 |
| · English requests | 11/11 | 5/11 | 2/11 |
| · Spanish / mixed requests | 14/14 | 7/14 | 6/14 |
| Correct and confident (≥ 0.6) | **23/25** | 7/25 | 3/25 |
| Mean route confidence | 0.91 | 0.52 | 0.42 |
| Modifier accuracy @ 0.5 (always-no: 93%) | 98% | 94% | 85% |
| Modifier precision / recall @ 0.5 | 80% / 100% | 60% / 38% | 14% / 25% |
| Modifier accuracy @ 0.8 (always-no: 93%) | **100%** | 93% | 91% |
| Modifier precision / recall @ 0.8 | **100% / 100%** | 0% / 0% | 20% / 12% |
| Modifier gap (min TP / max FP) | **0.92 / 0.64** ✅ | 0.19 / 0.81 ❌ | 0.01 / 0.89 ❌ |
| Route flips across 3 runs | 2 | 0 | 0 |
| Latency p50 | 544 ms | 380 ms | 183 ms |
| Latency p95 | 12,868 ms ⚠️ | 401 ms | 434 ms |
| Model load (cold) | — | 0.7 s | 0.9 s |
| Cost | ~$0.000036 / request | $0 | $0 |

⚠️ **Jev's p95 reflects an overloaded provider, not its normal latency.** During the run, TypeSafe returned `529 system_overloaded` (2 retries), and some successful calls were slow too. In earlier runs that day, Jev took ~430–820 ms per call.

### Route per request (run 1)

❌ marks a route outside the accepted set.

| Request | Expected | Jev | Laya | Laya multilingual |
|---|---|---|---|---|
| cold play | `artist` | `artist` 0.98 | ❌ `genre` 0.35 | ❌ `control` 0.42 |
| yellow from cold play | `track` | `track` 0.99 | ❌ `control` 0.36 | ❌ `artist` 0.24 |
| gym music | `activity_mood` | `activity_mood` 1.00 | ❌ `genre` 0.42 | ❌ `control` 0.40 |
| some hip hop music | `genre` | `genre` 1.00 | `genre` 0.95 | `genre` 0.46 |
| algo para estudiar | `activity_mood` | `activity_mood` 0.99 | `activity_mood` 0.37 | `activity_mood` 0.53 |
| ponme la de despacito | `track` | `track` 0.93 | `track` 0.27 | ❌ `control` 0.35 |
| something like radiohead but happier | `similar` | `similar` 1.00 | `similar` 0.83 | ❌ `control` 0.22 |
| musica de los 80s para una fiesta | `era` \| `activity_mood` | `era` 1.00 | `era` 0.71 | ❌ `genre` 0.36 |
| the new taylor swift album | `album` | `album` 0.99 | `album` 0.79 | `album` 0.73 |
| otra vez | `history` | `history` 0.95 | `history` 0.40 | ❌ `control` 0.24 |
| that song that goes na na na | `unclear` \| `track` | `unclear` 0.78 | `track` 0.96 | ❌ `control` 0.33 |
| reggaeton viejo | `genre` \| `era` | `genre` 0.75 | ❌ `similar` 0.37 | `genre` 0.75 |
| asdf | `unclear` | `unclear` 0.83 | ❌ `genre` 0.33 | ❌ `control` 0.63 |
| metallica one | `track` \| `artist` | `track` 0.27 | ❌ `genre` 0.27 | ❌ `control` 0.29 |
| nirvana del ultimo album | `album` | `album` 0.89 | `album` 1.00 | `album` 0.97 |
| la que dice 'is this the real life, is this just fantasy' | `track` | `track` 1.00 | ❌ `unclear` 0.77 | ❌ `control` 0.47 |
| rock pero nada de metal ni nada muy pesado | `genre` | `genre` 1.00 | `genre` 0.97 | `genre` 0.52 |
| el soundtrack de interstellar | `album` | `album` 0.83 | ❌ `similar` 0.39 | ❌ `control` 0.25 |
| la versión acústica de wonderwall | `track` | `track` 1.00 | ❌ `history` 0.40 | ❌ `control` 0.20 |
| la que sonó hace rato, la segunda | `history` | `history` 1.00 | ❌ `track` 0.50 | ❌ `control` 0.24 |
| un podcast de historia | `out_of_scope` | `out_of_scope` 1.00 | ❌ `history` 0.51 | ❌ `history` 0.80 |
| algo para dedicarle a mi novia que está triste 💔 | `activity_mood` | `activity_mood` 0.94 | ❌ `history` 0.21 | `activity_mood` 0.22 |
| bad bunny, luego karol g y después algo de feid | `artist` | `artist` 1.00 | ❌ `track` 0.25 | `artist` 0.16 |
| smells like teen spirit pero cover de otra banda | `track` \| `similar` | `track` 0.56 | `track` 0.38 | ❌ `control` 0.55 |
| metalica enter sandman plz | `track` | `track` 1.00 | `track` 0.35 | ❌ `genre` 0.22 |

## What the numbers say

1. **Jev gets the routes right and knows when it is right.** It scored 25/25 with a mean confidence of 0.91, and its only low-confidence answers are on the genuinely ambiguous cases ("metallica one" 0.27, the cover 0.56). That is exactly the behavior the thresholds in this repo rely on.
2. **Laya is often right with low confidence, so the router could not act on it.** It got 12 routes right, but only 7 with confidence ≥ 0.6. In a router that asks the user whenever confidence is low, Laya would ask on most requests.
3. **Laya multilingual defaults to `control`.** 13 of its 17 wrong routes are `control`. It looks like an overused default rather than an actual judgment. Being multilingual did not help it with the Spanish requests either (6/14, vs 7/14 for the English model).
4. **Laya's modifiers have no usable threshold.** Its false positives score higher than its true positives (lowest true positive 0.19 vs highest false positive 0.81), so no threshold separates them. At 0.8 it detects nothing correctly; at 0.5 it finds 38% of the positives.
5. **Laya's edge is operational.** It is ~1.4–3× faster at p50, has stable latency (p95 ≈ p50), costs nothing, works offline, and gives the same answer every run. Jev flipped the route on 2 of 25 requests across runs.

## Caveats

- **Only 25 requests, 1 day, 1 machine.** Treat this as a smoke test, not a leaderboard.
- **The benchmark favors Jev by design.** The questions, the route descriptions and the labels were written while iterating against Jev (see [README](README.md)), so they are tuned to how Jev reads them. Laya might do better with questions designed for it. Laya did separate a single, simpler question reasonably well in a separate experiment (ID-without-title detection).
- **The route question is hard for an encoder.** It has 11 options with long descriptions. Laya is a 421M-parameter encoder (ModernBERT-large); Jev's size and architecture are not public.
- **The Jev tail latency came from a provider overload** (see above) and should be re-measured.
- **`laya-typed-decisions` was not included.** In the ID-detection experiment its scores clustered around 0.4 without separating anything.

## When to use which

| Use | If |
|---|---|
| **Jev** | You need correct routing and trustworthy confidence, especially with multi-option `choice` questions or modifiers where false positives are expensive. |
| **Laya** | The questions are simple and binary, and you care more about latency, cost, privacy or offline operation. Pair it with deterministic code (regexes, catalog lookups) and validate on your own labeled set first. |

## Reproduce

```bash
uv venv .venv && uv pip install --python .venv/bin/python "jevals[laya]" rich   # Apple Silicon
export AI_GATEWAY_API_KEY=...      # or a Vercel OIDC token, see README
.venv/bin/python bench.py --runs 3 # writes results/<date>.json
```

Options: `--laya MODEL ...` picks the Laya models to test, `--no-jev` skips Jev, `--out FILE` sets the output file.
