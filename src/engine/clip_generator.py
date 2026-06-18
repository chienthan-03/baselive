import subprocess
import os
from datetime import datetime
from src.core.models import EventCandidate

class ClipGenerator:
    def __init__(self, source_file: str, output_dir: str = "output/clips",
                 pre_roll: float = 10.0, post_roll: float = 5.0,
                 pts_offset: float = 0.0):
        self.source_file = source_file
        self.output_dir = output_dir
        self.pre_roll = pre_roll
        self.post_roll = post_roll
        self.pts_offset = pts_offset
        os.makedirs(output_dir, exist_ok=True)

    def build_ffmpeg_cmd(self, event: EventCandidate, output_path: str) -> list:
        start = max(0.0, event.start_pts - self.pts_offset - self.pre_roll)
        duration = (event.end_pts - event.start_pts) + self.pre_roll + self.post_roll

        return [
            "ffmpeg",
            "-ss", str(start),
            "-i", self.source_file,
            "-t", str(duration),
            "-c", "copy",
            "-avoid_negative_ts", "1",
            "-y",
            output_path,
        ]

    def generate(self, event: EventCandidate) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        peak_score = event.peak_score if event.peak_score is not None else 0.0
        output_path = os.path.join(
            self.output_dir,
            f"highlight_{timestamp}_score{peak_score:.2f}.mp4"
        )

        cmd = self.build_ffmpeg_cmd(event, output_path)

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr}")

        return output_path
