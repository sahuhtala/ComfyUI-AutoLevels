import torch


def stretch_levels(values: torch.Tensor, minimum_span: float = 0.0) -> torch.Tensor:
    # Flatten the spatial axes so each image and channel gets its own levels.
    pixels = values.flatten(1, 2)
    pixel_count = pixels.shape[1]
    # Round 0.1% up to a whole pixel. kthvalue uses one-based ranks.
    tail_count = (pixel_count + 999) // 1000

    # Compute order statistics on CPU when using Apple's MPS backend.
    samples = pixels.cpu() if pixels.device.type == "mps" else pixels
    black = samples.kthvalue(tail_count, dim=1, keepdim=True).values
    white = samples.kthvalue(pixel_count - tail_count + 1, dim=1, keepdim=True).values
    black = black.unsqueeze(2).to(values.device)
    white = white.unsqueeze(2).to(values.device)

    span = white - black
    has_range = span > minimum_span
    # Preserve channels without a usable range between black and white.
    safe_span = torch.where(has_range, span, 1.0)
    stretched = ((values - black) / safe_span).clamp_(0.0, 1.0)
    return torch.where(has_range, stretched, values)


def srgb_to_oklab(srgb: torch.Tensor) -> torch.Tensor:
    # Oklab conversion matrices from https://bottosson.github.io/posts/oklab/.
    rgb_to_lms = srgb.new_tensor([
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ])
    lms_to_oklab = srgb.new_tensor([
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ])
    linear_rgb = torch.where(
        srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055).pow(2.4)
    )
    lms_root = (linear_rgb @ rgb_to_lms.T).clamp_min_(0.0).pow_(1.0 / 3.0)
    return lms_root @ lms_to_oklab.T


def oklab_to_srgb(lightness: torch.Tensor, chroma: torch.Tensor) -> torch.Tensor:
    chroma_to_lms = chroma.new_tensor([
        [0.3963377774, 0.2158037573],
        [-0.1055613458, -0.0638541728],
        [-0.0894841775, -1.2914855480],
    ])
    lms_to_rgb = chroma.new_tensor([
        [4.0767416621, -3.3077115913, 0.2309699292],
        [-1.2684380046, 2.6097574011, -0.3413193965],
        [-0.0041960863, -0.7034186147, 1.7076147010],
    ])
    # The inverse transform adds L equally to each LMS component before cubing.
    chroma_lms = chroma @ chroma_to_lms.T
    linear_rgb = (lightness + chroma_lms).pow(3) @ lms_to_rgb.T

    interior = ((lightness > 0.0) & (lightness < 1.0)).squeeze(-1)
    outside_gamut = ((linear_rgb < 0.0) | (linear_rgb > 1.0)).any(dim=-1)
    needs_mapping = interior & outside_gamut
    if needs_mapping.any():
        target_lightness = lightness[needs_mapping]
        chroma_offsets = chroma_lms[needs_mapping]
        low = torch.zeros_like(target_lightness)
        high = torch.ones_like(target_lightness)
        # Scale both chroma components together to keep the hue angle constant.
        for _ in range(12):
            scale = (low + high) * 0.5
            candidate = (target_lightness + scale * chroma_offsets).pow(3) @ lms_to_rgb.T
            in_gamut = ((candidate >= 0.0) & (candidate <= 1.0)).all(dim=-1, keepdim=True)
            low = torch.where(in_gamut, scale, low)
            high = torch.where(in_gamut, high, scale)
        linear_rgb[needs_mapping] = (target_lightness + low * chroma_offsets).pow(3) @ lms_to_rgb.T

    linear_rgb.clamp_(0.0, 1.0)
    srgb = torch.where(
        linear_rgb <= 0.0031308, 12.92 * linear_rgb, 1.055 * linear_rgb.pow(1.0 / 2.4) - 0.055
    )
    # The sRGB gamut contains only black at L=0 and white at L=1.
    return torch.where(interior.unsqueeze(-1), srgb, lightness)


def stretch_lightness(image: torch.Tensor) -> torch.Tensor:
    # Use at least float32 for color conversion and gamut tests.
    srgb = image if image.dtype == torch.float64 else image.float()
    oklab = srgb_to_oklab(srgb)
    lightness = oklab[..., :1]
    # Conversion roundoff can give a solid color a tiny apparent lightness range.
    adjusted_lightness = stretch_levels(lightness, minimum_span=4 * torch.finfo(srgb.dtype).eps)
    adjusted = oklab_to_srgb(adjusted_lightness, oklab[..., 1:])
    return torch.where(adjusted_lightness == lightness, image, adjusted.to(image.dtype))


class AutoLevels:
    CATEGORY = "image/adjustments"
    DESCRIPTION = "Stretch RGB channels or perceptual lightness, then blend with the input."
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "apply"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "strength": (
                    "FLOAT",
                    {
                        "default": 1.0,
                        "min": 0.0,
                        "max": 1.0,
                        "step": 0.01,
                        "tooltip": "0 keeps the original. 1 applies full Auto Levels.",
                    },
                ),
            },
            "optional": {
                "luminance_only": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "display_name": "Luminance only",
                        "tooltip": "Adjust perceptual lightness while preserving hue and keeping as much chroma as sRGB allows.",
                    },
                ),
            },
        }

    def apply(self, image: torch.Tensor, strength: float = 1.0, luminance_only: bool = False):
        if strength == 0.0 or image.numel() == 0:
            return (image,)

        adjusted = stretch_lightness(image) if luminance_only else stretch_levels(image)
        if strength == 1.0:
            return (adjusted,)
        return (image.lerp(adjusted, strength),)


NODE_CLASS_MAPPINGS = {"AutoLevelsRGB": AutoLevels}
NODE_DISPLAY_NAME_MAPPINGS = {"AutoLevelsRGB": "Auto Levels"}
