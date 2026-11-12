# Model pool

The models Pawread can call, and what was actually measured about them.

This file records **measurements**, not intentions. A model is only listed as
usable if a real call was made against it and the response was checked.

## Tiers

Models are grouped into tiers. Select one with `--tier`.

| Tier | Models | Output price / 1M tokens |
|---|---|---|
| `test` | `qwen-flash`, `qwen-flash-2025-07-28` | $1.5 |
| `standard` | `qwen-plus`, `qwen-plus-latest`, `qwen-plus-2025-12-01`, `qwen-plus-2025-07-14` | $2.0 |
| `quality` | `deepseek-v4-flash-0731` | $4.5 |
| `quality` | `qwen-max` | $9.6 |
| `quality` | `deepseek-v4-pro-0813` | $13.5 |
| `quality` | `deepseek-v4-pro` | $24.0 |
| `max` | `qwen3.7-max` and three snapshots | $36.0 |
| `character` | `qwen-plus-character`, `qwen-flash-character` | — |

The machine-readable version is [`data/model_pool.json`](../data/model_pool.json).

Use `test` while you are tuning, `standard` for normal work, `quality` for
long-form reading tasks, and `max` only when the result has to be as good as
the model can make it.

## Endpoints

| Purpose | Endpoint |
|---|---|
| Search, structured output | `https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation` |
| Model catalogue | `https://dashscope.aliyuncs.com/api/v1/models` (paginated, 200 per page) |
| OpenAI-compatible | `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` |

**Search only works on the native endpoint.** On the OpenAI-compatible
endpoint, `extra_body.enable_search` is silently ignored — no error is raised,
but the model states that it cannot search, and `usage.plugins.search` is
missing from the response. This cost real time to find: the first round of
testing concluded that none of the models had network access, and switching to
the native endpoint produced real search results immediately.

## Cost per book

Reading one full book at the `standard` tier costs on the order of half a
million tokens. At the `test` tier, reading only the first few chapters of a
book costs roughly a tenth of that.

## Availability

A model that is absent from the catalogue's `features` field is not
necessarily callable, and a model that is present is not necessarily enabled
for your account. **Availability must be measured with a real call** — the
catalogue metadata is not a reliable signal.

## Reproducing the measurement

```bash
# Fetch the full catalogue
curl -s -H "Authorization: Bearer $DASHSCOPE_API_KEY" \
  "https://dashscope.aliyuncs.com/api/v1/models?page_no=1&page_size=200"

# Probe which models actually answer
python3 -c "import json; print(json.load(open('logs/model_probe.json')))"
```

The raw artifacts are written to `logs/` and are not committed:

| File | Contents |
|---|---|
| `logs/bailian_models.json` | The full catalogue metadata |
| `logs/model_probe.json` | The measured availability of each candidate |
