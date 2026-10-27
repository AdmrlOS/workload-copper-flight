#!/usr/bin/env python3
"""Read-only release evidence, using native clocks rather than browser FPS.

This verifies one device only; passing is not a fleet-scale benchmark or native
Copper replay verification. No deployment, restart or device writes occur.
"""
import argparse
import http.client
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.parse
import urllib.request


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def analyze_frames(episodes, min_sim_rate=1.0, min_source_hz=30.0):
    """Assess actual distinct source frames; never join clocks across episodes."""
    wall = sim = 0.0
    intervals = samples = 0
    invalid = gaps = 0
    policy_progress = False
    depth_sequences, rasters = set(), set()
    for episode, received in episodes.items():
        index = {}
        for frame in received:
            if not isinstance(frame, dict) or type(frame.get('seq')) is not int or frame['seq'] < 0:
                invalid += 1
                continue
            if not all(finite(frame.get(k)) and frame[k] >= 0 for k in ('sim_time_s', 'wall_time_s')):
                invalid += 1
                continue
            index[frame['seq']] = frame
        rows = sorted(index.values(), key=lambda f: f['seq'])
        samples += len(rows)
        for row in rows:
            preview = row.get('depth_preview')
            if isinstance(preview, dict) and type(preview.get('source_seq')) is int and preview['source_seq'] >= 0:
                data = preview.get('data')
                if isinstance(data, str) and re.fullmatch('[0-9a-f]{1536}', data):
                    depth_sequences.add((episode, preview['source_seq']))
                    rasters.add(data)
        for a, b in zip(rows, rows[1:]):
            dt = b['wall_time_s'] - a['wall_time_s']
            ds = b['sim_time_s'] - a['sim_time_s']
            if dt <= 0 or ds < 0:
                invalid += 1
                continue
            if b['seq'] != a['seq'] + 1:
                gaps += 1
            wall += dt
            sim += ds
            intervals += 1
            if type(a.get('policy_observation_seq')) is int and type(b.get('policy_observation_seq')) is int:
                policy_progress |= b['policy_observation_seq'] > a['policy_observation_seq']
    rate = sim / wall if wall else None
    hz = intervals / wall if wall else None
    gates = {
        'valid_native_clocks': invalid == 0 and wall > 0,
        'continuous_observed_source': gaps == 0,
        'simulation_realtime_factor': rate is not None and rate >= min_sim_rate,
        'observed_source_hz': hz is not None and hz >= min_source_hz,
        'policy_publication_progress': policy_progress,
        'changing_observed_depth': len(depth_sequences) >= 2 and len(rasters) >= 2,
    }
    return {
        'passed': all(gates.values()), 'failed_gates': [k for k, passed in gates.items() if not passed],
        'scope': 'single-device native telemetry; not browser pacing or fleet scale',
        'episodes': len(episodes), 'actual_unique_samples': samples,
        'native_wall_span_s': wall, 'simulation_span_s': sim,
        'simulation_realtime_factor': rate, 'observed_source_hz': hz,
        'source_gap_pairs': gaps, 'invalid_frames': invalid,
        'observed_depth_sequences': len(depth_sequences), 'distinct_depth_rasters': len(rasters),
        'required_min_sim_rate': min_sim_rate, 'required_min_source_hz': min_source_hz,
        'native_replay_verified': False,
    }


def read_json(origin, path):
    request = urllib.request.Request(origin + path, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=8) as response:
        expected_length = response.headers.get('Content-Length')
        if expected_length is not None:
            expected_length = int(expected_length)
            if expected_length < 0:
                raise ValueError('invalid response Content-Length')
        data = response.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise ValueError('telemetry response exceeds 8 MiB')
    if expected_length is not None and len(data) != expected_length:
        raise http.client.IncompleteRead(data, max(0, expected_length - len(data)))
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    def numeric(value, convert):
        result = convert(value)
        if not finite(result):
            raise ValueError('nonfinite or oversized JSON number')
        return result

    try:
        result = json.loads(data, object_pairs_hook=pairs,
                            parse_float=lambda value: numeric(value, float),
                            parse_int=lambda value: numeric(value, int),
                            parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON constant')))
    except (UnicodeError, RecursionError) as error:
        raise ValueError('invalid JSON encoding or nesting') from error
    stack = [(result, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > 64:
            raise ValueError('JSON nesting exceeds 64 levels')
        if isinstance(value, (dict, list)):
            stack.extend((child, depth + 1) for child in (value.values() if isinstance(value, dict) else value))
    if not isinstance(result, dict):
        raise ValueError('response must be an object')
    return result


def observe(origin, expected_revision, seconds=90, min_sim_rate=1.0, min_source_hz=30.0,
            startup_timeout=10.0):
    parsed = urllib.parse.urlsplit(origin)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('use a credential-free HTTP(S) origin')
    if not re.fullmatch('[0-9a-f]{40}', expected_revision):
        raise ValueError('expected revision must be the exact 40-character Git SHA')
    if not finite(seconds) or not 10 <= seconds <= 3600:
        raise ValueError('observation seconds must be in 10..3600')
    if not finite(startup_timeout) or not 1 <= startup_timeout <= 60:
        raise ValueError('startup timeout must be finite wall seconds in 1..60')
    if not finite(min_sim_rate) or not 0 < min_sim_rate <= 100 or not finite(min_source_hz) or not 0 < min_source_hz <= 10000:
        raise ValueError('invalid explicit acceptance thresholds')
    spec = importlib.util.spec_from_file_location('native_acceptance', Path(__file__).resolve().parents[1] / 'tests/check_image.py')
    assert spec is not None and spec.loader is not None
    acceptance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(acceptance)
    origin = origin.rstrip('/')
    started = time.monotonic()
    episodes, errors = {}, []
    cursor = episode = None
    first = True
    hardware_observations = 0
    hardware_episodes = set()
    healthy_since = last_progress = last_rows = None
    prior_observed_at = None
    healthy_durations, healthy_windows = {}, {}
    prior_state = None
    episode_armed = False
    transition_since = started
    transition_limit_s = startup_timeout  # Cold initialization and arming, bounded in wall time.
    transition_expired = False
    terminal_live = False
    while time.monotonic() - started < seconds:
        terminal_live = False
        try:
            query = '' if cursor is None else '?' + urllib.parse.urlencode({'after_seq': cursor, 'episode_id': episode})
            batch = read_json(origin, '/api/telemetry' + query)
            if batch.get('engine', {}).get('revision') != expected_revision:
                raise ValueError('unexpected source revision')
            current = batch.get('episode', {}).get('id')
            rows = batch.get('frames')
            if not isinstance(current, str) or not isinstance(rows, list):
                raise ValueError('invalid telemetry envelope')
            if not first:
                episodes.setdefault(current, []).extend(rows)
            first = False  # Exclude the pre-existing history returned at connection.
            now = time.monotonic()
            if current != episode:
                healthy_since = last_progress = last_rows = None
                prior_state = None
                episode_armed = False
                # Initial HTTP errors must not restart the original startup budget.
                transition_since = started if episode is None else now
                transition_expired = False
            if rows and (cursor is None or current != episode or rows[-1]['seq'] > cursor):
                last_rows = now
            if rows:
                cursor = rows[-1]['seq']
            elif current != episode:
                cursor = None
            episode = current
            state = read_json(origin, '/api/state')
            if state.get('engine', {}).get('revision') != expected_revision:
                raise ValueError('unexpected live-state revision')
            if state.get('episode', {}).get('id') != current:
                raise ValueError('telemetry/state episode mismatch')
            statuses = (batch.get('status'), state.get('status'))
            if any(status not in ('live', 'starting', 'between_episodes') for status in statuses):
                raise ValueError('native source failed or stopped')
            transitioning = any(status != 'live' for status in statuses)
            if not transitioning:
                age = batch.get('frame_age_s')
                if not finite(age) or not 0 <= age < 2:
                    raise ValueError('telemetry is stale or missing')
                age = state.get('frame_age_s')
                if not finite(age) or not 0 <= age < 2:
                    raise ValueError('live state is stale or missing')
                frame = state.get('frame') or {}
                sim_time = frame.get('sim_time_s')
                transitioning = (not episode_armed and finite(sim_time) and 0 <= sim_time < 4)
            if transitioning and transition_since is None:
                transition_since = now
                transition_expired = False
            if (transition_since is not None and not transition_expired and
                    now - transition_since >= transition_limit_s):
                transition_expired = True
                # Retain the failed gate once, without hiding later real hardware/progress.
                errors.append({'wall_s': now - started, 'error':
                               f'native arming/episode transition deadline exceeded '
                               f'(required within {startup_timeout:g} wall seconds)'})
            if transitioning:
                healthy_since = last_progress = None
                prior_state = None
            else:
                acceptance.validate_live_state(state, 'cuda')
                episode_armed = True
                transition_since = None
                frame = state['frame']
                if prior_state is None:
                    healthy_since = last_progress = now
                elif all(frame[k] > prior_state[k] for k in ('seq', 'sim_time_s', 'policy_observation_seq')):
                    last_progress = now
                    # Credit only consecutive validated progress in this episode.
                    # Startup, transitions and frozen polls add no healthy coverage.
                    if last_rows is not None and now - last_rows < 2:
                        healthy_durations[current] = healthy_durations.get(current, 0.0) + now - prior_observed_at
                        healthy_windows[current] = max(healthy_windows.get(current, 0.0), now - healthy_since)
                if now - last_progress >= 2:
                    raise ValueError('native simulation/policy progress froze')
                prior_state = frame
                prior_observed_at = now
                hardware_observations += 1
                hardware_episodes.add(current)
                terminal_live = (last_rows is not None and now - last_rows < 2 and
                                 last_progress > healthy_since and now - last_progress < 2)
        except (OSError, http.client.HTTPException, ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError) as error:
            healthy_since = last_progress = None
            prior_state = None
            errors.append({'wall_s': time.monotonic() - started, 'error': str(error)[:300]})
        time.sleep(.2)
    report = analyze_frames(episodes, min_sim_rate, min_source_hz)
    if errors:
        report['failed_gates'].append('error_free_http_observation')
    if hardware_observations < 2:
        report['failed_gates'].append('observed_cuda_nvidia_auto')
    if report['native_wall_span_s'] < seconds * .5:
        report['failed_gates'].append('sustained_native_observation')
    if not terminal_live:
        report['failed_gates'].append('terminal_fresh_native_observation')
    total_healthy = sum(healthy_durations.values())
    required_window = min(5.0, seconds * .5)
    if total_healthy < seconds * .5:
        report['failed_gates'].append('sustained_healthy_hardware_policy_observation')
    if max(healthy_windows.values(), default=0.0) < required_window:
        report['failed_gates'].append('sustained_same_episode_hardware_policy_progress')
    report.update(passed=not report['failed_gates'], revision=expected_revision,
                  observed_wall_s=time.monotonic() - started, errors=errors,
                  healthy_wall_s=total_healthy, episode_healthy_wall_s=healthy_durations,
                  episode_healthy_progress_window_s=healthy_windows,
                  required_same_episode_progress_s=required_window,
                  required_startup_timeout_s=startup_timeout,
                  hardware_observations=hardware_observations,
                  hardware_episodes=len(hardware_episodes))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--expected-revision', required=True)
    parser.add_argument('--seconds', type=float, default=90)
    parser.add_argument('--startup-timeout', type=float, default=10.0,
                        help='cold initialization/arming and episode transition budget in wall seconds (1..60; default: 10)')
    parser.add_argument('--min-sim-rate', type=float, default=1.0)
    parser.add_argument('--min-source-hz', type=float, default=30)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = observe(args.url, args.expected_revision, args.seconds, args.min_sim_rate, args.min_source_hz,
                         startup_timeout=args.startup_timeout)
    except (OSError, http.client.HTTPException, ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError) as error:
        report = {'passed': False, 'error': str(error)[:500], 'native_replay_verified': False}
    payload = json.dumps(report, indent=2, allow_nan=False) + '\n'
    args.report.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=args.report.parent, prefix='.readiness-', delete=False) as output:
            temporary = output.name
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, args.report)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    print(payload, end='')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
