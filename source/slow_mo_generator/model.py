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

is_initialized = False
s3_bucket = None
s3_prefix = None
model_path = "model/Style/saved_model"

def initialize_service(properties: dict):
    
    global is_initialized
    global s3_bucket
    global s3_prefix
  
    
    s3_bucket = properties.get("s3_bucket")
    s3_prefix = properties.get("s3_prefix")
    
    #
    # copy model onto the instance
    #
    try:
        subprocess.run(["/opt/djl/bin/s5cmd", "ls", f"s3://{s3_bucket}/{s3_prefix}/"], check=True, timeout=15)
    except subprocess.CalledProcessError as e:
        raise Exception(f"Unable to access s3://{s3_bucket}/{s3_prefix}/. Error message: {e.output}.")
    except Exception as e:
        raise Exception(f"Unable to access s3://{s3_bucket}/{s3_prefix}/. Error message: {e}.")
    
    is_initialized = True


def handle(inputs: Input):
    
    global is_initialized
    global s3_bucket
    global s3_prefix
   
    properties = inputs.get_properties()

    if not is_initialized:
        initialize_service(properties)

    if inputs.is_empty():
        return None
    
    tar_buffer = BytesIO(inputs.get_as_bytes())
    
    # extract input frames
    frame_dir, process_config = utils.extract_frames(tar_buffer)
    
    print(f"extracted frames to here: {frame_dir}")
    # kick off interpolation process to generate new frames
    
    slow_frame_dir = asyncio.run(utils.interpolate_frames(input_frame_dir=frame_dir, 
                                                          model_path=model_path,
                                                         **process_config))
        
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