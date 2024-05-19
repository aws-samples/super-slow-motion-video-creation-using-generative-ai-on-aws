from djl_python import Input, Output
from io import BytesIO
from pathlib import Path
import os
import uuid
import subprocess
import json
import time
import utils
import random
import asyncio

import interpolator as interpolator_lib

s3_bucket = None
s3_prefix = None
model_path = "model/Style/saved_model"
_interpolator = None

def initialize_service(properties: dict):
    
    global s3_bucket
    global s3_prefix
  
    
    s3_bucket = properties.get("s3_bucket")
    s3_prefix = properties.get("s3_prefix")
    #
    # check S3 location
    #
    try:
        subprocess.run(["/opt/djl/bin/s5cmd", "ls", f"s3://{s3_bucket}/{s3_prefix}/"], check=True, timeout=15)
    except subprocess.CalledProcessError as e:
        raise Exception(f"Unable to access s3://{s3_bucket}/{s3_prefix}/. Error message: {e.output}.")
    except Exception as e:
        raise Exception(f"Unable to access s3://{s3_bucket}/{s3_prefix}/. Error message: {e}.")

    # Initialize interpolator
    align = 64
    block_height = 1
    block_width = 1
        
        
    _interpolator = interpolator_lib.Interpolator(model_path, 
                                              64, 
                                              [1, 1])
    
    print("Interpolator loaded....")
    
    return _interpolator


def handle(inputs: Input):
    
    global _interpolator
    global s3_bucket
    global s3_prefix

    # get property
    properties = inputs.get_properties()

   
    if not _interpolator:
        _interpolator = initialize_service(properties)

    if inputs.is_empty():
        return None

    # load input config and extract input frames
    tar_buffer = BytesIO(inputs.get_as_bytes())

    frame_dir, process_config = utils.extract_frames(tar_buffer)

    # set the interpolator configuration
    print(f"set interpolator configuration...")
    _interpolator._align = process_config["align"]
    _interpolator._block_shape = [process_config["block_height"],
                                  process_config["block_width"]]
    
    print(f"extracted frames to here: {frame_dir}")
    # kick off interpolation process to generate new frames
    
    slow_frame_dir = utils.interpolate_frames(input_frame_dir=frame_dir, 
                                                          interpolator=_interpolator,
                                                         **process_config)
        
    timeout = 30  
    
    print(f"slow-mo frames to here: {slow_frame_dir}")
    print(os.listdir(slow_frame_dir))
    
    # Upload the frames to S3
    output_s3_path = f"s3://{s3_bucket}/{s3_prefix}/{os.path.basename(slow_frame_dir)}/"
    try:
        # Build s5cmd command
        cmd = ["/opt/djl/bin/s5cmd", "cp", f"{slow_frame_dir}/", output_s3_path]

        # Run command
        subprocess.run(cmd, timeout=timeout, check=True)
        
        print(f"Frames uploaded to {output_s3_path}")
        status = "SUCCESS"

    except subprocess.CalledProcessError as e:
        print("Error executing s5cmd:") 
        print(e.output)
        print(e.stderr)
        status = "Failed"

    except Exception as e:
        print("Unexpected error:")
        print(e)
        status = "Failed"

    return Output().add_as_json({"status":status, "output_location": output_s3_path})