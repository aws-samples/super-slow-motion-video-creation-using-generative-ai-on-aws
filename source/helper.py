from pathlib import Path
import random
import subprocess
import tarfile
import os

#
# make tar.gz file
#
def make_tar(folder_path):
    output_path = "input_frames.tar.gz"
    
    # tar the files
    with tarfile.open(output_path, "w:gz") as tar:
        for filename in os.listdir(folder_path):
            file = os.path.join(folder_path, filename)
            tar.add(file, arcname=os.path.basename(file))

    return output_path

#
# use ffmpeg to extract frames from video
#
def extract_frames(video_path):
    
    output_dir = Path(f"/tmp/{random.randint(0, 1000000)}")
    while output_dir.exists():
        output_dir = Path(f"/tmp/{random.randint(0, 1000000)}")
        
    output_dir.mkdir(parents=True, exist_ok=False)
    
    output_pattern = output_dir / "frame-%07d.jpg"
    print(output_pattern)
    
    ffmpeg_cmd = ["ffmpeg", "-i", video_path, 
                  "-qmin", "1", "-q:v", "1", str(output_pattern)]
    
    try:
        subprocess.run(ffmpeg_cmd, check=True)
    except subprocess.CalledProcessError as err:
        print(f"Error running ffmpeg: {err}")
        
    return output_dir

#
# use ffmpeg to create video from frames
#
def create_video(input_frame_dir, output_file, fr=60):
    
    ffmpeg_cmd = [
    "ffmpeg", 
    "-y", 
    "-framerate", str(fr),
    "-pattern_type", "glob",
    "-i", f"{input_frame_dir}/frame*.jpg", 
    "-c:v", "libx264",
    "-pix_fmt", "yuvj420p",
    output_file
    ]

    try:
        subprocess.run(ffmpeg_cmd, check=True)
    except subprocess.CalledProcessError as err:
        print(f"Error running ffmpeg: {err}")