"""Publish a validated set of JSON files with rollback on a write failure.
Readers should reload only after index.json changes; old versions are retained outside checkout.
"""
import hashlib,json,os,pathlib,tempfile


def publish(directory, documents, history):
    directory, history = pathlib.Path(directory), pathlib.Path(history)
    for name,doc in documents.items():
        if name.endswith('.json') and 'records' in doc and (directory/name).exists():
            old=json.loads((directory/name).read_text())
            if old.get('records') and len(doc['records']) < .7*len(old['records']):
                raise ValueError('Suspicious record loss; review before replacing '+name)
    encoded = {name: json.dumps(doc,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode() for name,doc in documents.items()}
    # Serialize everything before touching current data, so malformed update output cannot truncate files.
    previous={name:(directory/name).read_bytes() if (directory/name).exists() else None for name in encoded}
    digest=hashlib.sha256(b''.join(v or b'' for k,v in sorted(previous.items()))).hexdigest()
    backup=history/digest;backup.mkdir(parents=True,exist_ok=True)
    for name,data in previous.items():
        if data is not None:(backup/name).write_bytes(data)
    directory.mkdir(parents=True,exist_ok=True)
    staged={}
    try:
        for name,data in encoded.items():
            with tempfile.NamedTemporaryFile(dir=directory,delete=False) as f:f.write(data);staged[name]=f.name
        for name in sorted(encoded,key=lambda x:x=='index.json'):os.replace(staged[name],directory/name)
    except Exception:
        for name,data in previous.items():
            if data is None:(directory/name).unlink(missing_ok=True)
            else:
                with tempfile.NamedTemporaryFile(dir=directory,delete=False) as f:f.write(data);restore=f.name
                os.replace(restore,directory/name)
        raise
    finally:
        for path in staged.values():pathlib.Path(path).unlink(missing_ok=True)
    return digest
