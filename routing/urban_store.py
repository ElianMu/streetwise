"""Read-only offline SQLite snapshots: bounded page cache, streaming decompression, no network on queries."""
import contextlib,gzip,hashlib,json,os,pathlib,shutil,sqlite3,tempfile,threading
ROOT=pathlib.Path(__file__).resolve().parents[1]
_lock=threading.Lock();_ready={}

def manifest(name):
    path=ROOT/'data/urban'/name/'manifest.json'
    if not path.exists():raise RuntimeError(name+' indexed snapshot is unavailable')
    return json.loads(path.read_text())

def database(name):
    m=manifest(name);key=(name,m['sha256'])
    with _lock:
        if key not in _ready:
            source=ROOT/'data/urban'/name/m['database']
            target=pathlib.Path(tempfile.gettempdir())/'streetwise-indexed-urban'/m['sha256']/(name+'.sqlite')
            target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists() or target.stat().st_size!=m['database_bytes']:
                with source.open('rb') as f:
                    if hashlib.file_digest(f,'sha256').hexdigest()!=m['sha256']:raise RuntimeError(name+' snapshot checksum mismatch')
                fd,stage=tempfile.mkstemp(dir=target.parent)
                try:
                    with os.fdopen(fd,'wb') as out,gzip.open(source,'rb') as data:shutil.copyfileobj(data,out,1024*1024)
                    if pathlib.Path(stage).stat().st_size!=m['database_bytes']:raise RuntimeError(name+' snapshot decompression size mismatch')
                    os.replace(stage,target)
                finally:pathlib.Path(stage).unlink(missing_ok=True)
            _ready[key]=target
        return _ready[key]

@contextlib.contextmanager
def connection(name):
    db=sqlite3.connect(database(name).as_uri()+'?mode=ro&immutable=1',uri=True,timeout=10)
    try:
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA cache_size=-1024');db.execute('PRAGMA mmap_size=0');db.execute('PRAGMA temp_store=FILE')
        yield db
    finally:db.close()
