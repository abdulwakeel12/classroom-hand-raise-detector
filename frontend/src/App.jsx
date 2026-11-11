import { useEffect, useRef, useState } from 'react'
import './App.css'

const ANALYSIS_URL = 'http://127.0.0.1:8000/api/activity/video'

export default function App() {
  const previewRef = useRef(null)
  const replayRef = useRef(null)
  const streamRef = useRef(null)
  const recorderRef = useRef(null)
  const analysisRequestRef = useRef(null)

  const [phase, setPhase] = useState('idle')
  const [recordingUrl, setRecordingUrl] = useState('')
  const [analysis, setAnalysis] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    return () => {
      analysisRequestRef.current?.abort()

      const recorder = recorderRef.current
      if (recorder) {
        recorder.onstop = null
        recorder.onerror = null
        if (recorder.state !== 'inactive') recorder.stop()
      }

      streamRef.current?.getTracks().forEach((track) => track.stop())
    }
  }, [])

  useEffect(() => {
    return () => {
      if (recordingUrl) URL.revokeObjectURL(recordingUrl)
    }
  }, [recordingUrl])

  function releaseCamera() {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    recorderRef.current = null

    if (previewRef.current) {
      previewRef.current.srcObject = null
    }
  }

  async function analyzeRecording(clip) {
    const controller = new AbortController()
    analysisRequestRef.current = controller
    setPhase('analyzing')

    try {
      const extension = clip.type.includes('mp4') ? 'mp4' : 'webm'
      const formData = new FormData()
      formData.append('video', clip, `session.${extension}`)

      const response = await fetch(ANALYSIS_URL, {
        method: 'POST',
        body: formData,
        signal: controller.signal,
      })

      const result = await response.json().catch(() => null)

      if (!response.ok) {
        throw new Error(
          result?.detail || `Analysis failed (HTTP ${response.status}).`
        )
      }

      if (!Array.isArray(result?.events)) {
        throw new Error('The backend returned an invalid analysis result.')
      }

      setAnalysis(result)
    } catch (error) {
      if (!controller.signal.aborted) {
        setError(error.message || 'Could not analyze the recording.')
      }
    } finally {
      analysisRequestRef.current = null
      if (!controller.signal.aborted) setPhase('idle')
    }
  }

  async function startRecording() {
    setError('')
    setPhase('opening')

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: false,
      })

      if (!previewRef.current) {
        stream.getTracks().forEach((track) => track.stop())
        return
      }

      streamRef.current = stream
      previewRef.current.srcObject = stream

      const recorder = new MediaRecorder(stream)
      recorderRef.current = recorder
      const chunks = []

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunks.push(event.data)
      }

      recorder.onerror = (event) => {
        recorder.onstop = null
        releaseCamera()
        setError(event.error?.message || 'Recording failed.')
        setPhase('idle')
      }

      recorder.onstop = () => {
        releaseCamera()

        const clip = new Blob(chunks, {
          type: recorder.mimeType || chunks[0]?.type || 'video/webm',
        })

        if (clip.size === 0) {
          setError('The clip was empty. Try recording for a few seconds.')
          setPhase('idle')
          return
        }

        setRecordingUrl(URL.createObjectURL(clip))
        void analyzeRecording(clip)
      }

      recorder.start()
      setRecordingUrl('')
      setAnalysis(null)
      setPhase('recording')
    } catch (error) {
      releaseCamera()
      setError(error.message || 'Could not start the camera.')
      setPhase('idle')
    }
  }

  function stopRecording() {
    const recorder = recorderRef.current
    if (recorder?.state === 'recording') {
      setPhase('stopping')
      recorder.stop()
    }
  }

  function jumpTo(seconds) {
    if (replayRef.current) {
      replayRef.current.currentTime = seconds
    }
  }

  return (
    <main>
      <h1>Classroom Hand Raise Detector</h1>
      <p>Record a classroom session and review detected hand raises.</p>

      <button type="button" onClick={startRecording} disabled={phase !== 'idle'}>
        Start Recording
      </button>{' '}
      <button type="button" onClick={stopRecording} disabled={phase !== 'recording'}>
        Stop Recording
      </button>

      {phase === 'opening' && <p role="status">Opening camera…</p>}
      {phase === 'recording' && <p role="status">Recording…</p>}
      {phase === 'stopping' && <p role="status">Preparing replay…</p>}
      {phase === 'analyzing' && <p role="status">Analyzing hand raises…</p>}
      {error && <p role="alert">{error}</p>}

      <video
        ref={previewRef}
        autoPlay
        playsInline
        muted
        hidden={phase !== 'recording'}
        style={{ width: '100%', maxWidth: 720, marginTop: 16 }}
      />

      {recordingUrl && (
        <section>
          <h2>Session Replay</h2>
          <video
            ref={replayRef}
            src={recordingUrl}
            controls
            playsInline
            style={{ width: '100%', maxWidth: 720 }}
          />
        </section>
      )}

      {analysis && (
        <section>
          <h2>Hand Raise Timeline</h2>
          <p>Total hand raises: {analysis.total_hand_raises}</p>

          {analysis.events.length === 0 ? (
            <p>No hand raises detected in this recording.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th scope="col">Start</th>
                  <th scope="col">End</th>
                  <th scope="col">Duration</th>
                </tr>
              </thead>
              <tbody>
                {analysis.events.map((event, index) => (
                  <tr key={`${event.start_seconds}-${index}`}>
                    <td>
                      <button
                        type="button"
                        onClick={() => jumpTo(event.start_seconds)}
                        aria-label={`Jump to hand raise ${index + 1} at ${event.start_seconds.toFixed(2)} seconds`}
                      >
                        {event.start_seconds.toFixed(2)} s
                      </button>
                    </td>
                    <td>{event.end_seconds.toFixed(2)} s</td>
                    <td>{event.duration_seconds.toFixed(2)} s</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
    </main>
  )
}