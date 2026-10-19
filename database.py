import json
import os
import sqlite3
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import chromadb

import config
import llm
import metadata
from exif_extract import extract

class ExifDB:
    def __init__(self, cfg: dict):
        path = config.resolve(cfg["exif_db_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path, check_same_thread=False)
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS images ("
            "path TEXT PRIMARY KEY, name TEXT, mtime REAL, taken TEXT, raw_exif TEXT, "
            "keywords TEXT, description TEXT, embedded INTEGER DEFAULT 0, meta TEXT DEFAULT '')"
        )
        cols = {r[1] for r in self.con.execute("PRAGMA table_info(images)")}
        if "meta" not in cols:
            self.con.execute("ALTER TABLE images ADD COLUMN meta TEXT DEFAULT ''")
        self.con.commit()

    def get(self, path: str):
        return self.con.execute(
            "SELECT path,name,mtime,taken,raw_exif,keywords,description,embedded,meta FROM images WHERE path=?",
            (path,)
        ).fetchone()

    def upsert(self, path, name, mtime, taken, raw, keywords, description, meta):
        self.con.execute(
            "INSERT OR REPLACE INTO images(path,name,mtime,taken,raw_exif,keywords,description,meta,embedded) "
            "VALUES(?,?,?,?,?,?,?,?,0)", (path, name, mtime, taken, raw, keywords, description, meta))
        self.con.commit()

    def set_description(self, path, description):
        self.con.execute("UPDATE images SET description=?, embedded=0 WHERE path=?", (description, path))
        self.con.commit()

    def pending_embeddings(self):
        return self.con.execute(
            "SELECT path,name,description,meta FROM images "
            "WHERE embedded=0 AND description<>'' AND meta<>''").fetchall()

    def mark_embedded(self, paths):
        self.con.executemany("UPDATE images SET embedded=1 WHERE path=?", [(p,) for p in paths])
        self.con.commit()

    def reset_embedded(self):
        self.con.execute("UPDATE images SET embedded=0")
        self.con.commit()

    def delete(self, paths):
        self.con.executemany("DELETE FROM images WHERE path=?", [(p,) for p in paths])
        self.con.commit()

    def all_paths(self):
        return [r[0] for r in self.con.execute("SELECT path FROM images")]

    def by_path(self, path):
        return self.con.execute("SELECT path,name,taken,description FROM images WHERE path=?", (path,)).fetchone()

    def tag_count(self):
        tags = set()
        for (raw,) in self.con.execute("SELECT raw_exif FROM images WHERE keywords<>''"):
            try:
                tags.update(k.strip().lower() for k in json.loads(raw).get("keywords", []) if k.strip())
            except (ValueError, AttributeError, TypeError):
                pass
        return len(tags)

    def count(self):
        return self.con.execute("SELECT COUNT(*), SUM(description<>''), SUM(embedded) FROM images").fetchone()


def scan_files(cfg: dict):
    exts = {e.lower() for e in cfg["extensions"]}
    for folder in cfg["photo_folders"]:
        if not os.path.isdir(folder):
            continue
        if cfg["recursive"]:
            for root, _, files in os.walk(folder):
                for f in files:
                    if Path(f).suffix.lower() in exts:
                        yield os.path.join(root, f)
        else:
            for f in os.listdir(folder):
                if Path(f).suffix.lower() in exts:
                    yield os.path.join(folder, f)


def build_exif_db(cfg, db: ExifDB, log, stop, progress):
    files = list(scan_files(cfg))
    log(f"Found {len(files)} image(s).")
    present = set(files)
    removed = [p for p in db.all_paths() if p not in present]
    if removed:
        db.delete(removed)
        log(f"Removed {len(removed)} missing image(s) from the database.")
    errors = 0
    for i, path in enumerate(files, 1):
        if stop():
            log("Stopped.")
            return
        progress(i, len(files))
        name = os.path.basename(path)
        try:
            mtime = os.path.getmtime(path)
            row = db.get(path)
            if row and row[2] == mtime and row[6] and row[8]:
                continue
            try:
                info = extract(path)
            except Exception as e:
                log(f"[error] {name}: corrupt or unreadable EXIF/metadata ({type(e).__name__}: {e}); "
                    "continuing without metadata")
                errors += 1
                info = {"exif": {}, "xmp": "", "keywords": [], "taken": None,
                        "title": "", "description": ""}
            desc, meta = metadata.build(path, name, info)
            db.upsert(path, name, mtime, info["taken"],
                      json.dumps({"exif": info["exif"], "xmp": info["xmp"], "keywords": info["keywords"],
                                  "title": info["title"], "description": info["description"]},
                                 ensure_ascii=False),
                      " ".join(info["keywords"]), desc, json.dumps(meta, ensure_ascii=False))
            log(f"{name}: {desc or '(no description)'}")
        except Exception as e:
            errors += 1
            log(f"[error] {name}: skipped ({type(e).__name__}: {e})")
    log(f"EXIF database build finished" + (f" with {errors} error(s)." if errors else "."))


class VectorDB:
    def __init__(self, cfg: dict):
        path = config.resolve(cfg["vector_db_path"])
        path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(path))
        self.name = cfg["chroma_collection"]
        self.col = self.client.get_or_create_collection(self.name, metadata={"hnsw:space": "cosine"})

    def reset(self):
        self.client.delete_collection(self.name)
        self.col = self.client.get_or_create_collection(self.name, metadata={"hnsw:space": "cosine"})

    def remove_missing(self, valid: set):
        stale = [i for i in self.col.get()["ids"] if i not in valid]
        if stale:
            self.col.delete(ids=stale)


def build_vector_db(cfg, db: ExifDB, vdb: VectorDB, log, stop, progress, rebuild=False):
    if rebuild:
        vdb.reset()
        db.reset_embedded()
        log("Vector DB reset.")
    vdb.remove_missing(set(db.all_paths()))
    rows = db.pending_embeddings()
    log(f"{len(rows)} description(s) to embed.")
    size = max(1, int(cfg["embed_batch_size"]))
    workers = max(1, int(cfg.get("embed_workers", 4)))
    batches = [rows[s:s + size] for s in range(0, len(rows), size)]

    def embed_batch(batch):
        if stop():
            return None
        return llm.embed(cfg, ["search_document: " + r[2] for r in batch])

    done = 0
    # Only the HTTP calls run in threads; sqlite/chroma writes stay on this thread.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # Sliding window keeps memory bounded and lets Stop take effect quickly.
        pending = deque()
        it = iter(batches)

        def submit_next():
            b = next(it, None)
            if b is not None:
                pending.append((b, pool.submit(embed_batch, b)))

        for _ in range(workers * 2):
            submit_next()
        while pending:
            batch, fut = pending.popleft()
            try:
                vecs = fut.result()
            except llm.LLMError as e:
                log(f"[embedding error] {e}")
                for _, f in pending:
                    f.cancel()
                return
            if vecs is None or stop():
                log("Stopped.")
                for _, f in pending:
                    f.cancel()
                return
            vdb.col.upsert(
                ids=[r[0] for r in batch], embeddings=vecs, documents=[r[2] for r in batch],
                metadatas=[json.loads(r[3]) for r in batch])
            db.mark_embedded([r[0] for r in batch])
            done += len(batch)
            progress(done, len(rows))
            submit_next()
    log("Vector database build finished.")

