import { Quaternion } from './vendor/three-r182/build/three.core.js';

export function poseFromFrame(frame) {
  const p = frame?.position_m;
  const q = frame?.rotation;
  if (!p || !q || !['x', 'y', 'z'].every((axis) => typeof p[axis] === 'number' && Number.isFinite(p[axis]))) return null;
  if (!['x', 'y', 'z', 'w'].every((axis) => typeof q[axis] === 'number' && Number.isFinite(q[axis]))) return null;
  if (Math.abs(Math.hypot(q.x, q.y, q.z, q.w) - 1) > 0.01) return null;
  return { position: { ...p }, rotation: { ...q } };
}

export function sourceConnection(snapshot) {
  const { state, health } = snapshot;
  if (health.kind !== 'live') return { live: false, reason: health.kind === 'stale' ? 'Source stale · pose frozen' : `Source ${health.kind} · pose frozen` };
  if (state?.engine?.native !== true) return { live: false, reason: 'Native source unconfirmed' };
  if (state?.frame?.world !== 'forest') return { live: false, reason: 'Forest scene does not match the observed world' };
  if (!state?.frame?.rotation) return { live: false, reason: 'Native orientation unavailable' };
  if (!poseFromFrame(state?.frame)) return { live: false, reason: 'Native pose unavailable' };
  return { live: true, reason: 'Native pose connected · interpolated visualization' };
}

export function ingestSample(history, snapshot) {
  const { state, health, observation } = snapshot;
  const pose = poseFromFrame(state?.frame);
  if (!pose || !observation || state.status !== 'live' || state.engine.native !== true || state.frame.world !== 'forest'
    || !['live', 'waiting'].includes(health.kind) || health.frameAgeS === null || health.frameAgeS >= 2) return history;
  const key = JSON.stringify([state.engine.revision, state.episode?.id, state.episode?.started_at, observation.firstSeenAt, state.frame.world]);
  const atMs = observation.receivedAt;
  const reset = !history || history.key !== key || state.frame.seq < history.seq || atMs - history.samples.at(-1).atMs >= 2000;
  const previous = reset ? null : history;
  if (previous && state.frame.seq === previous.seq) return history;
  return {
    key, seq: state.frame.seq,
    samples: [...(previous?.samples ?? []), { atMs, seq: state.frame.seq, pose }].slice(-24),
    trace: [...(previous?.trace ?? []), { ...pose.position }].slice(-256),
  };
}

// Target times outside the observed interval hold an endpoint; never extrapolate.
export function samplePose(history, targetMs) {
  const samples = history?.samples;
  if (!samples?.length || !Number.isFinite(targetMs)) return null;
  const first = samples[0];
  const last = samples.at(-1);
  if (targetMs <= first.atMs) return { pose: first.pose, interpolated: false };
  if (targetMs >= last.atMs) return { pose: last.pose, interpolated: false };
  for (let index = 1; index < samples.length; index += 1) {
    const next = samples[index];
    if (targetMs <= next.atMs) {
      const previous = samples[index - 1];
      const t = (targetMs - previous.atMs) / (next.atMs - previous.atMs);
      return { pose: interpolatePose(previous.pose, next.pose, t), interpolated: t > 0 && t < 1 };
    }
  }
  return { pose: last.pose, interpolated: false };
}

// Stabilized observation camera only. Never changes a native vehicle transform.
export function chaseView(pose) {
  if (!pose?.position) return null;
  const p = pose.position;
  return {
    position: { x: p.x + 0.9, y: p.y + 0.6, z: p.z + 2.4 },
    target: { x: p.x, y: p.y + 0.25, z: p.z - 1.6 },
  };
}

export function interpolatePose(start, end, fraction) {
  if (!start || !end || !Number.isFinite(fraction)) return null;
  const t = Math.max(0, Math.min(1, fraction));
  const q = new Quaternion(start.rotation.x, start.rotation.y, start.rotation.z, start.rotation.w)
    .slerp(new Quaternion(end.rotation.x, end.rotation.y, end.rotation.z, end.rotation.w), t).normalize();
  return {
    position: Object.fromEntries(['x', 'y', 'z'].map((axis) => [axis, start.position[axis] + (end.position[axis] - start.position[axis]) * t])),
    rotation: { x: q.x, y: q.y, z: q.z, w: q.w },
  };
}
