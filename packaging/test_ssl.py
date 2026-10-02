"""Verify default bundled roots and explicit override preservation in a frozen helper."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import certifi
p=argparse.ArgumentParser();p.add_argument('--helper',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
helper=a.helper.resolve();env={'PATH':'/usr/bin:/bin','HOME':os.environ['HOME'],'PYTHONNOUSERSITE':'1'}
def check(arguments,environment):
    result=json.loads(subprocess.check_output([str(helper),'selftest-ssl',*arguments],env=environment,text=True))
    assert result['ca_count']>0 and result['certificate_verification_required'] and result['hostname_verification_enabled'] and result['expected_override_preserved'],result
    return result
baseline=check([],env)
with tempfile.TemporaryDirectory(prefix='disc-porter-trust-') as temp:
    override=Path(temp)/'explicit-ca.pem';shutil.copy2(certifi.where(),override)
    explicit=check(['--expected-cert-file',str(override)],{**env,'SSL_CERT_FILE':str(override)})
a.output.write_text(json.dumps({'default':baseline,'explicit_override':explicit,'scope':'Actual frozen helper; no network request or credential; normal CA and hostname verification retained'},indent=2)+'\n')
print(json.dumps(baseline));print('Explicit CA override preserved')
