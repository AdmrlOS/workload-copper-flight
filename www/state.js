// All normalization is conservative: absent or invalid observations stay null.
const object = (value) => value !== null && typeof value === 'object' && !Array.isArray(value) ? value : {};
const text = (value) => typeof value === 'string' && value.trim() ? value : null;
const boolean = (value) => typeof value === 'boolean' ? value : null;
const nonnegative = (value) => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
const choice = (value, choices) => choices.includes(value) ? value : null;

const integer = (value) => Number.isSafeInteger(value) && value >= 0 ? value : null;
const vector = (value) => {
  const v = object(value);
  return ['x', 'y', 'z'].every((axis) => typeof v[axis] === 'number' && Number.isFinite(v[axis]))
    ? { x: v.x, y: v.y, z: v.z } : null;
};

const quaternion = (value) => {
  const q = object(value);
  if (!['x', 'y', 'z', 'w'].every((axis) => typeof q[axis] === 'number' && Number.isFinite(q[axis]))) return null;
  if (Math.abs(Math.hypot(q.x, q.y, q.z, q.w) - 1) > 0.01) return null;
  return { x: q.x, y: q.y, z: q.z, w: q.w };
};

function parseFrame(input) {
  const f = object(input);
  if (f.schema_version !== 1 || integer(f.seq) === null) return null;
  const graphics = object(f.graphics);
  return {
    schema_version: 1, seq: f.seq, sim_time_s: nonnegative(f.sim_time_s),
    position_m: vector(f.position_m), velocity_m_s: vector(f.velocity_m_s), rotation: quaternion(f.rotation),
    armed: boolean(f.armed), auto_enabled: boolean(f.auto_enabled),
    mode: text(f.mode), world: text(f.world),
    policy_prediction_m_s: vector(f.policy_prediction_m_s),
    policy_observation_seq: integer(f.policy_observation_seq),
    inference_backend: choice(f.inference_backend, ['cpu', 'cuda']),
    inference_count: integer(f.inference_count),
    graphics: { backend: text(graphics.backend), adapter_name: text(graphics.adapter_name) },
  };
}

export function safeDownloadURL(input) {
  const r = object(input);
  if (r.completed !== true || typeof r.id !== 'string' || !/^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$/.test(r.id)) return null;
  const expected = `/api/recordings/${r.id}/download`;
  return r.download_url === expected ? expected : null;
}

// Monotonic local timestamps; successful HTTP is not evidence of native progress.
export function observeProgress(previous, state, nowMs) {
  if (!state.frame) return null;
  const key = JSON.stringify([state.engine.revision, state.episode?.id, state.episode?.started_at]);
  const reset = !previous || previous.key !== key || state.frame.seq < previous.seq
    || (state.frame.sim_time_s !== null && previous.simTimeS !== null && state.frame.sim_time_s < previous.simTimeS)
    || (state.uptime_s !== null && previous.uptimeS !== null && state.uptime_s < previous.uptimeS);
  const prior = reset ? null : previous;
  return {
    key, seq: state.frame.seq, simTimeS: state.frame.sim_time_s, uptimeS: state.uptime_s,
    policySeq: state.frame.policy_observation_seq,
    lastPolicyProgressAt: prior && state.frame.policy_observation_seq !== null && prior.policySeq !== null
      && state.frame.policy_observation_seq >= prior.policySeq
      ? (state.frame.seq > prior.seq && state.frame.policy_observation_seq > prior.policySeq ? nowMs : prior.lastPolicyProgressAt)
      : null,
    firstSeenAt: prior?.firstSeenAt ?? nowMs,
    lastProgressAt: prior && state.frame.seq > prior.seq ? nowMs : prior?.lastProgressAt ?? null,
    receivedAt: nowMs,
  };
}

export const STALE_AFTER_S = 2;

export function resolveHealth(state, observation, nowMs, requestError = null) {
  const progressAgeS = observation ? Math.max(0, nowMs - (observation.lastProgressAt ?? observation.firstSeenAt)) / 1000 : null;
  const frameAgeS = state?.frame && observation && state.frame_age_s !== null
    ? state.frame_age_s + Math.max(0, nowMs - observation.receivedAt) / 1000 : null;
  let kind;
  if (requestError) kind = 'error';
  else if (!state) kind = 'connecting';
  else if (state.status === 'failed' || state.error) kind = 'failed';
  else if (state.status !== 'live') kind = state.status;
  else if (!state.frame || !observation) kind = 'waiting';
  else if ((frameAgeS !== null && frameAgeS >= STALE_AFTER_S) || progressAgeS >= STALE_AFTER_S) kind = 'stale';
  else if (frameAgeS === null) kind = 'unknown';
  else kind = observation.lastProgressAt !== null ? 'live' : 'waiting';
  const policyAgeS = observation?.lastPolicyProgressAt !== null && observation?.lastPolicyProgressAt !== undefined
    ? Math.max(0, nowMs - observation.lastPolicyProgressAt) / 1000 : null;
  return { kind, progressAgeS, frameAgeS, policyAgeS };
}

export function inferenceEvidence(state, health) {
  const requested = state?.configuration.inference ?? null;
  const backend = state?.frame?.inference_backend ?? null;
  const count = state?.frame?.inference_count ?? null;
  return {
    requested, backend, count,
    confirmed: health.kind === 'live' && backend !== null && Number.isFinite(health.policyAgeS)
      && health.policyAgeS < STALE_AFTER_S && state?.frame?.policy_observation_seq !== null
      && state?.frame?.policy_prediction_m_s !== null,
    mismatch: requested !== null && backend !== null && requested !== backend,
  };
}

export function parseState(input) {
  const value = object(input);
  if (!['starting', 'live', 'between_episodes', 'failed', 'stopped'].includes(value.status)) {
    throw new TypeError('Invalid runtime state: missing or unsupported status');
  }
  const engine = object(value.engine);
  const config = object(value.configuration);
  const episode = object(value.episode);
  return {
    status: value.status,
    error: text(value.error),
    engine: {
      native: boolean(engine.native),
      copper_version: text(engine.copper_version),
      source_revision: text(engine.source_revision),
      revision: text(engine.revision),
    },
    configuration: {
      world: choice(config.world, ['forest', 'urban']),
      inference: choice(config.inference, ['cpu', 'cuda']),
      autonomy: boolean(config.autonomy),
      episode_seconds: nonnegative(config.episode_seconds),
    },
    episode: text(episode.id) ? { id: episode.id, started_at: text(episode.started_at) } : null,
    frame_age_s: nonnegative(value.frame_age_s),
    frame: parseFrame(value.frame),
    recordings_known: Array.isArray(value.recordings),
    recordings_partial: Array.isArray(value.recordings) && value.recordings.some((recording) => !text(object(recording).id)),
    recordings: Array.isArray(value.recordings) ? value.recordings
      .filter((recording) => text(object(recording).id))
      .map((recording) => ({
        id: recording.id, completed: boolean(recording.completed),
        size_bytes: integer(recording.size_bytes), started_at: text(recording.started_at),
        ended_at: text(recording.ended_at), download_url: text(recording.download_url),
      })) : [],
    uptime_s: nonnegative(value.uptime_s),
  };
}
