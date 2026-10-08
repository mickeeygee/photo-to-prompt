"""Small ComfyUI client: load an API-format workflow, put a prompt (and a random seed) into it, run it, and get
the images back. No dependencies beyond the standard library. Used by watch.py and setup.py."""
import copy, json, random, time, urllib.error, urllib.parse, urllib.request

TEXT_KEYS = ("text", "prompt", "value", "string", "string_a")
SEED_KEYS = ("seed", "noise_seed")


def _json(url, payload=None, timeout=30):
    req = urllib.request.Request(url, json.dumps(payload).encode() if payload is not None else None,
                                 {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def is_up(base):
    try:
        _json(base.rstrip("/") + "/system_stats", timeout=5)
        return True
    except Exception:
        return False


def free_memory(base):
    """Ask ComfyUI to unload its models so another program (LM Studio) can use the GPU."""
    try:
        _json(base.rstrip("/") + "/free", {"unload_models": True, "free_memory": True}, 30)
    except Exception:
        pass


def load_workflow(path):
    """Read an API-format workflow ({node_id: {class_type, inputs}}). Raises ValueError with a helpful message."""
    try:
        with open(path, encoding="utf-8") as fh: wf = json.load(fh)
    except (OSError, ValueError) as e:
        raise ValueError(f"Cannot read {path}: {e}")
    if isinstance(wf, dict) and "nodes" in wf and "links" in wf:
        raise ValueError("That is a normal workflow save, not an API export. In ComfyUI use the Workflow menu > "
                         "Export (API) (turn on 'Dev mode options' in Settings if you don't see it).")
    if not isinstance(wf, dict) or not wf or not all(isinstance(v, dict) and "class_type" in v for v in wf.values()):
        raise ValueError("That file is not an API-format ComfyUI workflow.")
    return wf


def _is_link(v):
    return isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)


def _text_link_key(k):
    return k in TEXT_KEYS or k.startswith("string") or "conditioning" in k.lower()


def _trace_text(wf, nid, seen):
    """Follow links back from a sampler's positive input (through conditioning, string-concatenate nodes and
    so on) until a node with a literal text field is found. Links are followed first, so a prompt box feeding
    a concatenate node is found rather than the concatenate node's own suffix text."""
    if nid in seen or nid not in wf: return None
    seen.add(nid)
    inputs = wf[nid]["inputs"]
    for k, v in inputs.items():
        if _is_link(v) and _text_link_key(k):
            hit = _trace_text(wf, v[0], seen)
            if hit: return hit
    for k in TEXT_KEYS:
        if isinstance(inputs.get(k), str): return (nid, k)
    return None


def find_prompt_nodes(wf):
    """Return (guess, candidates). guess = (node_id, input) of the positive prompt, wired into a sampler's
    'positive' input, or None. candidates = every (node_id, input, class_type, current_text) with a text field."""
    cands = [(nid, k, n["class_type"], n["inputs"][k]) for nid, n in wf.items()
             for k in TEXT_KEYS if isinstance(n["inputs"].get(k), str)]
    for n in wf.values():
        pos = n["inputs"].get("positive")
        if _is_link(pos):
            hit = _trace_text(wf, pos[0], set())
            if hit: return hit, cands
    return None, cands


def find_seed_inputs(wf):
    """Every literal seed input in the workflow, as [node_id, input] pairs."""
    return [[nid, k] for nid, n in wf.items() for k in SEED_KEYS if isinstance(n["inputs"].get(k), int)]


def _error_text(e):
    try: body = json.loads(e.read().decode())
    except Exception: return str(e)
    msgs = []
    err = body.get("error") or {}
    if err: msgs.append(f"{err.get('message', '')} {err.get('details', '')}")
    for nid, ne in (body.get("node_errors") or {}).items():
        for er in ne.get("errors", []):
            msgs.append(f"node {nid} ({ne.get('class_type')}): {er.get('message')} {er.get('details', '')}")
    return " | ".join(m.strip() for m in msgs if m.strip()) or str(body)[:300]


def run(base, wf, prompt_node, prompt_input, seed_inputs, text, seed=None, timeout=900):
    """Run the workflow once with `text` as the prompt. Returns [(filename, png_bytes), ...] for the saved images."""
    base = base.rstrip("/")
    g = copy.deepcopy(wf)
    if prompt_node not in g: raise RuntimeError(f"Node {prompt_node} is not in the workflow. Run setup again.")
    g[prompt_node]["inputs"][prompt_input] = text
    seed = random.randint(0, 2**32 - 1) if seed is None else seed
    for nid, key in seed_inputs or []:
        if nid in g: g[nid]["inputs"][key] = seed
    try:
        pid = _json(base + "/prompt", {"prompt": g}, 60)["prompt_id"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(_error_text(e))
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = _json(f"{base}/history/{pid}", timeout=30)
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error":
                raise RuntimeError(json.dumps(st.get("messages", [])[-1:])[:400])
            out = []
            for o in h[pid].get("outputs", {}).values():
                for im in o.get("images", []):
                    if im.get("type") != "output": continue      # skip previews (type 'temp')
                    q = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im.get("subfolder", ""), "type": "output"})
                    out.append((im["filename"], urllib.request.urlopen(f"{base}/view?{q}", timeout=120).read()))
            if not out: raise RuntimeError("The workflow finished but has no Save Image node, so there are no images. "
                                           "Add a Save Image node and export it again.")
            return out
        time.sleep(2)
    raise RuntimeError("timed out waiting for ComfyUI")
