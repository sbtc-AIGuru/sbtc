"""Incremental Lucene writer pinned to the bundled Anserini/Lucene runtime."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .backend import JAVA_SEARCH_LOCK
from .models import ANALYZER_PROFILE, FIELDS, INDEX_SCHEMA_VERSION
from .runtime import configure_java


class DirectLucenePartition:
    """Append pre-tokenized Anserini JSON records and commit durable batch receipts."""

    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        spec_hash: str,
        partition: str,
        mode: str,
        ram_buffer_mib: int = 16,
    ):
        if mode not in {"create", "append"}:
            raise ValueError("Writer mode must be explicit: create or append")
        if not run_id or not spec_hash or not partition or ram_buffer_mib <= 0:
            raise ValueError("Writer identity and positive RAM buffer are required")
        configure_java()
        from pyserini.pyclass import autoclass

        self.path = Path(path).resolve()
        self.run_id = run_id
        self.spec_hash = spec_hash
        self.partition = partition
        self.closed = False
        if mode == "create":
            if self.path.exists() and any(self.path.iterdir()):
                raise RuntimeError(f"Refusing CREATE over a nonempty Lucene partition: {self.path}")
        else:
            if not self.path.exists():
                raise RuntimeError(f"Cannot APPEND to a missing Lucene partition: {self.path}")
            previous = self.read_committed(self.path)
            self._validate_identity(previous["user_data"])

        self.FSDirectory = autoclass("org.apache.lucene.store.FSDirectory")
        self.Paths = autoclass("java.nio.file.Paths")
        self.IndexWriter = autoclass("org.apache.lucene.index.IndexWriter")
        self.IndexWriterConfig = autoclass("org.apache.lucene.index.IndexWriterConfig")
        self.OpenMode = autoclass("org.apache.lucene.index.IndexWriterConfig$OpenMode")
        self.WhitespaceAnalyzer = autoclass("org.apache.lucene.analysis.core.WhitespaceAnalyzer")
        self.Field = autoclass("org.apache.lucene.document.Field")
        self.FieldType = autoclass("org.apache.lucene.document.FieldType")
        self.IndexOptions = autoclass("org.apache.lucene.index.IndexOptions")
        self.StringReader = autoclass("java.io.StringReader")
        from jnius import cast
        self.cast = cast
        self.BM25Similarity = autoclass("org.apache.lucene.search.similarities.BM25Similarity")
        self.SerialMergeScheduler = autoclass("org.apache.lucene.index.SerialMergeScheduler")
        self.Args = autoclass("io.anserini.index.IndexCollection$Args")
        self.Generator = autoclass("io.anserini.index.generator.DefaultLuceneDocumentGenerator")
        self.JsonDocument = autoclass("io.anserini.collection.JsonCollection$Document")
        self.HashMap = autoclass("java.util.HashMap")

        self.directory = self.FSDirectory.open(self.Paths.get(str(self.path)))
        self.whitespace_analyzer = self.WhitespaceAnalyzer()
        config = self.IndexWriterConfig(self.whitespace_analyzer)
        config.setOpenMode(self.OpenMode.CREATE if mode == "create" else self.OpenMode.APPEND)
        config.setSimilarity(self.BM25Similarity())
        config.setRAMBufferSizeMB(float(ram_buffer_mib))
        config.setUseCompoundFile(False)
        config.setMergeScheduler(self.SerialMergeScheduler())
        config.setCommitOnClose(False)

        args = self.Args()
        args.storePositions = False
        args.storeContents = False
        args.storeDocvectors = False
        args.storeRaw = False
        args.pretokenized = True
        self.generator = self.Generator(args)
        self.auxiliary_field_type = self.FieldType()
        self.auxiliary_field_type.setStored(False)
        self.auxiliary_field_type.setIndexOptions(self.IndexOptions.DOCS_AND_FREQS)
        self.auxiliary_field_type.freeze()
        with JAVA_SEARCH_LOCK:
            self.writer = self.IndexWriter(self.directory, config)
            if mode == "create":
                self._set_commit_data({
                    "run_id": self.run_id,
                    "spec_hash": self.spec_hash,
                    "schema_version": str(INDEX_SCHEMA_VERSION),
                    "analyzer_profile": ANALYZER_PROFILE,
                    "partition": self.partition,
                    "batch_id": "__initial__",
                    "cumulative_live_docs": "0",
                })
                self.writer.commit()

    @staticmethod
    def read_committed(path: Path) -> dict:
        configure_java()
        from pyserini.pyclass import autoclass

        FSDirectory = autoclass("org.apache.lucene.store.FSDirectory")
        Paths = autoclass("java.nio.file.Paths")
        DirectoryReader = autoclass("org.apache.lucene.index.DirectoryReader")
        with JAVA_SEARCH_LOCK:
            directory = FSDirectory.open(Paths.get(str(Path(path).resolve())))
            try:
                reader = DirectoryReader.open(directory)
                try:
                    iterator = reader.getIndexCommit().getUserData().entrySet().iterator()
                    user_data = {}
                    while iterator.hasNext():
                        entry = iterator.next()
                        user_data[str(entry.getKey())] = str(entry.getValue())
                    return {"documents": int(reader.numDocs()), "user_data": user_data}
                finally:
                    reader.close()
            finally:
                directory.close()

    def _validate_identity(self, user_data: dict[str, str]) -> None:
        expected = {
            "run_id": self.run_id,
            "spec_hash": self.spec_hash,
            "schema_version": str(INDEX_SCHEMA_VERSION),
            "analyzer_profile": ANALYZER_PROFILE,
            "partition": self.partition,
        }
        mismatches = {key: (user_data.get(key), value) for key, value in expected.items() if user_data.get(key) != value}
        if mismatches:
            raise RuntimeError(f"Lucene commit identity mismatch for {self.partition}: {mismatches}")

    def _set_commit_data(self, values: dict[str, str]) -> None:
        data = self.HashMap()
        for key, value in values.items():
            data.put(str(key), str(value))
        self.writer.setLiveCommitData(data.entrySet())

    def add_jsonl(self, path: Path) -> tuple[int, str]:
        """Add every JSON object in a durable batch partition file without committing."""
        if self.closed:
            raise RuntimeError("Lucene writer is closed")
        digest = hashlib.sha256()
        count = 0
        try:
            with Path(path).open("rb") as source, JAVA_SEARCH_LOCK:
                for line_number, payload in enumerate(source, 1):
                    digest.update(payload)
                    if not payload.strip():
                        raise ValueError(f"Empty prepared JSONL line at {path}:{line_number}")
                    document = self.JsonDocument.fromString(payload.decode("utf-8"))
                    parsed = json.loads(payload)
                    lucene_document = self.generator.createDocument(document)
                    for field in FIELDS:
                        if field == "contents" or field not in parsed:
                            continue
                        value = parsed[field]
                        if not isinstance(value, str):
                            raise ValueError(f"Prepared field {field!r} must be a string at {path}:{line_number}")
                        reader = self.cast("java.io.Reader", self.StringReader(value))
                        lucene_document.add(self.Field(field, reader, self.auxiliary_field_type))
                    self.writer.addDocument(lucene_document)
                    count += 1
        except BaseException:
            self.rollback()
            raise
        return count, digest.hexdigest()

    def commit_batch(self, *, batch_id: str, stage_sha256: str, event_digest: str) -> dict:
        if self.closed:
            raise RuntimeError("Lucene writer is closed")
        if not batch_id or len(stage_sha256) != 64 or len(event_digest) != 64:
            raise ValueError("A batch ID and SHA-256 digests are required for a commit receipt")
        with JAVA_SEARCH_LOCK:
            live_docs = int(self.writer.getDocStats().numDocs)
            self._set_commit_data({
                "run_id": self.run_id,
                "spec_hash": self.spec_hash,
                "schema_version": str(INDEX_SCHEMA_VERSION),
                "analyzer_profile": ANALYZER_PROFILE,
                "partition": self.partition,
                "batch_id": batch_id,
                "stage_sha256": stage_sha256,
                "event_digest": event_digest,
                "cumulative_live_docs": str(live_docs),
            })
            self.writer.commit()
        committed = self.read_committed(self.path)
        self._validate_identity(committed["user_data"])
        if committed["user_data"].get("batch_id") != batch_id:
            raise RuntimeError(f"Lucene did not persist expected batch receipt: {self.partition}/{batch_id}")
        if committed["documents"] != live_docs:
            raise RuntimeError(f"Lucene committed live-document count mismatch: {committed['documents']} != {live_docs}")
        return committed

    def rollback(self) -> None:
        if self.closed:
            return
        with JAVA_SEARCH_LOCK:
            try:
                self.writer.rollback()
            finally:
                self.whitespace_analyzer.close()
                self.directory.close()
                self.closed = True

    def close(self) -> None:
        if self.closed:
            return
        with JAVA_SEARCH_LOCK:
            try:
                self.writer.close()
            finally:
                self.whitespace_analyzer.close()
                self.directory.close()
                self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close() if exc_type is None else self.rollback()
