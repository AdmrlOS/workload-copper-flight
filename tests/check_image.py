#!/usr/bin/env python3
"""Evidence checks for the real native flight image; no synthetic runtime data."""
import math
import json
import argparse
import http.client
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request


def number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def vector(value):
    return isinstance(value, dict) and all(number(value.get(k)) for k in ('x', 'y', 'z'))


def episode_id(state):
    episode = state.get('episode')
    value = episode.get('id') if isinstance(episode, dict) else None
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or not value.strip():
        raise ValueError('a bounded nonempty string episode ID is required')
    return value


def validate_live_state(state, expected_backend, allow_software=False):
    episode_id(state)
    frame = state.get('frame') or {}
    graphics = frame.get('graphics') or {}
    if state.get('status') != 'live' or state.get('engine', {}).get('native') is not True:
        raise ValueError('native runtime is not live')
    age = state.get('frame_age_s')
    if not number(age) or not 0 <= age <= 5:
        raise ValueError('native observation is stale or missing')
    if frame.get('schema_version') != 1 or type(frame.get('seq')) is not int or frame['seq'] < 0:
        raise ValueError('missing native observation sequence')
    if not number(frame.get('sim_time_s')) or frame['sim_time_s'] < 4:
        raise ValueError('autonomous start has not been observed')
    if frame.get('armed') is not True or frame.get('auto_enabled') is not True:
        raise ValueError('native flight is not armed in AUTO')
    if frame.get('inference_backend') != expected_backend or state.get('configuration', {}).get('inference') != expected_backend:
        raise ValueError('requested and observed inference backends do not match')
    if type(frame.get('policy_observation_seq')) is not int or frame['policy_observation_seq'] <= 0:
        raise ValueError('no actual learned-policy publication observed')
    if 'inference_count' not in frame or (frame['inference_count'] is not None and
            (type(frame['inference_count']) is not int or frame['inference_count'] <= 0)):
        raise ValueError('missing or invalid exact inference count')
    if not all(vector(frame.get(k)) for k in ('position_m', 'velocity_m_s', 'policy_prediction_m_s')):
        raise ValueError('native flight or learned-policy output is missing/nonfinite')
    if not isinstance(graphics.get('backend'), str) or not graphics['backend'].strip() or \
            not isinstance(graphics.get('adapter_name'), str) or not graphics['adapter_name'].strip():
        raise ValueError('graphics adapter/backend has not been observed')
    software = any(k in graphics['adapter_name'].lower() for k in ('llvmpipe', 'lavapipe', 'swiftshader', 'software', 'cpu'))
    if software and not allow_software:
        raise ValueError('software rendering cannot establish native hardware graphics')
    # These fields must come from actual RenderAdapterInfo, never requested configuration.
    if not allow_software and (graphics['backend'] != 'Vulkan' or
                               type(graphics.get('vendor_id')) is not int or graphics['vendor_id'] != 0x10de or
                               graphics.get('device_type') not in ('IntegratedGpu', 'DiscreteGpu') or
                               graphics['adapter_name'].strip().lower() in ('unknown', 'noop', 'none')):
        raise ValueError('observed NVIDIA Vulkan hardware adapter evidence is required')
    return {k: frame[k] for k in ('seq', 'sim_time_s', 'position_m', 'velocity_m_s',
                                  'inference_backend', 'inference_count', 'policy_observation_seq', 'graphics')}


def verify_progress(before, after):
    first, last = before.get('frame') or {}, after.get('frame') or {}
    if episode_id(before) != episode_id(after):
        raise ValueError('cannot compare progress across different episodes')
    for field in ('seq', 'sim_time_s', 'policy_observation_seq'):
        if not number(first.get(field)) or not number(last.get(field)) or last[field] <= first[field]:
            raise ValueError('native simulation/policy did not advance: ' + field)


def validate_archive(source):
    names, aliases, slabs, total = set(), [], [], 0
    kwargs = {'fileobj': source} if hasattr(source, 'read') else {'name': source}
    with tarfile.open(mode='r:*', **kwargs) as archive:
        for member in archive:
            p = PurePosixPath(member.name)
            name = str(p)
            if p.is_absolute() or '..' in p.parts or not p.parts or name in names:
                raise ValueError('unsafe or duplicate archive member')
            names.add(name)
            if len(names) > 4096 or member.size < 0:
                raise ValueError('archive limits exceeded')
            total += member.size
            if total > 8 * 1024 ** 3:
                raise ValueError('archive size limit exceeded')
            if member.isfile():
                if re.search(r'_0\.copper$', name):
                    slabs.append(name)
            elif member.issym():
                target = PurePosixPath(member.linkname)
                if target.is_absolute() or len(target.parts) != 1 or '..' in target.parts:
                    raise ValueError('unsafe native alias')
                aliases.append(str(p.parent / target))
            elif not member.isdir():
                raise ValueError('unsupported archive entry type')
    expected = {'flight_controller_sim_0.copper', 'flight_compute_sim_0.copper'}
    if {PurePosixPath(p).name for p in slabs} != expected or len(slabs) != 2 or \
            len({PurePosixPath(p).parent for p in slabs}) != 1 or \
            any(target not in names for target in aliases):
        raise ValueError('required first-slab inventory and confined aliases are missing or invalid')
    return {'members': len(names), 'native_first_slabs': len(slabs), 'safe_aliases': len(aliases),
            'uncompressed_bytes': total}


def read_state(base_url):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate state JSON key')
            result[key] = value
        return result

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('nonfinite state JSON number')
        return result

    def reject_constant(_):
        raise ValueError('nonfinite state JSON constant')

    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or \
            parsed.username is not None or parsed.password is not None or \
            parsed.path not in {'', '/'} or parsed.query or parsed.fragment:
        raise ValueError('use a credential-free HTTP(S) origin, without a path or query')
    request = urllib.request.Request(base_url.rstrip('/') + '/api/state',
                                     headers={'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=5) as response:
        data = response.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError('state response exceeds the size limit')
    try:
        state = json.loads(data, object_pairs_hook=pairs, parse_float=finite_float,
                           parse_constant=reject_constant)
    except (UnicodeError, RecursionError) as error:
        raise ValueError('invalid state JSON') from error
    if not isinstance(state, dict):
        raise ValueError('state response must be an object')
    return state


def observe_live(base_url, backend, allow_software=False, timeout=300,
                 observe_seconds=2, interval=.25, expected_revision=None):
    if backend not in {'cpu', 'cuda'} or not all(number(n) for n in (timeout, observe_seconds, interval)) or \
            not .05 <= observe_seconds < timeout <= 3600 or not .01 <= interval <= 5:
        raise ValueError('invalid observation backend or timing bounds')
    if expected_revision is not None and not re.fullmatch('[0-9a-f]{40}', expected_revision):
        raise ValueError('expected revision must be a full lowercase Git SHA')
    started = time.monotonic()
    first = first_evidence = None
    first_at = started
    last_error = 'no valid observations received'
    while time.monotonic() - started < timeout:
        try:
            state = read_state(base_url)
            evidence = validate_live_state(state, backend, allow_software)
            if expected_revision is not None and state['engine'].get('revision') != expected_revision:
                raise ValueError('runtime revision differs from the requested release')
            now = time.monotonic()
            if first is None or episode_id(state) != episode_id(first):
                first, first_evidence, first_at = state, evidence, now
            elif now - first_at >= observe_seconds:
                verify_progress(first, state)
                return {'passed': True, 'scope': 'native-simulation-and-observed-policy-progress',
                        'native_replay_verified': False, 'hardware_graphics_required': not allow_software,
                        'episode_id': episode_id(state),
                        'revision': state['engine'].get('revision'),
                        'elapsed_s': now - started, 'first': first_evidence, 'last': evidence}
        except (OSError, http.client.HTTPException, ValueError, AttributeError, TypeError) as error:
            first = None
            last_error = str(error)
        time.sleep(min(interval, max(0, timeout - (time.monotonic() - started))))
    raise TimeoutError('native acceptance deadline exceeded: ' + last_error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='HTTP(S) origin of the real flight workload')
    parser.add_argument('--backend', choices=['cpu', 'cuda'], required=True)
    parser.add_argument('--allow-software', action='store_true',
                        help='Explicit local software-graphics acceptance; not Jetson GPU proof')
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--observe-seconds', type=float, default=2)
    parser.add_argument('--interval', type=float, default=.25)
    parser.add_argument('--expected-revision')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    try:
        result = observe_live(args.url, args.backend, allow_software=args.allow_software,
                              timeout=args.timeout, observe_seconds=args.observe_seconds,
                              interval=args.interval, expected_revision=args.expected_revision)
    except (OSError, http.client.HTTPException, ValueError) as error:
        result = {'passed': False, 'scope': 'native-simulation-and-observed-policy-progress',
                  'native_replay_verified': False, 'error': str(error)}
    payload = json.dumps(result, indent=2, allow_nan=False) + '\n'
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=args.report.parent,
                                             prefix='.flight-acceptance-', delete=False) as stream:
                temporary = stream.name
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, args.report)
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
    print(payload, end='')
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
