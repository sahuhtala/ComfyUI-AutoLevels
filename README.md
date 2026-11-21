# Auto Levels for ComfyUI

Automatically set the black and white points of an image. Use **Auto Levels** to stretch each RGB channel independently, or turn on **Luminance only** to increase contrast while keeping the image's hues.

## Installation

With Git installed, open a terminal in your ComfyUI `custom_nodes` folder and run this command.

```bash
git clone https://github.com/sahuhtala/ComfyUI-AutoLevels.git
```

If you previously put a standalone `auto_levels.py` directly in `custom_nodes`, move that copy out of the folder before restarting so ComfyUI loads the node once.

Restart ComfyUI and search for **Auto Levels** in the node menu under **image → adjustments**. The node uses the PyTorch that comes with ComfyUI.

## Usage

Connect **Load Image → Auto Levels → Preview Image** to try it. Use **Save Image** to save the result, or connect the output to the next image node in your workflow.

| Control | Default | What it does |
| --- | --- | --- |
| **image** | Required | Takes an RGB `IMAGE`. Each image in a batch is processed independently. |
| **strength** | `1.00` | Blends the original and corrected images. `0.00` passes the original through, `0.50` mixes them equally, and `1.00` applies the full correction. |
| **Luminance only** | Off | **Off** adjusts red, green, and blue independently and can change the color balance. **On** adjusts perceptual lightness and keeps the original hues. |

The output is an RGB `IMAGE` with the same dimensions and batch size as the input.

## How it works

The node chooses black and white points from the lowest and highest **0.1%** of values, rounded up to whole pixels. It clips values at the endpoints and stretches the values in between linearly. When the black and white points coincide, that channel keeps its original values.

- **Per-channel RGB** calculates separate endpoints for red, green, and blue. This follows the per-channel approach of Photoshop's Auto Tone and can reduce or introduce a color cast. [Adobe Auto Tone documentation](https://helpx.adobe.com/photoshop/desktop/adjust-color/color-corrections/apply-auto-tone-auto-contrast-and-auto-color.html)
- **Luminance only** treats the input as sRGB and applies the stretch to the OKLab lightness channel. It preserves hue and reduces chroma where needed to fit the result into sRGB. The lightest and darkest clipped values become white and black. [OKLab reference](https://bottosson.github.io/posts/oklab/)
