# /// script
# requires-python = ">=3.11"
# dependencies = ["mlx-whisper"]
# ///
"""transcribe.py <audio> <out.json> [--prompt "FL Studio, Image-Line"] [--lang ru]
Пословная расшифровка (mlx-whisper large-v3-turbo, локально на Apple Silicon).
out.json: [{w, s, e}]. В stdout — сегменты со словами и таймингами.
--prompt подсказывает Whisper имена/бренды/сленг: сильно улучшает их распознавание."""
import argparse, json, mlx_whisper
ap = argparse.ArgumentParser(); ap.add_argument("audio"); ap.add_argument("out")
ap.add_argument("--prompt", default=None); ap.add_argument("--lang", default="ru")
ap.add_argument("--model", default="mlx-community/whisper-large-v3-turbo")
a = ap.parse_args()
r = mlx_whisper.transcribe(a.audio, path_or_hf_repo=a.model, language=a.lang, word_timestamps=True, initial_prompt=a.prompt)
words = []
for sg in r["segments"]:
    ws = [dict(w=x["word"].strip(), s=round(x["start"], 2), e=round(x["end"], 2)) for x in sg["words"]]
    words += ws
    print(f'[{sg["start"]:7.2f}-{sg["end"]:7.2f}] ' + " ".join(f'{x["w"]}[{x["s"]:.2f}-{x["e"]:.2f}]' for x in ws))
json.dump(words, open(a.out, "w"), ensure_ascii=False, indent=0)
