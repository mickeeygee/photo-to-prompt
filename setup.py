"""Setup wizard for Photo -> Prompt. Run it once (Setup.bat), and again whenever you want to change something.

It checks Python and Pillow, helps you start the LM Studio server, tests the connection, lets you pick the vision
model, asks for your character and your folders, and saves everything to user_settings.json (the only file you
need to fill in; you can also edit it by hand later).
"""
import json, os, shutil, subprocess, sys, urllib.request

import comfy

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(HERE, "user_settings.json")
DEFAULT_URL = "http://127.0.0.1:1234"

def say(txt=""): print(txt, flush=True)

def ask(question, default=None):
    suffix = f" [{default}]" if default not in (None, "") else ""
    while True:
        ans = input(f"{question}{suffix}: ").strip()
        if ans: return ans
        if default not in (None, ""): return default

def yes(question, default=True):
    ans = input(f"{question} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not ans else ans.startswith("y")

def step(n, title):
    say(); say(f"=== Step {n}: {title} ===")

def load_existing():
    try:
        with open(SETTINGS, encoding="utf-8") as fh: return json.load(fh)
    except (OSError, ValueError): return {}

def http_json(url, timeout=10):
    return json.load(urllib.request.urlopen(url, timeout=timeout))

def check_python():
    step(1, "Python and Pillow")
    if sys.version_info < (3, 10):
        raise SystemExit(f"Python 3.10+ is required (you have {sys.version.split()[0]}). Install it from python.org and run setup again.")
    say(f"Python {sys.version.split()[0]} OK.")
    try:
        import PIL
        say(f"Pillow {PIL.__version__} OK.")
    except ImportError:
        say("Pillow (the image library) is not installed.")
        if yes("Install it now with pip?"):
            if subprocess.call([sys.executable, "-m", "pip", "install", "-r", os.path.join(HERE, "requirements.txt")]) != 0:
                raise SystemExit("pip failed. Run: pip install pillow   then run setup again.")
        else:
            raise SystemExit("Pillow is required. Run: pip install pillow   then run setup again.")

def lm_studio(existing):
    step(2, "LM Studio server")
    say("""This tool talks to a vision model running in LM Studio (free, https://lmstudio.ai).
Do these in LM Studio now:
  1. Download a VISION model (Search tab: look for models with the eye icon, e.g. Qwen-VL or Gemma 3).
  2. Open the Developer tab (the green >_ icon on the left).
  3. Switch "Status" to Running (Start Server). Note the address next to it,
     usually http://127.0.0.1:1234 . Port 1234 is the default.
  4. You can leave the model unloaded: LM Studio loads it on the first request.
""")
    url = ask("Server address", existing.get("lm_studio_url", DEFAULT_URL)).rstrip("/")
    if not url.startswith("http"): url = "http://" + url
    while True:
        try:
            data = http_json(url + "/api/v0/models")["data"]
            break
        except Exception as e:
            say(f"\nCould not reach LM Studio at {url} ({e}).")
            say("Check that the server is Running in the Developer tab and the address/port match.")
            if not yes("Try again?"):
                say("Saving the address anyway; the model will be chosen automatically when you run it.")
                return url, existing.get("model")
            url = ask("Server address", url).rstrip("/")
    vlms = [m["id"] for m in data if m.get("type") == "vlm"]
    say(f"Connected. {len(data)} model(s) found, {len(vlms)} with vision.")
    if not vlms:
        say("No vision model is downloaded yet. Download one in LM Studio, then run setup again.")
        return url, None
    say("Vision models:")
    for i, m in enumerate(vlms, 1): say(f"  {i}. {m}")
    say("  0. Pick automatically each run (the first vision model LM Studio lists)")
    default = (vlms.index(existing["model"]) + 1) if existing.get("model") in vlms else 0
    while True:
        c = ask("Which one", str(default))
        if c.isdigit() and 0 <= int(c) <= len(vlms): break
        say("Enter one of the numbers above.")
    return url, (None if c == "0" else vlms[int(c) - 1])

def character(existing):
    step(3, "Your character")
    say("""The tool writes prompts for ONE fixed fictional character who replaces whoever is in each photo.
The description line starts every prompt, so use the same wording you used for your LoRA / trigger word.
Example: mia, a young woman with short black hair and freckles, athletic build.
It must describe an adult, and never a real person.
""")
    name = ask("Character name", existing.get("character_name") or None)
    desc = ask("Description line", existing.get("character_description") or None)
    return name, desc

def folders(existing):
    step(4, "Folders")
    say("""Where do you want things? Press Enter to keep the defaults (inside this folder).
  Photos folder : the reference photos to read go here (jpg, png, webp, bmp).
  Output folder : prompt files are written here as 'batch 1.txt', 'batch 2.txt', and so on.
You can type a full path like D:\\MyPhotos, or a name relative to this folder.
""")
    out = {}
    for key, label, default in (("photos_folder", "Photos folder", "photos"), ("output_folder", "Output folder", "output")):
        val = ask(label, existing.get(key, default)).strip('"')
        full = val if os.path.isabs(val) else os.path.join(HERE, val)
        try: os.makedirs(full, exist_ok=True)
        except OSError as e: raise SystemExit(f"Cannot create {full}: {e}")
        say(f"  -> {full}")
        out[key] = val
    return out

def comfy_step(existing):
    step(5, "ComfyUI (optional): make the images automatically")
    say("""If you want each photo to turn into an image as well as a prompt, this tool can send the prompt to ComfyUI.
You need ComfyUI running and a workflow that already makes images you like. Export it once:
  1. In ComfyUI open your workflow and make sure it ends in a Save Image node.
  2. Settings -> turn on "Dev mode options" (if you don't see an Export (API) item later).
  3. Workflow menu -> Export (API). Save the .json file somewhere you can find it.
Skip this step to only get prompts; you can run Setup.bat again later.
""")
    if not yes("Connect ComfyUI?", bool(existing.get("comfyui_workflow"))):
        return {"comfyui_workflow": ""}
    url = ask("ComfyUI address", existing.get("comfyui_url", "http://127.0.0.1:8188")).rstrip("/")
    if not url.startswith("http"): url = "http://" + url
    if comfy.is_up(url): say("  Connected to ComfyUI.")
    else: say("  ComfyUI is not answering there right now. That's fine for setup, but start it before watching.")
    while True:
        path = ask("Full path to the exported API workflow (.json)", None).strip('"')
        try: wf = comfy.load_workflow(path); break
        except ValueError as e:
            say(f"  {e}")
            if not yes("Try another file?"): return {"comfyui_workflow": ""}
    guess, cands = comfy.find_prompt_nodes(wf)
    chosen = None
    if guess:
        nid, key = guess
        say(f"  Found the positive prompt: node {nid} ({wf[nid]['class_type']}), input '{key}', currently:")
        say(f"    \"{str(wf[nid]['inputs'][key])[:100]}\"")
        if yes("  Is that the box your prompts should go into?"): chosen = (nid, key)
    if not chosen:
        if not cands: say("  No text inputs found in that workflow."); return {"comfyui_workflow": ""}
        say("  Text inputs in this workflow:")
        for i, (nid, key, cls, txt) in enumerate(cands, 1): say(f"    {i}. node {nid} ({cls}) {key}: \"{str(txt)[:70]}\"")
        while True:
            c = ask("  Which number is the positive prompt (not the negative)", "1")
            if c.isdigit() and 1 <= int(c) <= len(cands): break
            say("  Enter one of the numbers above.")
        chosen = (cands[int(c) - 1][0], cands[int(c) - 1][1])
    seeds = comfy.find_seed_inputs(wf)
    say(f"  Seeds: {len(seeds)} seed input(s) will be randomised for every image." if seeds
        else "  No seed input found; ComfyUI's own randomisation (if any) is used.")
    n = ask("How many images per photo", str(existing.get("images_per_photo", 1)))
    swap = yes("Does your GPU struggle to hold the vision model and ComfyUI at the same time (12 GB or less)?\n"
               "  If yes, the vision model is unloaded before ComfyUI runs (recommended for most PCs)", existing.get("gpu_swap", True))
    dest = os.path.join(HERE, "workflow_api.json")      # keep a copy next to the tool so the path never breaks
    shutil.copyfile(path, dest)
    say(f"  Copied your workflow to {dest}")
    return {"comfyui_url": url, "comfyui_workflow": "workflow_api.json", "comfyui_prompt_node": chosen[0],
            "comfyui_prompt_input": chosen[1], "comfyui_seed_inputs": seeds,
            "images_per_photo": int(n) if n.isdigit() and int(n) > 0 else 1, "gpu_swap": swap}

def save(cfg):
    with open(SETTINGS, "w", encoding="utf-8") as fh: json.dump(cfg, fh, indent=2)
    say(f"\nSaved {SETTINGS}")

def first_run(cfg):
    step(6, "Test")
    photos = cfg["photos_folder"] if os.path.isabs(cfg["photos_folder"]) else os.path.join(HERE, cfg["photos_folder"])
    imgs = sorted(f for f in os.listdir(photos) if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")))
    if not imgs:
        say(f"No photos in {photos} yet. Drop a few in, then run Run.bat.")
        return
    if yes(f"Run a quick test on '{imgs[0]}' now? (LM Studio will load the model; this can take a minute)"):
        subprocess.call([sys.executable, os.path.join(HERE, "photos_to_prompts.py"), os.path.join(photos, imgs[0])])

def main():
    say("Photo -> Prompt setup")
    say("Press Enter to accept the value in [brackets]. Ctrl+C quits without saving.")
    existing = load_existing()
    check_python()
    url, model = lm_studio(existing)
    name, desc = character(existing)
    cfg = {**existing, "lm_studio_url": url, "model": model, "character_name": name,
           "character_description": desc, **folders(existing), **comfy_step(existing)}
    cfg.setdefault("temperature", 0.6); cfg.setdefault("image_max_side", 1024); cfg.setdefault("dashboard_port", 8765)
    save(cfg)
    first_run(cfg)
    say("\nAll set.")
    say("  run.bat   : turn a folder of photos into one prompt file")
    say("  watch.bat : keep running; every photo you drop in becomes a prompt" + (" and an image" if cfg.get("comfyui_workflow") else ""))
    say("Run Setup.bat again any time to change a setting.")

if __name__ == "__main__":
    try: main()
    except (KeyboardInterrupt, EOFError):
        say("\nSetup cancelled, nothing saved."); sys.exit(1)
