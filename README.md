# Photo → Prompt

Turns a folder of reference photos into detailed image-generation prompts for **your own fictional character**, using a local vision model in LM Studio. Everything runs on your PC. No cloud, no API keys.

> **For fictional characters only.** Use photos you have the right to use as inspiration, never recreate a real person, keep characters adult and content within your platform's rules, and don't present AI images as real photos. Label AI content when you post it.

For each photo it writes a prompt covering the scene, lighting, outfit, pose, framing and photo style. It never describes the person in the photo, and it skips anyone who looks under 18.

## Setup

1. Install Python 3.10+ from python.org (tick "Add Python to PATH").
2. Install [LM Studio](https://lmstudio.ai) and download a **vision** model (Qwen-VL, Gemma 3 and similar).
3. Double-click **Setup.bat**. The wizard:
   - installs Pillow if it's missing,
   - walks you through starting the LM Studio server (Developer tab → Status: Running) and tests the connection,
   - lists your vision models so you can pick one,
   - asks for your character's name and look line,
   - asks where the photos folder and output folder should be,
   - optionally connects ComfyUI so every photo also becomes an image (see "Auto mode" below),
   - saves everything to **user_settings.json** and offers a test on one photo.
4. Put photos in your photos folder.

`user_settings.json` is the only file you need to fill in, and the wizard writes it for you. You can also edit it by hand:

| Setting | Meaning |
|---|---|
| `character_name` | Your fictional character's name |
| `character_description` | The fixed look line that starts every prompt |
| `lm_studio_url` | LM Studio server address, default `http://127.0.0.1:1234` |
| `model` | A model id, or `null` to use the first vision model LM Studio lists |
| `photos_folder` | Where reference photos are read from (relative to this folder, or a full path) |
| `output_folder` | Where `batch N.txt` files and progress are written |
| `temperature`, `image_max_side`, `dashboard_port` | Optional tuning |
| `hair_styles` | List of hair stylings; one is picked at random for each prompt's Hair line. The hair colour and length come only from `character_description`, so list stylings, not colours (add "in a ponytail", "in a bun" if your character's hair is long enough) |
| `comfyui_workflow` | Your exported API workflow (setup copies it here as `workflow_api.json`). Empty = prompts only |
| `comfyui_url` | ComfyUI address, default `http://127.0.0.1:8188` |
| `comfyui_prompt_node`, `comfyui_prompt_input` | Which node and input receives the prompt (setup finds this for you) |
| `comfyui_seed_inputs` | Seed inputs randomised for each image (found by setup) |
| `images_per_photo` | How many images to make per photo |
| `gpu_swap` | `true` (default): unload the vision model before ComfyUI runs, and free ComfyUI's models before captioning. Turn off only if your GPU holds both at once |
| `min_free_vram_mb`, `watch_interval_s`, `comfyui_timeout_s` | Optional tuning |
| `disable_thinking` | `true` (default) asks reasoning models to skip their thinking step. Set `false` if your model rejects it |

Run Setup.bat again any time to change a setting.

## Run

Double-click `run.bat` (it starts Setup first if you haven't done it), or:

```
python photos_to_prompts.py                 # every image in your photos folder
python photos_to_prompts.py "D:\other"      # another folder
python photos_to_prompts.py "D:\pic.jpg"  # one photo, prints the prompt (good for testing)
```

Results go to `batch N.txt` in the output folder. Prompts are separated by `---`, with a `# photo N | source: file` line above each. Read and edit them before you use them.

A live dashboard (photo being processed, progress, ETA, newest prompt) opens at http://127.0.0.1:8765 when you use `run.bat`, or start it yourself with `python dashboard.py`.

## Auto mode: photo in, prompt and image out

Double-click `watch.bat` (or `python watch.py`) and leave it running. Every photo you drop into the photos folder is captioned, and if ComfyUI is connected, an image is generated from the prompt.

```
photos\pic.jpg  ->  output\prompts\pic.txt  ->  output\images\pic_1.png
```

Options: `python watch.py --once` (process what's waiting, then exit) and `python watch.py --no-image` (prompts only).

**Connecting ComfyUI.** Build a workflow in ComfyUI that makes images you like and ends in a Save Image node. Then use the Workflow menu → **Export (API)** (turn on "Dev mode options" in Settings if you don't see it) and give that file to `Setup.bat`. Setup finds the positive-prompt box on its own, even when the prompt goes through string or conditioning nodes. If it guesses wrong, it shows a numbered list so you can pick. Your workflow decides the look: your character LoRA, resolution, upscaling and so on. The tool only swaps the prompt and the seed.

**GPU memory.** With `gpu_swap` on, the work runs in two stages: all waiting photos are captioned, then the vision model is unloaded (via LM Studio's `lms` tool), then ComfyUI generates. This lets one 12 GB card run both. If `lms` isn't found, the tool tells you and you'll need to eject the model in LM Studio yourself.

**Safe to stop and restart.** Progress is saved in `output\_processed.json`. If ComfyUI is down, prompts are still saved and the images are made when it comes back. A photo that fails twice is skipped (its prompt is kept) and logged in `output\watch_log.txt`. Your photos are never moved or changed.

## Tuning

- `system_prompt.txt` holds the instructions sent with every photo. Edit it, save, and the next run uses it. `{NAME}` and `{BASE}` are filled in from `user_settings.json`. The Hair line is not written by the model: the script adds it from `hair_styles`, because small vision models drift on hair colour and length.
- If answers get cut off, the script retries once with a bigger token budget. Anything still incomplete is logged as failed and the run continues.
- Don't run it while ComfyUI or a game is using the GPU. Both want the VRAM.

## Rules of use

Only use photos you have the right to use as inspiration. Don't recreate a real person. Keep characters adult and content within the rules of the platform you post on, and label AI-generated content when you post it.


