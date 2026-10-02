#!/usr/bin/env python3
"""Create a cask only after a published, notarized artifact is verified."""
import argparse
import hashlib
from pathlib import Path
import urllib.request
import subprocess

p=argparse.ArgumentParser()
p.add_argument('--artifact',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--version',default='0.2.0')
p.add_argument('--build',default='5')
p.add_argument('--app',type=Path,required=True)
a=p.parse_args()
subprocess.run(['xcrun','stapler','validate',str(a.app)],check=True)
subprocess.run(['spctl','--assess','--type','execute',str(a.app)],check=True)
url=f'https://github.com/Kian-hdr/disc-porter/releases/download/v{a.version}/Disc_Porter_{a.version}_arm64.zip'
expected=hashlib.sha256(a.artifact.read_bytes()).hexdigest()
with urllib.request.urlopen(url,timeout=60)as r:
 h=hashlib.sha256()
 while b:=r.read(1024*1024):h.update(b)
assert h.hexdigest()==expected,'Published artifact differs from reviewed artifact'
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(f'''cask "disc-porter" do
  version "{a.version},{a.build}"
  sha256 "{expected}"

  url "https://github.com/Kian-hdr/disc-porter/releases/download/v#{{version.csv.first}}/Disc_Porter_#{{version.csv.first}}_arm64.zip"
  name "Disc Porter"
  desc "Disc archiving with resumable checkpoints and local MCP control"
  homepage "https://github.com/Kian-hdr/disc-porter"

  depends_on arch: :arm64
  depends_on macos: ">= :sonoma"

  app "Disc Porter.app"

  uninstall quit: "dev.discporter.app"

  caveats do
    <<~EOS
      Created by Kian Konrad Tajbakhsh.
      MakeMKV is an external dependency for optical acquisition.
      Prepare to disconnect and stop MCP clients before updates or uninstall.
      Real-disc and target-player pilots remain pending in this early release.
    EOS
  end
end
''')
print('Cask generated from verified published bytes:',a.output.name)
