import io
import logging
import os
import re
import zipfile
from typing import Dict, List, Optional

import cairosvg
import fitz
from PIL import Image
from plasTeX import Base, Command, Environment
from plasTeX.Base import Caption
from plasTeX.Base import figure as base_figure
from plasTeX.Packages import graphics, graphicx

logger = logging.getLogger(__name__)


def image_to_bytes(image: Image.Image) -> bytes:
    with io.BytesIO() as output:
        image.save(output, format="PNG", compress_level=9)
        return output.getvalue()


def pack_images(image_paths: List[str], output_zip_path: str, compression=9) -> str:
    """
    Compresses a list of image paths into a ZIP file.

    Returns:
        str: Path to the created ZIP file.
    """
    with zipfile.ZipFile(
        output_zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=compression
    ) as zipf:
        for img_path in image_paths:
            if os.path.exists(img_path):
                zipf.write(img_path, os.path.basename(img_path))
            else:
                logger.error(f"File not found: {img_path}, skipping.")


def get_file_from_zip(zip_path: str, filename: str) -> Optional[bytes]:
    """Retrieves a single file from a zip archive by filename."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zipf:
            if filename in zipf.namelist():
                with zipf.open(filename) as file:
                    return file.read()
            else:
                logger.error(f"File '{filename}' not found in the ZIP archive.")
                return None
    except Exception as e:
        logger.error(f"Failed to find file '{filename}' in ZIP archive: {e}")
        return None


def process_image(
    image_data: bytes,
    format: str,
    scale: float = None,
    width: int = None,
    height: int = None,
    min_size: int = 500,
    max_size: int = 1600,
) -> bytes:
    try:
        if format == "svg":
            png_image = cairosvg.svg2png(
                bytestring=image_data,
                scale=scale,
                output_height=height,
                output_width=width,
            )
            im = Image.open(io.BytesIO(png_image))

        elif format == "pdf":
            doc = fitz.open(stream=image_data, filetype=format)
            if len(doc) > 1:
                logger.warning(
                    "PDF contains multiple pages, only the first will be used."
                )
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(1.6, 1.6))
            im = Image.open(io.BytesIO(pix.pil_tobytes(format="png")))
        else:
            im = Image.open(io.BytesIO(image_data))

        w, h = im.size
        if width is None and height is None:
            width, height = w, h
        elif width is None and height is not None:
            width = int(w * height / h)
        elif height is None and width is not None:
            height = int(h * width / w)

        if scale:
            width, height = round(width * scale), round(height * scale)

        # Constrain image to min_size
        if width < min_size and height < min_size and (w >= min_size or h >= min_size):
            if w < h:
                width = min_size
                height = int(min_size * h / w)
            else:
                height = min_size
                width = int(min_size * w / h)

        # Constrain the image to max_size
        if width > max_size or height > max_size:
            if width > height:
                width = max_size
                height = int(max_size * h / w)
            else:
                height = max_size
                width = int(max_size * w / h)

        if width > w or height > h:
            width, height = w, h
        else:
            im = im.resize((width, height), Image.LANCZOS)

        return image_to_bytes(im)

    except Exception as e:
        logger.error(f"Error processing image: {e}")
        return None


class includegraphics(Command):
    args = "* [ options:dict ] file:str"
    captionable = True
    path: List[str]
    size: List[Dict[str, float]]
    label: str

    def invoke(self, tex):
        res = Command.invoke(self, tex)

        f = self.attributes["file"]
        extensions = [
            "",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".pdf",
            ".ps",
            ".eps",
            ".svg",
        ]
        try:
            for ext in extensions:
                img = tex.kpsewhich(f + ext)
                break
        except FileNotFoundError:
            self.path = None
            self.size = None
            self.label = None
            return

        options = self.attributes["options"] or {}
        scale = float(options.get("scale", 1))
        height = self.to_pixel_size(options.get("height", None))
        width = self.to_pixel_size(options.get("width", None))

        self.path = [img]
        self.size = [{"scale": scale, "height": height, "width": width}]
        self.label = os.path.splitext(os.path.basename(img))[0]

        return res

    def to_pixel_size(self, option, dpi=96) -> int:
        "Parses a dimension string with units and returns the size in pixels."
        if option is None:
            return None

        option = getattr(option, "value", option)
        multiplier = 1.0
        if hasattr(option, "hasChildNodes") and option.hasChildNodes():
            for node in option.allChildNodes:
                if hasattr(node, "value"):
                    option = node.value
                else:
                    try:
                        multiplier *= float(node)
                    except:
                        pass

        m = re.match(r"^([\d\.]+)\s*([a-z]*)$", str(option))
        if m:
            value = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
            unit = m.group(2)

            if unit == "cm":
                value = value / 2.54 * dpi
            elif unit == "in":
                value *= dpi
            elif unit == "pt":
                value = value / 72 * dpi

            return round(value * multiplier)


class graphics_includegraphics(includegraphics):
    packageName = "graphics"
    args = "* [ ll ] [ ur ] file:str"


class figure(base_figure):
    caption: str = None
    label: str = None
    path: List[str]
    size: List[Dict[str, float]]

    def digest(self, tokens):
        res = Environment.digest(self, tokens)
        if self.macroMode == self.MODE_BEGIN:
            # Collect images and captions
            self.path = []
            self.size = []
            captions = []
            image_labels = []
            all = self.allChildNodes
            for node in all:
                if isinstance(node, includegraphics):
                    if node.path is not None:
                        self.path.extend(node.path)
                        self.size.extend(node.size)
                        image_labels.append(node.label)
                elif isinstance(node, Caption):
                    captions.append(node.source)
                elif node.nodeName == "label":
                    self.label = node.attributes["label"]

            self.caption = "\n".join(captions)
            if self.label is None:
                self.label = "_".join(image_labels)

        return res


class FigureStar(figure):
    macroName = "figure*"


# Monkey patch include graphics references
graphics.includegraphics = graphics_includegraphics
graphicx.includegraphics = includegraphics
Base.figure = figure
Base.FigureStar = FigureStar
