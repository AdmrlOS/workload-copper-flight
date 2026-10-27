import { parseFrame } from './state.js';
import { poseFromFrame, interpolatePose } from './pose.js';

export function createPlayback(mission) {
  const start = mission.frames[0].sim_time_s;
  const end = mission.frames.at(-1).sim_time_s;
  let position = start; let anchor = 0; let rate = 1; let playing = false;
  const clamp = value => Math.max(start, Math.min(end, value));
  const time = now => {
    const value = clamp(position + (playing ? Math.max(0, now - anchor) * rate / 1000 : 0));
    if (value === end && playing) { position = end; playing = false; }
    return value;
  };
  return {
    start, end, time,
    get playing() { return playing; }, get rate() { return rate; },
    play(now) { if (time(now) >= end) position = start; anchor = now; playing = true; },
    pause(now) { position = time(now); anchor = now; playing = false; },
    seek(value, now) { if (!Number.isFinite(value)) return; position = clamp(value); anchor = now; },
    setRate(value, now) { if (![0.25, 0.5, 1, 2].includes(value)) throw new TypeError('Unsupported playback rate'); position = time(now); anchor = now; rate = value; },
  };
}

// Binary search keeps per-render sampling cheap even for high-rate recordings.
export function sampleMission(mission, timeS) {
  const frames = mission?.frames;
  if (!frames?.length || !Number.isFinite(timeS)) return null;
  let low = 0; let high = frames.length - 1;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (frames[middle].sim_time_s <= timeS) low = middle; else high = middle - 1;
  }
  const frame = frames[low];
  const next = frames[Math.min(low + 1, frames.length - 1)];
  const t = next === frame ? 0 : Math.max(0, Math.min(1, (timeS - frame.sim_time_s) / (next.sim_time_s - frame.sim_time_s)));
  return { frame, pose: interpolatePose(poseFromFrame(frame), poseFromFrame(next), t), interpolated: t > 0 && t < 1, bracket: [frame.seq, next.seq] };
}

export const recordingID = value => typeof value === 'string' && /^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$/.test(value);

export function parseRecording(input, expectedID) {
  const recording = input?.recording;
  if (input?.schema_version !== 1 || !recordingID(recording?.id) || recording.id !== expectedID || recording.completed !== true) throw new TypeError('Invalid completed recording');
  if (!Array.isArray(input.frames) || !input.frames.length) throw new TypeError('Recording telemetry is empty');
  let previous = null;
  const frames = input.frames.map(raw => {
    const frame = parseFrame(raw);
    if (!frame || frame.sim_time_s === null || frame.world !== 'forest'
      || (previous && (frame.seq <= previous.seq || frame.sim_time_s < previous.sim_time_s))) throw new TypeError('Invalid or unordered recording telemetry frame');
    previous = frame;
    return frame;
  });
  return {
    recording: { id: recording.id, completed: true, started_at: typeof recording.started_at === 'string' ? recording.started_at : null, ended_at: typeof recording.ended_at === 'string' ? recording.ended_at : null },
    provenance: input.provenance && typeof input.provenance === 'object' && !Array.isArray(input.provenance) ? input.provenance : null,
    frames,
  };
}
