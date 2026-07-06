import numpy as np
import pydicom
from PIL import Image


def convert_dicom_to_png(dcm_path: str, png_path: str):
    """
    Read a DICOM file from `dcm_path`, extract its pixel array,
    normalize it to 8-bit uint8, apply photometric corrections if needed,
    and save it as a PNG to `png_path`.
    """
    dcm = pydicom.dcmread(dcm_path)
    img_array = dcm.pixel_array

    # Normalize to 8-bit
    img_array = img_array.astype(float)
    img_max = img_array.max()
    img_min = img_array.min()

    if img_max > img_min:
        img_array = ((img_array - img_min) / (img_max - img_min)) * 255.0
    else:
        img_array = img_array * 0

    img_array = np.uint8(img_array)

    # Correct for MONOCHROME1 interpretation (where 0 is white and max is black)
    if hasattr(dcm, 'PhotometricInterpretation') and dcm.PhotometricInterpretation == "MONOCHROME1":
        img_array = 255 - img_array

    img = Image.fromarray(img_array)
    img.save(png_path)
