import { sampleMission, createPlayback } from './mission.js';

export function createSession(liveBuffer) {
  let mode = 'live'; let mission = null; let clock = null;
  return {
    get mode() { return mode; }, get mission() { return mission; }, get clock() { return clock; },
    setMode(next, now) { if (!['live', 'recorded'].includes(next)) throw new TypeError('Unsupported source mode'); if (next !== mode) clock?.pause(now); mode = next; },
    load(value) { mission = value; clock = createPlayback(value); },
    view(now) {
      if (mode === 'live') return { ...liveBuffer.sample(now), mode, frames: liveBuffer.frames };
      if (!mission) return { mode, pose: null, frame: null, frames: [], reason: 'Choose a completed native mission', live: false };
      const timeS = clock.time(now);
      return { ...sampleMission(mission, timeS), mode, live: false, timeS, key: mission.recording.id, frames: mission.frames, reason: 'Recorded native mission visualization' };
    },
  };
}

export function captureEvidence(copper) {
  if (copper?.recording_mode === 'telemetry-only' || copper?.full_recording === false) return { full: false, text: 'FULL CAPTURE OFF', detail: 'Telemetry only · no full native archive' };
  if (copper?.recording_mode === 'full' && copper?.full_recording === true) return { full: true, text: 'Full capture reported ON', detail: 'Native replay remains unverified' };
  return null;
}

export function evidenceLabel(mode, frame, advancing) {
  if (!frame?.policy_prediction_m_s || !frame?.inference_backend) return 'Policy evidence unavailable';
  const backend = frame.inference_backend.toUpperCase();
  if (mode === 'recorded') return `${backend} · recorded policy observation`;
  return advancing ? `${backend} · policy publications advancing` : `${backend} · last reported policy`;
}

// No resampling or invented gap values: charts describe source frames only.
export function chartPath(frames, valueOf, { start, end, min, max, width, height }) {
  let path = ''; let pen = false;
  for (const frame of frames) {
    const value = valueOf(frame); const time = frame.sim_time_s;
    if (!Number.isFinite(value) || !Number.isFinite(time)) { pen = false; continue; }
    if (time < start || time > end) continue;
    const x = (time - start) / (end - start || 1) * width;
    const y = height - (value - min) / (max - min || 1) * height;
    path += `${pen ? 'L' : 'M'}${+x.toFixed(2)},${+y.toFixed(2)}`; pen = true;
  }
  return path;
}
