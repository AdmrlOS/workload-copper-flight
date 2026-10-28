"""Synthetic local browser fixture; NOT native execution/deployment evidence."""
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from service import RecordingStore, StateStore, make_server
from test_depth_fullres import RUN, OTHER, raster, descriptor, event, rows
from test_service import frame


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = RecordingStore(Path(tmp).resolve() / 'runs')
        pose = dict(frame(), wall_time_s=3, sim_time_s=2, depth_raster=descriptor())
        legacy = dict(frame(), wall_time_s=3, sim_time_s=2,
                      depth_preview=dict(raster(), width=32, height=24, sampling='nearest-cell-center', data='000eff' * 256))
        for run_id, values in [(RUN, [event(), pose]), (OTHER, [legacy])]:
            run = store.begin(run_id)
            (run / 'telemetry.jsonl').write_bytes(rows(*values))
            store.complete(run_id)
        state = StateStore()
        state.begin(RUN)
        state.publish(event())
        state.publish(pose)
        with state.lock:
            state.data['recordings'] = store.summaries()
            state.data['status'] = 'stopped'
        server = make_server(state, store, ROOT / 'www', host='127.0.0.1', port=0)
        print(json.dumps({'url': f'http://127.0.0.1:{server.server_port}', 'synthetic': True}), flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()


if __name__ == '__main__':
    main()
