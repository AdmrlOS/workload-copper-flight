import { parseFrame } from './state.js';
import { sampleMission } from './mission.js';

// Measured wall/simulation cadence drives only presentation, never physics.
export function createLiveBuffer() {
  let frames = []; let arrivals = []; let key = null; let source = null;
  let receivedAt = 0; let progressedAt = null; let cursor = null; let renderedAt = null; let failed = false;
  const metrics = () => {
    const first = arrivals[0]; const last = arrivals.at(-1);
    const elapsed = first && last ? (last.at - first.at) / 1000 : 0;
    const nativeFrames = frames.slice(-120);
    const nativeFirst = nativeFrames[0]; const nativeLast = nativeFrames.at(-1);
    const nativeClock = nativeFrames.length > 1 && nativeFrames.every((f, index) => Number.isFinite(f.wall_time_s) && (index === 0 || f.wall_time_s > nativeFrames[index - 1].wall_time_s));
    const nativeElapsed = nativeClock ? nativeLast.wall_time_s - nativeFirst.wall_time_s : null;
    const simRate = nativeClock ? (nativeLast.sim_time_s - nativeFirst.sim_time_s) / nativeElapsed : elapsed > 0 ? (last.sim - first.sim) / elapsed : null;
    const sourceHz = nativeClock ? (nativeFrames.length - 1) / nativeElapsed : elapsed > 0 ? arrivals.slice(1).reduce((sum, item) => sum + item.count, 0) / elapsed : null;
    const intervalS = frames.length > 1 ? (frames.at(-1).sim_time_s - frames[Math.max(0, frames.length - 12)].sim_time_s) / Math.min(11, frames.length - 1) : null;
    const delayS = intervalS === null ? 0 : Math.max(intervalS * 1.5, (simRate ?? 1) * .2);
    return { simRate, sourceHz, intervalS, delayS, samples: frames.length, clock: nativeClock ? 'native' : 'receipt' };
  };
  return {
    get frames() { return frames; }, get key() { return key; }, get source() { return source; },
    metrics,
    fail() { failed = true; },
    ingest(envelope, now) {
      source = envelope; receivedAt = now; failed = false;
      const nextKey = JSON.stringify([envelope.engine?.revision, envelope.episode?.id, envelope.episode?.started_at]);
      const reset = nextKey !== key || envelope.reset === true;
      if (reset) { frames = []; arrivals = []; cursor = null; renderedAt = null; progressedAt = null; key = nextKey; }
      const latest = frames.at(-1);
      const added = envelope.frames.filter(frame => (!latest || frame.seq > latest.seq) && frame.sim_time_s !== null);
      if (added.length) {
        if (latest && added[0].sim_time_s < latest.sim_time_s) return;
        frames = [...frames, ...added].slice(-600);
        arrivals = [...arrivals, { at: now, sim: frames.at(-1).sim_time_s, count: added.length }].slice(-12);
        if (frames.at(-1).sim_time_s > (latest?.sim_time_s ?? added[0].sim_time_s)) progressedAt = now;
        if (cursor === null) cursor = Math.max(frames[0].sim_time_s, frames.at(-1).sim_time_s - metrics().delayS);
      }
    },
    sample(now) {
      if (!frames.length) return { live: false, pose: null, frame: null, reason: 'Waiting for native telemetry' };
      const age = source.frame_age_s === null ? null : source.frame_age_s + Math.max(0, now - receivedAt) / 1000;
      const live = !failed && source.status === 'live' && source.engine?.native === true && age !== null && age < 2 && progressedAt !== null && now - progressedAt < 2000;
      if (live && renderedAt !== null) {
        const stats = metrics();
        const target = frames.at(-1).sim_time_s - stats.delayS;
        const correction = Math.max(.8, Math.min(1.2, 1 + (target - cursor) * .25));
        cursor = Math.min(frames.at(-1).sim_time_s, cursor + Math.max(0, now - renderedAt) / 1000 * (stats.simRate ?? 1) * correction);
      }
      renderedAt = now;
      const sampled = sampleMission({ frames }, cursor);
      const matching = sampled.frame.world === 'forest' && sampled.pose !== null;
      return { ...sampled, timeS: cursor, live: live && matching, key, reason: !matching ? 'Observed world/pose does not match forest' : live ? 'Native telemetry · buffered' : failed ? 'Connection unavailable · pose frozen' : 'Native progress unconfirmed or stale · pose frozen', frameAgeS: age };
    },
  };
}

export function parseTelemetry(input) {
  if (input?.schema_version !== 1 || !Array.isArray(input.frames) || !['starting', 'live', 'between_episodes', 'failed', 'stopped'].includes(input.status)) throw new TypeError('Unsupported telemetry envelope');
  let prior = null;
  const frames = input.frames.map(raw => {
    const frame = parseFrame(raw);
    if (!frame || frame.sim_time_s === null || (prior && (frame.seq <= prior.seq || frame.sim_time_s < prior.sim_time_s))) throw new TypeError('Invalid telemetry frame order');
    prior = frame; return frame;
  });
  return { ...input, frames, frame_age_s: typeof input.frame_age_s === 'number' && Number.isFinite(input.frame_age_s) && input.frame_age_s >= 0 ? input.frame_age_s : null };
}
