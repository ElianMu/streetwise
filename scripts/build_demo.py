"""Regenerate the single-file entry point from current source; no stale duplicate app."""
import json, re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
s=(root/'index.html').read_text()
s=re.sub(r'<link rel="stylesheet" href="\./styles\.css(\?v=\d+)?" />',lambda m:'<style>\n'+(root/'styles.css').read_text()+'\n</style>',s)
pilot=json.dumps(json.loads((root/'data/pilot.json').read_text()),separators=(',',':')).replace('<','\\u003c')
streets=json.dumps(json.loads((root/'data/manhattan-streets.json').read_text()),separators=(',',':'),ensure_ascii=False).replace('<','\\u003c')
inline=lambda name:'<script>\n'+(root/name).read_text()+'\n</script>'
s=re.sub(r'<script src="\./experience-core\.js(\?v=\d+)?"></script>',lambda m:'<script>window.STREETWISE_PILOT='+pilot+';window.STREETWISE_STREETS='+streets+';</script>\n'+inline('experience-core.js'),s)
# Every local script referenced by index.html is inlined, whatever its cache-busting version.
s=re.sub(r'<script src="\./([\w-]+\.js)(\?v=\d+)?"></script>',lambda m:inline(m.group(1)),s)
assert not re.search(r'<script src="\./',s),'a local script was not inlined'
(root/'STREETWISE_single_file_demo.html').write_text(s)
print('Built single-file demo with real pilot snapshot. Internet still required for map assets, routing and urban data tiles.')
