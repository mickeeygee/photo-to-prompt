"""Turn reference photos into image-generation prompts for one fixed fictional character, using a local
vision model served by LM Studio.

Usage:
    python photos_to_prompts.py                  every image in your photos folder
    python photos_to_prompts.py "D:\\some\\folder"  every image in another folder
    python photos_to_prompts.py "D:\\a\\photo.jpg"  one photo (quick test; the prompt is printed at the end)

Writes  output\\batch N.txt  (prompts separated by ---, with a "# photo N | source: file" line above each).
Settings: user_settings.json (made by setup.py). Instructions to the vision model: system_prompt.txt.
Needs LM Studio's local server running with a vision model available.
"""
import base64, io, json, os, random, re, shutil, sys, time, urllib.request
from PIL import Image, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
REQUIRED = ["Scene:", "Outfit:", "Framing:", "Constraints:"]
LABEL = re.compile(r"^(Scene|Lighting|Outfit|Hair|Jewell?ery[^:]*|Body[^:]*|Phone[^:]*|Expression|Framing|Photo style|Constraints):", re.I)

def with_base(t):
    """Assemble the final prompt. The character line and the Hair line are written here, never by the model:
    it drifts on hair colour and length, and sometimes writes its own variant of the character line.
    So any leading line that is not a section label is dropped, any Hair line is replaced, and the Hair line
    (a random pick from hair_styles in user_settings.json) goes right after Outfit."""
    lines = t.strip().splitlines()
    while lines and not LABEL.match(lines[0].strip()): lines.pop(0)
    lines = [l for l in lines if not re.match(r"\s*Hair\s*:", l, re.I)]
    styles = [s for s in CFG.get("hair_styles") or [] if str(s).strip()]
    hair = "Hair: " + (random.choice(styles).strip() if styles else "exactly as described in the first line, worn naturally.")
    at = next((i + 1 for i, l in enumerate(lines) if l.lstrip().lower().startswith("outfit:")), 1)
    lines.insert(at, hair)
    return BASE + "\n" + "\n".join(lines)

DEFAULTS = {
    "character_name": "",
    "character_description": "",
    "lm_studio_url": "http://127.0.0.1:1234",
    "model": None,
    "temperature": 0.6,
    "image_max_side": 1024,
    "dashboard_port": 8765,
    "photos_folder": "photos",
    "output_folder": "output",
    "disable_thinking": True,
    # ComfyUI + watch mode (setup.py fills these in; leave comfyui_workflow empty for prompts only)
    "comfyui_url": "http://127.0.0.1:8188",
    "comfyui_workflow": "",
    "comfyui_prompt_node": "",
    "comfyui_prompt_input": "text",
    "comfyui_seed_inputs": [],
    "comfyui_timeout_s": 900,
    "images_per_photo": 1,
    "gpu_swap": True,
    "min_free_vram_mb": 6000,
    "watch_interval_s": 5,
    "hair_styles": ["worn down loose and natural", "worn down and slightly tousled", "tucked behind one ear",
                    "swept over one shoulder", "swept to one side"],
}
SETTINGS_FILE = os.path.join(HERE, "user_settings.json")

def load_config():
    """Defaults overlaid with user_settings.json (created by setup.py)."""
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh: user = json.load(fh)
    except FileNotFoundError:
        raise SystemExit("No user_settings.json yet. Run Setup.bat (or: python setup.py) first.")
    except ValueError as e:
        raise SystemExit(f"user_settings.json is not valid JSON ({e}). Fix it or run setup.py again.")
    cfg = {**DEFAULTS, **user}
    for k in ("character_name", "character_description"):
        if not str(cfg[k]).strip(): raise SystemExit(f"'{k}' is empty in user_settings.json. Run setup.py again.")
    return cfg

def resolve(path):
    """Folders in settings may be relative to this package folder or absolute."""
    return path if os.path.isabs(path) else os.path.join(HERE, path)

CFG = load_config()
PHOTOS_DIR = resolve(CFG["photos_folder"])
OUT_DIR = resolve(CFG["output_folder"])
LM = CFG["lm_studio_url"].rstrip("/")
NAME = CFG["character_name"]
BASE = CFG["character_description"]

def load_system():
    """system_prompt.txt with // comment lines removed and {NAME} / {BASE} filled in."""
    path = os.path.join(HERE, "system_prompt.txt")
    try:
        with open(path, encoding="utf-8") as fh: lines = fh.read().splitlines()
    except OSError:
        raise SystemExit(f"Missing {path}")
    txt = "\n".join(l for l in lines if not l.lstrip().startswith("//")).strip()
    if "{BASE}" not in txt: raise SystemExit("system_prompt.txt must contain {BASE} on its own line.")
    return txt.replace("{NAME}", NAME).replace("{BASE}", BASE)

def http(path, payload=None, timeout=600):
    req = urllib.request.Request(LM + path, json.dumps(payload).encode() if payload else None,
                                 {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))

def pick_model():
    if CFG.get("model"): return CFG["model"]
    try: models = http("/api/v0/models", timeout=15)["data"]
    except Exception as e:
        raise SystemExit(f"Cannot reach LM Studio at {LM} ({e}). Start its local server first.")
    for m in models:
        if m.get("type") == "vlm": return m["id"]
    raise SystemExit("No vision (vlm) model found in LM Studio. Download one and try again.")

def load_image(path):
    """Open a photo upright (EXIF rotation applied) and flatten any transparency onto white."""
    im = ImageOps.exif_transpose(Image.open(path))
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA"); bg = Image.new("RGB", im.size, "white"); bg.paste(im, mask=im.split()[3]); return bg
    return im.convert("RGB")

def data_uri(path):
    im = load_image(path); im.thumbnail((CFG.get("image_max_side", 1024),) * 2)
    b = io.BytesIO(); im.save(b, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()

SYSTEM_NOW = ""

def describe(model, path):
    """Ask the vision model; retry with a larger token budget if the answer is empty or cut off."""
    last = ""
    for budget in (3500, 9000):
        r = http("/v1/chat/completions", {
            "model": model, "temperature": CFG.get("temperature", 0.6), "max_tokens": budget,
            **({"chat_template_kwargs": {"enable_thinking": False}} if CFG.get("disable_thinking", True) else {}),
            "messages": [{"role": "system", "content": SYSTEM_NOW},
                         {"role": "user", "content": [
                             {"type": "text", "text": "Write the prompt for this photo."},
                             {"type": "image_url", "image_url": {"url": data_uri(path)}}]}]})
        txt = r["choices"][0]["message"]["content"] or ""
        txt = re.sub(r"(?s)<think>.*?</think>", "", txt).strip().strip('"')
        last = txt
        if txt.upper().rstrip(".") == "SKIP": return txt
        if txt and all(k in txt for k in REQUIRED) and len(txt) > 900: return txt
    raise RuntimeError("incomplete answer after retry (" + str(len(last)) + " chars)")

def fmt(sec):
    sec = int(max(0, sec)); h, r = divmod(sec, 3600); m, s_ = divmod(r, 60)
    return f"{h}:{m:02d}:{s_:02d}" if h else f"{m}:{s_:02d}"

STATE = {}   # extra fields the dashboard shows

def progress(done, total, t0, label, ok, skipped, failed, status_path, tty, show=True):
    frac = done / total if total else 1
    el = time.time() - t0
    eta = (el / done) * (total - done) if done else 0
    bar = "#" * int(30 * frac) + "-" * (30 - int(30 * frac))
    line = f"[{bar}] {done}/{total} {frac * 100:3.0f}% | elapsed {fmt(el)} | ETA {fmt(eta)} | ok {ok} skip {skipped} fail {failed} | {label[:38]}"
    if show:
        if tty: print("\r" + line.ljust(shutil.get_terminal_size((120, 20)).columns - 1), end="", flush=True)
        else: print(line, flush=True)
    try:
        tmp = status_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({**STATE, "done": done, "total": total, "percent": round(frac * 100, 1), "elapsed_s": int(el), "eta_s": int(eta),
                       "ok": ok, "skipped": skipped, "failed": failed, "current": label, "updated": time.strftime("%H:%M:%S")}, fh)
        os.replace(tmp, status_path)      # atomic: the dashboard never reads a half-written file
    except OSError: pass

def next_batch_number(out_dir):
    """Next free 'batch N.txt' number in the output folder."""
    nums = [int(m.group(1)) for f in os.listdir(out_dir) if (m := re.fullmatch(r"batch (\d+)\.txt", f))]
    return max(nums, default=0) + 1

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else PHOTOS_DIR
    out_dir = OUT_DIR; os.makedirs(out_dir, exist_ok=True)
    single = os.path.isfile(src)
    if single: src, only = os.path.split(os.path.abspath(src))
    elif len(sys.argv) > 1 and not os.path.isdir(src): raise SystemExit(f"Not a folder or image file: {src}")
    else: os.makedirs(src, exist_ok=True)      # only the configured default is auto-created
    files = [only] if single else sorted(f for f in os.listdir(src) if f.lower().endswith(EXTS))
    if not files: raise SystemExit(f"No images found in {src}")
    global SYSTEM_NOW
    SYSTEM_NOW = load_system()
    model = pick_model(); n = len(files); tty = sys.stdout.isatty()
    print(f"{n} images, model: {model}", flush=True)
    if single:
        tag = re.sub(r"[^A-Za-z0-9]+", "_", os.path.splitext(only)[0]).strip("_")[:40]
        out = os.path.join(out_dir, f"test {tag} {time.strftime('%H%M%S')}.txt")
    else:
        out = os.path.join(out_dir, f"batch {next_batch_number(out_dir)}.txt")
    status = os.path.join(out_dir, "_progress.json")
    STATE.update(model=model, source_dir=os.path.abspath(src), output_file=out, recent=[], last_prompt="")
    ok = skipped = failed = streak = 0; t0 = time.time(); problems = []
    progress(0, n, t0, "starting...", ok, skipped, failed, status, tty)
    with open(out, "w", encoding="utf-8") as fh:
        for i, f in enumerate(files, 1):
            STATE["current_file"] = f; STATE["current_n"] = i
            progress(i - 1, n, t0, f, ok, skipped, failed, status, tty, show=False)
            try:
                t = describe(model, os.path.join(src, f))
                is_skip = t.strip().upper().rstrip(".") == "SKIP"
                if is_skip:
                    skipped += 1; fh.write(f"# photo {i} (skipped) | source: {f}\n---\n")
                else:
                    t = with_base(t)
                    fh.write(f"# photo {i} | source: {f}\n{t}\n---\n"); fh.flush(); ok += 1
                STATE["last_prompt"] = t; streak = 0
                STATE["recent"] = (STATE["recent"] + [{"n": i, "file": f, "result": "skipped" if is_skip else "ok"}])[-12:]
            except Exception as e:
                failed += 1; streak += 1; problems.append(f"{f}: {e}")
                fh.write(f"# photo {i} (FAILED: {str(e)[:100]}) | source: {f}\n---\n"); fh.flush()
                STATE["recent"] = (STATE["recent"] + [{"n": i, "file": f, "result": "failed: " + str(e)[:80]}])[-12:]
            progress(i, n, t0, f, ok, skipped, failed, status, tty)
            if streak >= 3:
                problems.append(f"stopped after {streak} failures in a row at photo {i}: is LM Studio still running?"); break
    STATE["current_file"] = ""; STATE["finished"] = True
    progress(n, n, t0, "finished", ok, skipped, failed, status, tty, show=False)
    if tty: print()
    print(f"done in {fmt(time.time() - t0)}: {ok} prompts, {skipped} skipped, {failed} failed -> {out}")
    for p_ in problems: print("  FAILED", p_)
    if single and ok: print("\n" + STATE["last_prompt"])

if __name__ == "__main__":
    main()
