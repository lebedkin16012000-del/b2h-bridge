"""Fast image reads for diagnostics, without Python loops over pixels."""
import numpy as np

def pixels_array(image):
    pixels = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(pixels)
    return pixels.reshape((-1, image.channels))
