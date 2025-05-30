import torch
import math
import torch.nn as nn
import torchvision.transforms as transforms
from PIL import Image
import numpy as np
import argparse
import os
import matplotlib.pyplot as plt
from tqdm import tqdm
from loguru import logger

WEIGHTS_PATH = {
    2: "net/FSRCNN/models/fsrcnn_x2.pth",
    3: "net/FSRCNN/models/fsrcnn_x3.pth",
    4: "net/FSRCNN/models/fsrcnn_x4.pth",
}
INPUT_NET_IMG_PATH = {
    "unet": "datasets/unet/",
    "yolo": "datasets/dataset_yolo/",
}
OUTPUT_NET_IMG_PATH = {
    "unet": "datasets/dataset_unet_sr",
    "yolo": "datasets/dataset_yolo_sr",
}

# https://github.com/yjn870/FSRCNN-pytorch
class FSRCNN:
    _instance = None
    _scale_factor = None 

    def __new__(cls, scale_factor, weights_path):
        if cls._instance is None or cls._scale_factor != scale_factor:
            cls._instance = super(FSRCNN, cls).__new__(cls)
            cls._instance.model = _FSRCNN(scale_factor).to("cuda" if torch.cuda.is_available() else "cpu")
            cls._instance.model.load_state_dict(torch.load(weights_path, map_location=torch.device("cpu")))
            cls._instance.model.eval()  
            cls._scale_factor = scale_factor 
        return cls._instance

class _FSRCNN(nn.Module):
    def __init__(self, scale_factor, num_channels=1, d=56, s=12, m=4):
        super(_FSRCNN, self).__init__()
        self.first_part = nn.Sequential(
            nn.Conv2d(num_channels, d, kernel_size=5, padding=5 // 2), nn.PReLU(d)
        )
        self.mid_part = [nn.Conv2d(d, s, kernel_size=1), nn.PReLU(s)]
        for _ in range(m):
            self.mid_part.extend(
                [nn.Conv2d(s, s, kernel_size=3, padding=3 // 2), nn.PReLU(s)]
            )
        self.mid_part.extend([nn.Conv2d(s, d, kernel_size=1), nn.PReLU(d)])
        self.mid_part = nn.Sequential(*self.mid_part)
        self.last_part = nn.ConvTranspose2d(
            d,
            num_channels,
            kernel_size=9,
            stride=scale_factor,
            padding=9 // 2,
            output_padding=scale_factor - 1,
        )
        self._initialize_weights()

    def _initialize_weights(self):
        for m in self.first_part:
            if isinstance(m, nn.Conv2d):
                nn.init.normal_(
                    m.weight.data,
                    mean=0.0,
                    std=math.sqrt(2 / (m.out_channels * m.weight.data[0][0].numel())),
                )
                nn.init.zeros_(m.bias.data)
        for m in self.mid_part:
            if isinstance(m, nn.Conv2d):
                nn.init.normal_(
                    m.weight.data,
                    mean=0.0,
                    std=math.sqrt(2 / (m.out_channels * m.weight.data[0][0].numel())),
                )
                nn.init.zeros_(m.bias.data)
        nn.init.normal_(self.last_part.weight.data, mean=0.0, std=0.001)
        nn.init.zeros_(self.last_part.bias.data)

    def forward(self, x):
        x = self.first_part(x)
        x = self.mid_part(x)
        x = self.last_part(x)
        return x

def apply_fsrcnn(img: np.ndarray, scale_factor: int) -> np.ndarray:
    """Aplica FSRCNN a una imagen."""
    fsrcnn = FSRCNN(scale_factor, WEIGHTS_PATH[scale_factor]).model

    img_tensor = torch.from_numpy(img).float().unsqueeze(0).unsqueeze(0).to("cuda" if torch.cuda.is_available() else "cpu")
    img_tensor = img_tensor / img_tensor.max()

    with torch.no_grad():
        sr_tensor = fsrcnn(img_tensor)

    sr_img = sr_tensor.squeeze(0).squeeze(0).cpu().numpy()
    sr_img = np.clip(sr_img, 0, 1) * 255
    sr_img = sr_img.astype(np.uint8)

    return sr_img

def super_resolve_image(image_path, model):
    image = Image.open(image_path).convert("L")

    transform = transforms.Compose([transforms.ToTensor()])
    image_tensor = transform(image).unsqueeze(0)

    model.eval()
    with torch.no_grad():
        output_tensor = model(image_tensor)

    output_image = output_tensor.squeeze(0).squeeze(0).cpu().numpy()
    output_image = np.clip(output_image, 0, 1)
    output_image = (output_image * 255).astype(np.uint8)

    plt.figure(figsize=(10, 5))
    plt.subplot(1, 2, 1)
    plt.title("Imagen Original")
    plt.imshow(image, cmap="gray")
    plt.axis("off")

    plt.subplot(1, 2, 2)
    plt.title("Imagen Mejorada")
    plt.imshow(output_image, cmap="gray")
    plt.axis("off")

    plt.show()

def super_resolve_image_dir(image_path, model, dst_path):
    image = Image.open(image_path).convert("L")
    transform = transforms.Compose([transforms.ToTensor()])
    image_tensor = transform(image).unsqueeze(0)
    model.eval()
    with torch.no_grad():
        output_tensor = model(image_tensor)
    output_image = output_tensor.squeeze(0).squeeze(0).cpu().numpy()
    output_image = np.clip(output_image, 0, 1)
    output_image = (output_image * 255).astype(np.uint8)
    output_pil = Image.fromarray(output_image)
    output_pil.save(dst_path)


def process_dataset(input_dir, output_dir, model):
    image_files = []
    for root, _, files in os.walk(input_dir):
        for file in files:
            if file.endswith(".png"):
                image_files.append(os.path.join(root, file))

    for image_path in tqdm(image_files, desc="Processing Images", unit="image"):
        relative_path = os.path.relpath(image_path, input_dir)
        output_file_path = os.path.join(output_dir, relative_path)
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
        super_resolve_image_dir(image_path, model, output_file_path)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FSRCNN")
    parser.add_argument(
        "--net",
        type=str,
        default="unet",
        choices=["unet", "yolo"],
        help="Format of the dataset to process",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=3,
        choices=[2, 3, 4],
        help="Super resolution scale factor",
    )
    args = parser.parse_args()

    if not os.path.exists(WEIGHTS_PATH[args.scale]):
        raise FileNotFoundError(f"Model weights not found at '{args.scale}'")

    logger.info(f"Scaling images by factor of {args.scale}x")

    # fsrcnn_model = load_fsrcnn_model(args.scale)
    fsrcnn_model = _FSRCNN(scale_factor=args.scale)
    fsrcnn_model.load_state_dict(
        torch.load(WEIGHTS_PATH[args.scale], map_location=torch.device("cpu"))
    )

    process_dataset(
        INPUT_NET_IMG_PATH[args.net],
        f"{OUTPUT_NET_IMG_PATH[args.net]}_x{args.scale}",
        fsrcnn_model,
    )
