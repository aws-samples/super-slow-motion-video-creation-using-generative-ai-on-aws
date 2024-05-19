import subprocess
from pathlib import Path
import random
import os
import sys
import time
from tqdm import tqdm
import numpy as np
from typing import Generator, Iterable, List, Optional
import tensorflow as tf
import glob
import asyncio
import tarfile
import json

import interpolator as interpolator_lib

_UINT8_MAX_F = float(np.iinfo(np.uint8).max)


#
# use ffmpeg to extract frames from video
#
def extract_frames(tar_obj):
    
    tmp_path = Path(f"/tmp/{random.randint(0, 1000000)}")
    while tmp_path.exists():
        tmp_path = Path(f"/tmp/{random.randint(0, 1000000)}")
    tmp_path.mkdir(parents=True, exist_ok=False)
    
    with tarfile.open(fileobj=tar_obj) as tar:
        tar.extractall(tmp_path)
        
        # check if config.json exists in the train path
    if (tmp_path / "config.json").exists():
        process_config = json.load((tmp_path / "config.json").open())
    else:
        process_config = {}  
        
    return tmp_path, process_config

#
# read_image, ported from codes/eval/util.py
#
def read_image(filename: str) -> np.ndarray:
    """Reads an sRgb 8-bit image.

    Args:
        filename: The input filename to read.

    Returns:
        A float32 3-channel (RGB) ndarray with colors in the [0..1] range.
    """
    image_data = tf.io.read_file(filename)
    image = tf.image.decode_image(image_data, channels=3)
    image_numpy = tf.cast(image, dtype=tf.float32).numpy()
    return image_numpy / _UINT8_MAX_F


#
# write_image, ported from codes/eval/util.py
#
def write_image(filename: str, image: np.ndarray) -> str:
    """Writes a float32 3-channel RGB ndarray image, with colors in range [0..1].

    Args:
        filename: The output filename to save.
        image: A float32 3-channel (RGB) ndarray with colors in the [0..1] range.

    Returns:
        filename
    """

    image_in_uint8_range = np.clip(image * _UINT8_MAX_F, 0.0, _UINT8_MAX_F)
    image_in_uint8 = (image_in_uint8_range + 0.5).astype(np.uint8)

    extension = os.path.splitext(filename)[1]
    if extension == '.jpg':
        image_data = tf.image.encode_jpeg(image = image_in_uint8, quality = 100)
    else:
        image_data = tf.image.encode_png(image_in_uint8)

    with open(filename, 'wb+') as f:
        f.write(image_data.numpy())
    return filename

#
# recursively interpolate frames, ported from codes/eval/util.py
#
def _recursive_generator(
    frame1: np.ndarray,
    frame2: np.ndarray,
    num_recursions: int,
    interpolator: interpolator_lib.Interpolator,
    progress_bar: Optional[tqdm] = None
) -> Generator[np.ndarray, None, None]:
    """Splits halfway to repeatedly generate more frames.

    Args:
        frame1: Input image 1.
        frame2: Input image 2.
        num_recursions: How many times to interpolate the consecutive image pairs.
        interpolator: The frame interpolator instance.

    Yields:
        The interpolated frames, including the first frame (frame1), but excluding
        the final frame2.
    """
    if num_recursions == 0:
        yield frame1
    else:
        # Adds the batch dimension to all inputs before calling the interpolator,
        # and remove it afterwards.
        time = np.full(shape=(1,), fill_value=0.5, dtype=np.float32)
        mid_frame = interpolator(
            frame1[np.newaxis, ...],
            frame2[np.newaxis, ...],
            time)[0]
        progress_bar.update(1) if progress_bar is not None else progress_bar
        yield from _recursive_generator(
            frame1,
            mid_frame,
            num_recursions - 1,
            interpolator,
            progress_bar)
        yield from _recursive_generator(
            mid_frame,
            frame2,
            num_recursions - 1,
            interpolator,
            progress_bar)

#
# interpolate frames from a list of input frames, ported from codes/eval/util.py
#
def interpolate_recursively_from_memory(
    frames: List[np.ndarray],
    times_to_interpolate: int,
    interpolator: interpolator_lib.Interpolator
) -> Iterable[np.ndarray]:
    """Generates interpolated frames by repeatedly interpolating the midpoint.

    This is functionally equivalent to interpolate_recursively_from_files(), but
    expects the inputs frames in memory, instead of loading them on demand.

    Recursive interpolation is useful if the interpolator is trained to predict
    frames at midpoint only and is thus expected to perform poorly elsewhere.

    Args:
        frames: List of input frames. Expected shape (H, W, 3). The colors should be
          in the range[0, 1] and in gamma space.
        times_to_interpolate: Number of times to do recursive midpoint
          interpolation.
        interpolator: The frame interpolation model to use.

    Yields:
        The interpolated frames (including the inputs).
    """
    n = len(frames)
    num_frames = (n - 1) * (2**(times_to_interpolate) - 1)
    progress_bar = tqdm(total=num_frames, ncols=100, colour='green')

    for i in range(1, n):
        yield from _recursive_generator(
            frames[i - 1],
            frames[i],
            times_to_interpolate,
            interpolator,
            progress_bar)
    # Separately yield the final frame.
    yield frames[-1]
    
#
# using the model to do frame interpolation
#
def interpolate_frames(input_frame_dir: str, 
                       interpolator: interpolator_lib.Interpolator,
                       align=64, 
                       block_height=1, 
                       block_width=1,
                       time_to_interpolate=3):
    
    input_jpeg_files = sorted(glob.glob(f"{input_frame_dir}/*.jpg"))
    #
    # create output_frames directory to store the output
    #
    output_frame_dir = Path(f"/tmp/{random.randint(0, 1000000)}")
    while output_frame_dir.exists():
        output_frame_dir = Path(f"/tmp/{random.randint(0, 1000000)}")
        
    output_frame_dir.mkdir(parents=True, exist_ok=False)
    
    #
    # read image to memory async
    #
    jpeg_nparray = [read_image(input_jpeg) for input_jpeg in input_jpeg_files]
    
    #
    # wait for read images
    #
    # jpeg_nparray = await asyncio.gather(*processes)
    
  #
    # start interpolation process by calling interpolate recursively
    #
    t0 = time.time()
    frames = list(interpolate_recursively_from_memory(jpeg_nparray, time_to_interpolate, interpolator))
    t1 = time.time()
    print(f">> interpolate_recursively_from_files: elapsed", t1 - t0)  

    del jpeg_nparray
    #
    # write frames to output_frames directory
    #
    processes = [write_image(output_frame_dir / f"frame_{idx:07d}.jpg", frame) for idx, frame in enumerate(frames)]
    # await asyncio.gather(*processes)
    
    del frames
    del processes
    
    t2 = time.time()
    print(f">> asyncio.write_image: {t2 - t1}")
    
    return output_frame_dir