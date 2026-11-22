"""Machine translation of conversation messages into Chinese, for the web report.

Translations are cached per text in results/translations/<sha16>.json, so a
message is translated once. The UI labels every translation "机器翻译".
The model is config.yaml models.translator (a free tier model).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "results" / "translations"
BATCH_CHARS = 2500

PROMPT = """Translate each English text below into natural simplified Chinese for a product manager reading a customer-service conversation.
Keep order ids (like #W1234567), item ids, product names in parentheses after the Chinese name, numbers, emails and amounts exactly.
Do not add or drop information. If a text is already Chinese, copy it.
Answer with JSON only: {"translations": [{"i": <index>, "zh": "<Chinese>"}]}

Texts:
"""


def _key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def cached(text: str) -> str | None:
    path = CACHE / f"{_key(text)}.json"
    zh = json.loads(path.read_text()).get("zh") if path.exists() else None
    return zh if zh and zh.strip() else None      # an empty answer is not a translation


def _call(texts: list[str], model: str) -> dict[int, str]:
    import litellm

    from runner.gateway import extract_json, install
    from runner.run_batch import gateway_config, load_config

    gw = install(gateway_config(load_config(ROOT / "config.yaml")))
    gw.run_tag = "translate_web"
    body = "\n".join(json.dumps({"i": i, "text": t}, ensure_ascii=False) for i, t in enumerate(texts))
    resp = litellm.completion(model=model, messages=[{"role": "user", "content": PROMPT + body}],
                              temperature=0.0, tracecheck_role="translator")
    data = json.loads(extract_json(resp.choices[0].message.content or "") or "{}")
    return {int(x["i"]): str(x["zh"]) for x in data.get("translations", []) if "i" in x and "zh" in x}


def translate(texts: list[str]) -> dict[str, str]:
    """{text: Chinese} for every text; untranslatable ones are left out (UI then shows only the original)."""
    import yaml

    model = yaml.safe_load((ROOT / "config.yaml").read_text())["models"]["translator"]
    out, todo = {}, []
    for t in dict.fromkeys(x for x in texts if x and x.strip()):
        hit = cached(t)
        if hit is not None:
            out[t] = hit
        else:
            todo.append(t)
    # Two passes: batches first, then whatever the model skipped, one text per call.
    for size in (BATCH_CHARS, 0):
        pending = [t for t in todo if t not in out]
        batches: list[list[str]] = []
        for t in pending:
            if batches and size and sum(map(len, batches[-1])) + len(t) < size:
                batches[-1].append(t)
            else:
                batches.append([t])
        for batch in batches:
            try:
                got = _call(batch, model)
            except Exception:  # noqa: BLE001 - a failed batch just stays untranslated
                got = {}
            CACHE.mkdir(parents=True, exist_ok=True)
            for i, zh in got.items():
                if 0 <= i < len(batch) and zh.strip():
                    out[batch[i]] = zh
                    (CACHE / f"{_key(batch[i])}.json").write_text(
                        json.dumps({"model": model, "text": batch[i], "zh": zh}, ensure_ascii=False))
    return out
