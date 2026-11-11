from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

import cv2
import mediapipe as mp
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from mediapipe.tasks.python import vision

app = FastAPI(title="Classroom Hand Raise Detector")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

MODEL_PATH = Path(__file__).resolve().parent / "models" / "pose_landmarker_lite.task"
MAX_VIDEO_BYTES = 50 * 1024 * 1024
MIN_RAISE_SECONDS = 0.75

ARM_LANDMARKS = (
    ("left", 11, 15),
    ("right", 12, 16),
)


def hand_is_raised(landmarks):
    for _, shoulder_index, wrist_index in ARM_LANDMARKS:
        shoulder = landmarks[shoulder_index]
        wrist = landmarks[wrist_index]

        if (
            shoulder.visibility >= 0.6
            and wrist.visibility >= 0.6
            and 0 <= wrist.x <= 1
            and 0 <= wrist.y <= 1
            and shoulder.y - wrist.y > 0.05
        ):
            return True

    return False


def print_diagnostics(seconds, video_ms, fps, poses, raised):
    print(
        f"Session time={seconds:.2f}s | "
        f"Video time={video_ms / 1000:.2f}s | "
        f"Reported FPS={fps:.2f} | raised={raised}",
        flush=True,
    )

    if not poses:
        print("  No pose detected", flush=True)
        return

    landmarks = poses[0]
    for side, shoulder_index, wrist_index in ARM_LANDMARKS:
        shoulder = landmarks[shoulder_index]
        wrist = landmarks[wrist_index]
        print(
            f"  {side}: shoulder visibility={shoulder.visibility:.2f}, "
            f"wrist visibility={wrist.visibility:.2f}, "
            f"wrist=({wrist.x:.2f}, {wrist.y:.2f}), "
            f"height above shoulder={shoulder.y - wrist.y:.2f}",
            flush=True,
        )


def detect_hand_raises(video_path: Path):
    if not MODEL_PATH.is_file():
        raise HTTPException(status_code=500, detail="The pose model file is missing.")

    options = vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(MODEL_PATH)),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
    )

    capture = cv2.VideoCapture(str(video_path))
    events = []
    started_at = None
    frame_count = 0
    video_time_offset = None
    previous_seconds = None
    last_timestamp_ms = -1
    next_diagnostic_at = 0.0

    def record_event(start, end):
        duration = end - start
        if duration >= MIN_RAISE_SECONDS:
            events.append({
                "start_seconds": round(start, 2),
                "end_seconds": round(end, 2),
                "duration_seconds": round(duration, 2),
            })

    try:
        if not capture.isOpened():
            raise HTTPException(status_code=400, detail="Could not open the recording.")

        fps = capture.get(cv2.CAP_PROP_FPS)

        # Use the reported FPS only to estimate missing frame timestamps.
        # The webcam recording reported 1000 FPS despite playing much slower.
        frame_step = 1 / fps if isfinite(fps) and 0 < fps <= 240 else 1 / 30

        with vision.PoseLandmarker.create_from_options(options) as detector:
            while True:
                success, frame = capture.read()
                if not success:
                    break

                video_ms = capture.get(cv2.CAP_PROP_POS_MSEC)
                video_seconds = video_ms / 1000
                estimated_seconds = (
                    0.0 if previous_seconds is None
                    else previous_seconds + frame_step
                )
                seconds = estimated_seconds

                if isfinite(video_seconds) and video_seconds >= 0:
                    if video_time_offset is None:
                        video_time_offset = video_seconds - estimated_seconds

                    session_seconds = video_seconds - video_time_offset
                    if previous_seconds is None or session_seconds > previous_seconds:
                        seconds = session_seconds
                        if previous_seconds is not None:
                            frame_step = seconds - previous_seconds

                previous_seconds = seconds
                timestamp_ms = max(last_timestamp_ms + 1, round(seconds * 1000))
                last_timestamp_ms = timestamp_ms
                frame_count += 1

                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                poses = detector.detect_for_video(image, timestamp_ms).pose_landmarks
                raised = bool(poses) and hand_is_raised(poses[0])

                if seconds >= next_diagnostic_at:
                    print_diagnostics(seconds, video_ms, fps, poses, raised)
                    next_diagnostic_at = seconds + 0.25

                if raised and started_at is None:
                    started_at = seconds
                elif not raised and started_at is not None:
                    record_event(started_at, seconds)
                    started_at = None

        if previous_seconds is None:
            raise HTTPException(
                status_code=400,
                detail="The recording has no readable frames.",
            )

        duration = previous_seconds + frame_step
        if started_at is not None:
            record_event(started_at, duration)

        print(
            f"Analyzed {frame_count} frames | "
            f"Session duration={duration:.2f}s | "
            f"Total hand raises={len(events)}",
            flush=True,
        )
        return {"total_hand_raises": len(events), "events": events}
    finally:
        capture.release()


@app.post("/api/activity/video")
def analyze_recording(video: Annotated[UploadFile, File()]):
    try:
        extension = Path(video.filename or "").suffix.lower()
        if extension not in {".mp4", ".webm"}:
            raise HTTPException(status_code=415, detail="Choose an MP4 or WebM recording.")

        recording = video.file.read(MAX_VIDEO_BYTES + 1)
    finally:
        video.file.close()

    if not recording:
        raise HTTPException(status_code=400, detail="The recording is empty.")

    if len(recording) > MAX_VIDEO_BYTES:
        raise HTTPException(status_code=413, detail="The recording exceeds 50 MB.")

    with TemporaryDirectory() as directory:
        video_path = Path(directory) / f"session{extension}"
        video_path.write_bytes(recording)
        return detect_hand_raises(video_path)