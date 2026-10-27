#!/usr/bin/env python3
"""Read-only target sampling: no ptrace, control changes, deployment or file writes on target."""
import argparse
import json
from pathlib import Path
import subprocess

PROBE = r'''
import os,json,time,collections
from pathlib import Path
processes=[p for p in Path('/proc').iterdir() if p.name.isdigit() and (p/'cmdline').exists() and (p/'cmdline').read_bytes()==b'/opt/copper-flight/bin/quad-sim\0']
counts=collections.Counter()
def snapshot(p):
 def read(name):
  try: return (p/name).read_text()
  except (FileNotFoundError,PermissionError): return None
 return {'pid':int(p.name),'io':read('io'),'stat':read('stat'),'status':read('status')}
before=[snapshot(p) for p in processes]
started=time.monotonic()
for _ in range(80):
 for p in processes:
  try:
   for t in (p/'task').iterdir():
    counts[(p.name,t.name,(t/'comm').read_text().strip(),(t/'wchan').read_text().strip())]+=1
  except (FileNotFoundError,PermissionError): pass
 time.sleep(.05)
print(json.dumps({'wall_s':time.monotonic()-started,'sample_count':80,'before':before,'after':[snapshot(p) for p in processes],'threads':[{'pid':k[0],'tid':k[1],'name':k[2],'wchan':k[3],'samples':v} for k,v in counts.items()]}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    command = ["admrl", "exec", "-org", args.org, "-no-login", args.device, "--", "python3", "-c", PROBE]
    result = subprocess.run(command, text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise SystemExit(result.stderr + result.stdout)
    report = json.loads(result.stdout)
    report.update(organization_id=args.org, device_id=args.device, scope="read-only /proc sampling; no device changes")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
