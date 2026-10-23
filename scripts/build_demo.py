"""Regenerate the single-file entry point from current source; no stale duplicate app."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
s=(root/'index.html').read_text()
s=s.replace('<link rel="stylesheet" href="./styles.css?v=9" />','<style>\n'+(root/'styles.css').read_text()+'\n</style>')
pilot=json.dumps(json.loads((root/'data/pilot.json').read_text()),separators=(',',':')).replace('<','\\u003c')
streets=json.dumps(json.loads((root/'data/manhattan-streets.json').read_text()),separators=(',',':'),ensure_ascii=False).replace('<','\\u003c')
s=s.replace('<script src="./experience-core.js?v=9"></script>','<script>window.STREETWISE_PILOT='+pilot+';window.STREETWISE_STREETS='+streets+';</script>\n<script>\n'+(root/'experience-core.js').read_text()+'\n</script>')
for name in ['app.js','route-client.js','urban-layers.js','explore-map.js','center-map.js']:s=s.replace(f'<script src="./{name}?v=9"></script>','<script>\n'+(root/name).read_text()+'\n</script>')
(root/'STREETWISE_single_file_demo.html').write_text(s)
print('Built single-file demo with real pilot snapshot. Internet still required for map assets and live routing.')
