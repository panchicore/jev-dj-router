# /// script
# requires-python = ">=3.10"
# dependencies = ["rich"]
# ///
"""DJ bot router: Jev classifies /play requests -> routing hint for the downstream LLM."""
import json, os, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = "https://ai-gateway.vercel.sh/typesafe/v1/systemone"
TOKEN = os.environ["AI_GATEWAY_API_KEY"]

QUESTIONS = {
    "route": {
        "type": "choice",
        "instructions": "What kind of music request is this?",
        "criteria": {
            "track": "A specific song, with or without artist (e.g. 'yellow from coldplay', 'bohemian rhapsody')",
            "artist": "An artist or band, no specific song (e.g. 'coldplay', 'bad bunny')",
            "album": "A specific album or record",
            "genre": "A music genre or style (e.g. 'hip hop', 'salsa', 'lo-fi')",
            "activity_mood": "Music for an activity, mood or context (e.g. 'gym music', 'something to relax', 'party')",
            "similar": "Music similar to / like some reference (e.g. 'something like radiohead')",
            "era": "Music from a decade, year or period (e.g. '80s hits', 'música de los 90')",
            "control": "Playback control of what is playing now (e.g. 'skip', 'louder', 'pause')",
            "history": "Replay something already played in this session (e.g. 'play it again', 'the one from before')",
            "out_of_scope": "Audio that is not music, like podcasts, audiobooks, radio shows or news",
            "unclear": "Not understandable as a music request or too vague to act on",
        },
    },
    "has_artist": {"type": "noul", "instructions": "Does the request name a specific artist or band?"},
    "has_track": {"type": "noul", "instructions": "Does the request name a specific song title?"},
    # modifiers: the route was right, but these nuances were getting lost
    "is_lyrics": {"type": "noul", "instructions": "Does the request quote song lyrics instead of naming the song title?"},
    "has_exclusion": {"type": "noul", "instructions": "Does the request say what NOT to play (a genre, artist or style to avoid)?"},
    "wants_version": {"type": "noul", "instructions": "Does the request ask for a specific version of a song, like acoustic, live, cover, remix or remastered?"},
    "is_queue": {"type": "noul", "instructions": "Does the request ask for several different things to be played in sequence?"},
    "relative_ref": {"type": "noul", "instructions": "Does the request refer to music relatively (latest, newest, first, most popular, best) instead of by its name?"},
    "energy": {
        "type": "score",
        "instructions": "What energy level of music does the user want?",
        "criteria": ["very chill", "chill", "medium", "upbeat", "very high energy"],
    },
}

REQUESTS = [
    "/play cold play",
    "/play yellow from cold play",
    "/play gym music",
    "/play some hip hop music",
    "/play algo para estudiar",
    "/play ponme la de despacito",
    "/play something like radiohead but happier",
    "/play musica de los 80s para una fiesta",
    "/play the new taylor swift album",
    "/play otra vez",
    "/play that song that goes na na na",
    "/play reggaeton viejo",
    "/play asdf",
    "/play metallica one",
    "/play nirvana del ultimo album",
    "/play la que dice 'is this the real life, is this just fantasy'",
    "/play rock pero nada de metal ni nada muy pesado",
    "/play el soundtrack de interstellar",
    "/play la versión acústica de wonderwall",
    "/play la que sonó hace rato, la segunda",
    "/play un podcast de historia",
    "/play algo para dedicarle a mi novia que está triste 💔",
    "/play bad bunny, luego karol g y después algo de feid",
    "/play smells like teen spirit pero cover de otra banda",
    "/play metalica enter sandman plz",
]

MODIFIERS = ("is_lyrics", "has_exclusion", "wants_version", "is_queue", "relative_ref")


def payload(state: str) -> dict:
    return {"model": "typesafe-ai/jev", "state": state, "questions": QUESTIONS}


def call(state: str) -> dict:
    body = json.dumps(payload(state)).encode()
    req = urllib.request.Request(
        URL, body, {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503) or attempt == 3:
                print(f"Jev {e.code}: {e.read().decode()[:300]}", file=sys.stderr)
                raise
            time.sleep(0.5 * 2**attempt)


def ask(state: str) -> tuple[dict, float]:
    t0 = time.perf_counter()
    answers = call(state)["answers"]
    return answers, (time.perf_counter() - t0) * 1000


def llm_hint(a: dict) -> dict:
    """What the downstream LLM receives as routing context."""
    r = a["route"]
    return {
        "route": r["choice"],
        "route_confidence": r["confidence"],
        "alternatives": {k: v for k, v in r["probabilities"].items() if v >= 0.15 and k != r["choice"]},
        "extract": [f for f, q in (("artist", "has_artist"), ("track", "has_track")) if a[q]["noul"] >= 0.5],
        # derived from the route: a "needs clarification" noul turned out noisy
        # high threshold: true positives score ≥0.9, false positives sit around 0.5–0.6
        "modifiers": [m for m in MODIFIERS if a[m]["noul"] >= 0.8],
        "ask_user_first": r["choice"] == "unclear" or r["confidence"] < 0.6,
        # None when Jev is unsure (e.g. a specific song: the catalog knows its energy, the text does not)
        "energy": a["energy"]["legend"][str(round(a["energy"]["score"]))] if a["energy"]["confidence"] >= 0.5 else None,
    }


def show(state: str) -> None:
    """-v mode: request payload, response, Jev summary and LLM hint, rendered with rich."""
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.table import Table

    c = Console()
    js = lambda o: Syntax(json.dumps(o, indent=2, ensure_ascii=False), "json", theme="monokai", background_color="default", word_wrap=True)

    t0 = time.perf_counter()
    res = call(state)
    ms = (time.perf_counter() - t0) * 1000

    gw = res.get("provider_metadata", {}).get("gateway", {})
    out = {k: v for k, v in res.items() if k != "provider_metadata"}
    out["provider_metadata"] = {"gateway": {k: gw.get(k) for k in ("cost", "marketCost", "generationId")}}

    c.print(Panel(js(payload(state)), title="[bold cyan]→ request[/]  POST /typesafe/v1/systemone", border_style="cyan", title_align="left"))
    c.print(Panel(js(out), title=f"[bold green]← response[/]  [bold white on green] {ms:.0f} ms [/]", border_style="green", title_align="left"))

    a = res["answers"]
    tbl = Table(box=None, pad_edge=False, show_header=True, header_style="dim")
    tbl.add_column("question"); tbl.add_column("type", style="dim"); tbl.add_column("answer", style="bold"); tbl.add_column("")
    bar = lambda p: f"[magenta]{'█' * round(p * 20)}[/][dim]{'░' * (20 - round(p * 20))}[/] {p:.2f}"
    for k, v in a.items():
        if v["type"] == "choice":
            tbl.add_row(k, "choice", v["choice"], bar(v["confidence"]))
        elif v["type"] == "score":
            tbl.add_row(k, "score", f'{v["legend"][str(round(v["score"]))]} ({v["score"]})', bar(v["confidence"]))
        else:
            tbl.add_row(k, "noul", "yes" if v["noul"] >= 0.5 else "no", bar(v["noul"]))
    probs = Table(box=None, show_header=False, pad_edge=False)
    for k, p in sorted(a["route"]["probabilities"].items(), key=lambda x: -x[1]):
        if p > 0:
            probs.add_row(f"  [dim]route[/] {k}", bar(p))
    c.print(Panel(Group(tbl, "", probs), title="[bold magenta]◆ jev[/]", border_style="magenta", title_align="left"))
    c.print(Panel(js(llm_hint(a)), title="[bold yellow]⇢ LLM hint[/]", border_style="yellow", title_align="left"))
    u = res.get("usage", {})
    c.print(f"[dim]  {ms:.0f} ms · {u.get('input_tokens')} in / {u.get('output_tokens')} out tokens · market ${gw.get('marketCost')} · billed ${gw.get('cost')}[/]")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "-v":
        for q in args[1:] or REQUESTS[:1]:
            show(q)
        sys.exit()
    reqs = args or REQUESTS
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(ask, reqs))
    for q, (a, ms) in zip(reqs, results):
        h = llm_hint(a)
        flag = " ⚠ ask" if h["ask_user_first"] else ""
        alt = f" (alt {h['alternatives']})" if h["alternatives"] else ""
        print(f"{ms:>5.0f}ms  {q:<45} → {h['route']:<13} {h['route_confidence']:.2f}{alt} | extract={h['extract']} | mods={h['modifiers']} | {h['energy'] or '?'}{flag}")
