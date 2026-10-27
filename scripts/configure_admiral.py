#!/usr/bin/env python3
"""Create a private flight Configuration; guarded fleet payloads are separate."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request

ORG = '7bd93e9d-c05a-4bbd-961f-afe73d8913e5'
CREDENTIAL = '8927588f-297a-424a-acae-6fc87e4a1de6'
FLEET = 'f2377f21-33ca-4588-9b51-838594cc22e6'
DEVICE = 'bcce44d5-ab16-4184-8d92-b5e6f7f4c8a1'
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def build_configuration(image):
    if not re.fullmatch(r'ghcr\.io/admrlos/workload-copper-flight@sha256:[0-9a-f]{64}', image):
        raise ValueError('an exact immutable workload-copper-flight image reference is required')
    return {
        'name': 'copper-flight',
        'description': 'Native ARM64 Copper forest-flight simulation and ViTFly CUDA inference with browser WebGL visualization and persistent native logs; no physical drone actuation',
        'tags': ['copper', 'arm64', 'autonomy', 'simulation', 'flight'],
        'spec': {
            'image': image, 'desiredState': 'RUNNING', 'registry_credential_id': CREDENTIAL,
            'command': [], 'environment': {
                'PORT': '8080', 'FLIGHT_INFERENCE': 'cuda', 'FLIGHT_WORLD': 'forest',
                'FLIGHT_DISPLAY_MODE': 'headless', 'FLIGHT_DATA_DIR': '/data/copper-flight',
                'FLIGHT_EPISODE_SECONDS': '45', 'FLIGHT_KEEP_RUNS': '2',
                'FLIGHT_MAX_BYTES': '8589934592',
            },
            'mounts': [], 'ports': [{'port': 8080, 'protocol': 'tcp'}],
            'volumes': {'data': {'source': '', 'destination': '/data', 'options': ['rbind', 'rw']}},
            'options': {
                'tty': False, 'all_devices_allowed': True, 'host_namespaces': [],
                'host_resolvconf': False, 'host_hosts_file': False, 'read_only_root': False,
                'ephemeral_root': False, 'privileged': False, 'capabilities': [],
                'new_privileges': False, 'parent_cgroup_devices': False,
                'exposeDBus': False, 'disableHostBluetooth': False,
            },
        },
    }


def normalized_spec(value, path=()):
    if isinstance(value, dict):
        value = dict(value)
        empty = ('command', 'mounts') if not path else ('host_namespaces',) if path == ('options',) else ()
        for key in empty:
            if value.get(key) is None:
                value[key] = []
        return {k: normalized_spec(v, (*path, k)) for k, v in value.items()}
    if isinstance(value, list):
        values = [normalized_spec(v, path) for v in value]
        if path in {('ports',), ('mounts',), ('options', 'host_namespaces'), ('options', 'capabilities')} or \
                (len(path) == 3 and path[0] == 'volumes' and path[-1] == 'options'):
            values.sort(key=lambda v: json.dumps(v, sort_keys=True, allow_nan=False))
        return values
    return value


def verify_configuration(document, payload):
    expected = json.dumps(normalized_spec(payload['spec']), sort_keys=True, allow_nan=False)
    actual = json.dumps(normalized_spec(document.get('spec')), sort_keys=True, allow_nan=False)
    if actual != expected:
        raise RuntimeError('full Configuration read-back differs from requested spec')
    if document.get('metadata', {}).get('name') != payload['name']:
        raise RuntimeError('Configuration read-back name differs')
    status = document.get('status') or {}
    if status.get('fleetUsage') or status.get('fleets'):
        raise RuntimeError('new Configuration unexpectedly has fleet assignments')


def build_fleet_patch(document, expected_selection, target, device_ids):
    if set(target) != {'id', 'version'} or not isinstance(target['id'], str) or not UUID.fullmatch(target['id']) or \
            not isinstance(target['version'], str) or not re.fullmatch(r'[1-9][0-9]*', target['version']):
        raise ValueError('fleet target must be a structural UUID and explicit positive version string')
    metadata = document.get('metadata') or {}
    if metadata.get('id') != FLEET or not isinstance(metadata.get('resourceVersion'), str) or not metadata['resourceVersion']:
        raise RuntimeError('wrong fleet or missing optimistic-concurrency revision')
    if (document.get('spec') or {}).get('configuration') != expected_selection:
        raise RuntimeError('fleet Configuration changed; refusing to overwrite another selection')
    if device_ids != [DEVICE]:
        raise RuntimeError('canary scope must contain only the approved Jetson, exactly once')
    return {'spec': {'configuration': dict(target)}}, metadata['resourceVersion']


def build_fleet_rollback(document, expected_selection, saved_prior_document, device_ids):
    """Restore only the selection in the caller's saved pre-canary fleet document."""
    if not isinstance(saved_prior_document, dict):
        raise RuntimeError('an explicitly saved prior fleet document is required')
    metadata = saved_prior_document.get('metadata')
    spec = saved_prior_document.get('spec')
    if not isinstance(metadata, dict) or metadata.get('id') != FLEET or \
            not isinstance(metadata.get('resourceVersion'), str) or not metadata['resourceVersion'] or \
            not isinstance(spec, dict):
        raise RuntimeError('wrong or incomplete saved prior fleet document')
    prior = spec.get('configuration')
    if not isinstance(prior, dict) or set(prior) != {'id', 'version'} or \
            not isinstance(prior['id'], str) or not UUID.fullmatch(prior['id']) or \
            not isinstance(prior['version'], str) or not re.fullmatch(r'latest|[1-9][0-9]*', prior['version']):
        raise ValueError('saved prior fleet selection is missing or invalid')
    # Reuse every forward guard, including an immutable current canary selection.
    patch, revision = build_fleet_patch(document, expected_selection, expected_selection, device_ids)
    patch['spec']['configuration'] = dict(prior)
    return patch, revision


def verify_fleet_selection(document, expected):
    if document.get('metadata', {}).get('id') != FLEET or document.get('spec', {}).get('configuration') != expected:
        raise RuntimeError('fleet read-back did not select the exact requested Configuration version')


def api(path, payload=None, method=None, if_match=None):
    headers = {'X-Organization-ID': ORG, 'X-API-Token-ID': os.environ['ADMRL_API_TOKEN_ID'],
               'X-API-Secret-Key': os.environ['ADMRL_API_SECRET_KEY'],
               'User-Agent': 'Mozilla/5.0 Copper-Flight-Admiral', 'Content-Type': 'application/json'}
    if if_match is not None:
        headers['If-Match'] = if_match
    request = urllib.request.Request('https://api.admrl.co/v1' + path, headers=headers,
                                     data=None if payload is None else json.dumps(payload, allow_nan=False).encode(),
                                     method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    return result.get('data', result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', nargs='?')
    parser.add_argument('--credential-check', action='store_true')
    parser.add_argument('--apply', action='store_true', help='Create one NEW Configuration; never deploy')
    parser.add_argument('--output', type=Path, default=Path('artifacts/admiral-configuration.json'))
    args = parser.parse_args()
    credential = api('/registry-credentials/' + CREDENTIAL)
    if credential.get('name') != 'GHCR- Alex PAT' or credential.get('registry') != 'ghcr.io' or not credential.get('has_password'):
        raise RuntimeError('the expected saved Alex GHCR credential could not be confirmed')
    print(json.dumps({k: credential.get(k) for k in ('id', 'name', 'registry', 'username', 'has_password')}))
    if args.credential_check and args.image is None:
        return
    payload = build_configuration(args.image or '')
    if not args.apply:
        print(json.dumps(payload, indent=2))
        return
    result = subprocess.run(['admrl', 'get', 'configurations', '--org', ORG, '--no-login', '-o', 'json'],
                            check=True, capture_output=True, text=True)
    listed = json.loads(result.stdout)
    if any(row['name'] == payload['name'] for row in listed['items']):
        raise RuntimeError('copper-flight already exists; refusing duplicate creation or overwrite')
    created = api('/configurations', payload)
    configuration_id = created['id']
    document = api('/configurations/' + configuration_id + '/document')
    verify_configuration(document, payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + '\n')
    print(json.dumps({'id': configuration_id, 'name': payload['name'], 'image': payload['spec']['image'], 'fleetUsage': []}))


if __name__ == '__main__':
    main()
