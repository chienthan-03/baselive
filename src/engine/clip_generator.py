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

    def _ffmpeg_copy_cmd(self, seek_pts: float, duration: float, output_path: str) -> list:
        return [
            "ffmpeg",
            "-ss", str(max(0.0, seek_pts)),
            "-i", self.source_file,
            "-t", str(duration),
            "-c", "copy",
            "-avoid_negative_ts", "1",
            "-y",
            output_path,
        ]

    def build_ffmpeg_cmd(self, event: EventCandidate, output_path: str) -> list:
        start = event.start_pts - self.pts_offset - self.pre_roll
        duration = (event.end_pts - event.start_pts) + self.pre_roll + self.post_roll
        return self._ffmpeg_copy_cmd(start, duration, output_path)

    def build_draft_cmd(
        self, event: EventCandidate, end_pts: float, output_path: str
    ) -> list:
        start = event.start_pts - self.pts_offset - self.pre_roll
        duration = (end_pts - event.start_pts) + self.pre_roll
        return self._ffmpeg_copy_cmd(start, duration, output_path)

    def build_final_cmd(
        self,
        start_pts: float,
        end_pts: float,
        output_path: str,
        pre_roll: float | None = None,
        post_roll: float | None = None,
    ) -> list:
        pre = self.pre_roll if pre_roll is None else pre_roll
        post = self.post_roll if post_roll is None else post_roll
        start = start_pts - self.pts_offset - pre
        duration = (end_pts - start_pts) + pre + post
        return self._ffmpeg_copy_cmd(start, duration, output_path)

    def _run_ffmpeg(self, cmd: list) -> None:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr}")

    def _make_output_path(self, prefix: str, event: EventCandidate) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        peak_score = event.peak_score if event.peak_score is not None else 0.0
        return os.path.join(
            self.output_dir,
            f"{prefix}_{timestamp}_score{peak_score:.2f}.mp4",
        )

    def generate_draft(self, event: EventCandidate, end_pts: float) -> str:
        output_path = self._make_output_path("draft", event)
        cmd = self.build_draft_cmd(event, end_pts=end_pts, output_path=output_path)
        self._run_ffmpeg(cmd)
        return output_path

    def generate_final(
        self,
        start_pts: float,
        end_pts: float,
        event: EventCandidate,
        pre_roll: float | None = None,
        post_roll: float | None = None,
    ) -> str:
        output_path = self._make_output_path("highlight", event)
        cmd = self.build_final_cmd(
            start_pts=start_pts,
            end_pts=end_pts,
            output_path=output_path,
            pre_roll=pre_roll,
            post_roll=post_roll,
        )
        self._run_ffmpeg(cmd)
        return output_path

    def generate(self, event: EventCandidate) -> str:
        return self.generate_final(event.start_pts, event.end_pts, event)
