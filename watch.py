"""Watch the photos folder: every new photo becomes a prompt, and (if ComfyUI is set up) an image.

    python watch.py             keep running; drop photos into the photos folder (Ctrl+C to stop)
    python watch.py --once      process what is waiting, then exit
    python watch.py --no-image  only write prompts, even if ComfyUI is set up

Per photo it writes  <output>\\prompts\\<photo>.txt  and  <output>\\images\\<photo>_1.png ...
Photos are never moved or changed. What has been done is remembered in <output>\\_processed.json, so a restart
does not redo anything.

With gpu_swap on (the default) the work runs in two stages so a single GPU can hold one model at a time:
all waiting photos are captioned, then the vision model is unloaded, then ComfyUI generates the images.
"""
import json, os, random, shutil, subprocess, sys, time
from pathlib import Path

import comfy
import photos_to_prompts as p

CFG = p.CFG
OUT = p.OUT_DIR
PROMPTS_DIR, IMAGES_DIR = os.path.join(OUT, "prompts"), os.path.join(OUT, "images")
STATE_FILE = os.path.join(OUT, "_processed.json")
LOG_FILE = os.path.join(OUT, "watch_log.txt")
COMFY_URL = CFG["comfyui_url"].rstrip("/")
WORKFLOW = p.resolve(CFG["comfyui_workflow"]) if CFG.get("comfyui_workflow") else None
MAX_TRIES = 2


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh: fh.write(time.strftime("%Y-%m-%d ") + line + "\n")
    except OSError: pass


# ------------------------------------------------------------------------------------------------ state
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as fh: return json.load(fh)
    except (OSError, ValueError): return {}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh: json.dump(state, fh, indent=1)
    os.replace(tmp, STATE_FILE)


def key_of(path):
    st = os.stat(path)
    return f"{os.path.basename(path)}|{st.st_size}|{st.st_mtime_ns}"


def stem_of(path):
    return os.path.splitext(os.path.basename(path))[0]


# ------------------------------------------------------------------------------------------------ GPU swap
def gpu_free_mb():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
        used, total = (int(x) for x in out.split(","))
        return total - used
    except Exception:
        return None


def find_lms():
    found = shutil.which("lms")
    if found: return found
    for cand in (Path.home() / ".lmstudio" / "bin" / "lms.exe", Path.home() / ".lmstudio" / "bin" / "lms"):
        if cand.exists(): return str(cand)
    return None


def unload_vision_model():
    lms = find_lms()
    if not lms:
        log("[!] LM Studio's 'lms' tool was not found, so I can't unload the vision model automatically. "
            "If ComfyUI runs out of memory, eject the model in LM Studio (or turn gpu_swap off).")
        return
    try:
        subprocess.run([lms, "unload", "--all"], capture_output=True, text=True, timeout=120)
        log("Vision model unloaded, GPU is free for ComfyUI.")
    except Exception as e:
        log(f"[!] Could not unload the vision model: {e}")
    time.sleep(2)


def make_room_for_vision():
    """ComfyUI keeps its models in memory after a job; release them before LM Studio loads the vision model."""
    free = gpu_free_mb()
    if free is not None and free < CFG["min_free_vram_mb"] and comfy.is_up(COMFY_URL):
        log(f"Only {free} MB of GPU memory free, asking ComfyUI to release its models...")
        comfy.free_memory(COMFY_URL); time.sleep(4)


# ------------------------------------------------------------------------------------------------ stages
def scan(seen_sizes, trust):
    """Photos in the folder that are not done yet and whose size has stopped changing (so still-copying files wait)."""
    ready = []
    for f in sorted(os.listdir(p.PHOTOS_DIR)):
        if not f.lower().endswith(p.EXTS): continue
        path = os.path.join(p.PHOTOS_DIR, f)
        try: size = os.path.getsize(path)
        except OSError: continue
        if size and (trust or seen_sizes.get(path) == size): ready.append(path)
        seen_sizes[path] = size
    return ready


def caption_stage(paths, state, tries):
    todo = [x for x in paths if key_of(x) not in state]
    if not todo: return
    if CFG["gpu_swap"]: make_room_for_vision()
    p.SYSTEM_NOW = p.load_system()
    model = p.pick_model()
    os.makedirs(PROMPTS_DIR, exist_ok=True)
    streak = 0
    for path in todo:
        k, name = key_of(path), os.path.basename(path)
        log(f"Captioning {name} ...")
        try:
            t = p.describe(model, path)
            streak = 0
            if t.strip().upper().rstrip(".") == "SKIP":
                state[k] = "skipped"; log(f"  skipped {name} (the model flagged the photo)")
            else:
                with open(os.path.join(PROMPTS_DIR, stem_of(path) + ".txt"), "w", encoding="utf-8") as fh:
                    fh.write(p.with_base(t) + "\n")
                state[k] = "prompted"; log(f"  prompt saved -> prompts\\{stem_of(path)}.txt")
        except Exception as e:
            streak += 1; tries[k] = tries.get(k, 0) + 1
            log(f"  FAILED {name}: {e}")
            if tries[k] >= MAX_TRIES: state[k] = "failed"; log(f"  giving up on {name} after {MAX_TRIES} tries")
            if streak >= 3:
                log("  3 failures in a row: is LM Studio still running? Will try again shortly."); break
        save_state(state)


_comfy_warned = [0.0]


def generate_stage(paths, state, tries, wf, prompt_node, prompt_input, seed_inputs):
    todo = [x for x in paths if state.get(key_of(x)) == "prompted"]
    if not todo: return
    if not comfy.is_up(COMFY_URL):
        if time.time() - _comfy_warned[0] > 60:
            log(f"{len(todo)} prompt(s) waiting, but ComfyUI is not answering at {COMFY_URL}. Start it and they will run."); _comfy_warned[0] = time.time()
        return
    if CFG["gpu_swap"]: unload_vision_model()
    os.makedirs(IMAGES_DIR, exist_ok=True)
    for path in todo:
        k, stem = key_of(path), stem_of(path)
        try:
            with open(os.path.join(PROMPTS_DIR, stem + ".txt"), encoding="utf-8") as fh: text = fh.read().strip()
            n = 0
            for _ in range(int(CFG["images_per_photo"])):
                log(f"Generating image for {stem} ...")
                t0 = time.time()
                for fname, data in comfy.run(COMFY_URL, wf, prompt_node, prompt_input, seed_inputs, text,
                                             timeout=int(CFG["comfyui_timeout_s"])):
                    n += 1
                    ext = os.path.splitext(fname)[1] or ".png"
                    dest = os.path.join(IMAGES_DIR, f"{stem}_{n}{ext}")
                    with open(dest, "wb") as fh: fh.write(data)
                    log(f"  saved images\\{os.path.basename(dest)} ({time.time() - t0:.0f}s)")
            state[k] = "done"
        except Exception as e:
            tries[k] = tries.get(k, 0) + 1
            log(f"  FAILED image for {stem}: {e}")
            if tries[k] >= MAX_TRIES: state[k] = "failed"; log(f"  giving up on {stem} after {MAX_TRIES} tries (the prompt is still saved)")
        save_state(state)


def main():
    once, no_image = "--once" in sys.argv, "--no-image" in sys.argv
    os.makedirs(p.PHOTOS_DIR, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    wf = prompt_node = prompt_input = seed_inputs = None
    if WORKFLOW and not no_image:
        try: wf = comfy.load_workflow(WORKFLOW)
        except ValueError as e: raise SystemExit(f"ComfyUI workflow problem: {e}\nRun setup.py again.")
        prompt_node, prompt_input = str(CFG["comfyui_prompt_node"]), CFG["comfyui_prompt_input"]
        seed_inputs = CFG["comfyui_seed_inputs"]
        if prompt_node not in wf: raise SystemExit("The saved prompt node is not in the workflow. Run setup.py again.")
        log(f"ComfyUI images: ON ({COMFY_URL}, workflow {os.path.basename(WORKFLOW)}, {CFG['images_per_photo']} per photo)")
    else:
        log("ComfyUI images: OFF (prompts only). Run setup.py to connect ComfyUI." if not no_image else "ComfyUI images: OFF (--no-image)")
    log(f"Watching {p.PHOTOS_DIR}  (Ctrl+C to stop)" if not once else f"Processing {p.PHOTOS_DIR}")
    state, tries, sizes = load_state(), {}, {}
    if once: scan(sizes, trust=False); time.sleep(2)       # first look only records sizes
    def waiting(paths):
        # with no ComfyUI, a photo is finished once its prompt exists
        return [x for x in paths if state.get(key_of(x)) in ((None, "prompted") if wf else (None,))]

    cycles = 0
    try:
        while True:
            paths = scan(sizes, trust=False)
            if waiting(paths):
                cycles += 1
                try:
                    caption_stage(paths, state, tries)
                    if wf: generate_stage(paths, state, tries, wf, prompt_node, prompt_input, seed_inputs)
                except SystemExit as e:
                    log(f"[!] {e}")
                except Exception as e:
                    log(f"[!] {type(e).__name__}: {e}")
            if once and (not waiting(paths) or cycles > MAX_TRIES): break     # a few retry rounds, then stop
            time.sleep(float(CFG["watch_interval_s"]))
    except KeyboardInterrupt:
        log("Stopped.")
    done = sum(1 for v in state.values() if v == "done")
    log(f"Finished. {done} photo(s) fully done in total, see {OUT}")


if __name__ == "__main__":
    main()
