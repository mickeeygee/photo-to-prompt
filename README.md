# Photo → Prompt

Turns a folder of reference photos into detailed image-generation prompts for **your own fictional character**, using a local vision model in LM Studio. Everything runs on your PC. No cloud, no API keys.

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

## Tuning

- `system_prompt.txt` holds the instructions sent with every photo. Edit it, save, and the next run uses it. `{NAME}` and `{BASE}` are filled in from `user_settings.json`. The Hair line is not written by the model: the script adds it from `hair_styles`, because small vision models drift on hair colour and length.
- If answers get cut off, the script retries once with a bigger token budget. Anything still incomplete is logged as failed and the run continues.
- Don't run it while ComfyUI or a game is using the GPU. Both want the VRAM.

## Rules of use

Only use photos you have the right to use as inspiration. Don't recreate a real person. Keep characters adult and content within the rules of the platform you post on, and label AI-generated content when you post it.


