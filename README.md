# Classroom Hand Raise Detector

A computer vision prototype that detects hand raises in a recorded webcam session. It shows the total count and the start time, end time, and duration of each raise. Click a start time in the timeline to jump to that moment in the replay.

## Run locally

You’ll need Python 3.11 and Node.js with npm. The commands below use PowerShell on Windows. Run each block from the repository root in a separate terminal.

### Start the backend

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

FastAPI runs at `http://127.0.0.1:8000`. The MediaPipe model is included in `backend/models/`.

### Start the frontend

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Open `http://localhost:5173/`.

## Try it

1. Click **Start Recording** and allow camera access.
2. Keep one person in view, with their shoulders and wrists visible. Raise a hand for about two seconds, lower it, then repeat.
3. Click **Stop Recording**. The app sends the clip to the local backend and displays the detected raises.
4. Click a start time in the timeline and press **Play** to review the event.

## How detection works

React records the webcam clip. FastAPI receives it, OpenCV reads the frames and their timestamps, and MediaPipe estimates shoulder and wrist positions. The detector counts a raise when a visible wrist stays above its shoulder for at least 0.75 seconds.

The prototype analyzes one person after recording stops. Brief gestures or an obscured wrist can be missed. The browser holds the clip for replay during the session, and the backend deletes its temporary copy after analysis.