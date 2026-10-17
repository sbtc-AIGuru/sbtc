-- PostgreSQL schema equivalent to models.py; run against an empty database.

BEGIN;

CREATE TABLE document (
	doc_id BIGINT NOT NULL,
	url TEXT NOT NULL,
	status TEXT NOT NULL,
	parents JSONB NOT NULL,
	strategy TEXT,
	version TEXT,
	doc_type TEXT,
	classification_reason TEXT,
	classification_confidence TEXT,
	raw_sha256 TEXT,
	source_sha256 TEXT,
	source_length BIGINT,
	source_units BIGINT,
	excluded_spans JSONB,
	coverage JSONB,
	structural_boundary_rate FLOAT,
	input_line BIGINT,
	reason TEXT,
	source_fields JSONB NOT NULL,
	extra_data JSONB DEFAULT '{}' NOT NULL,
	PRIMARY KEY (doc_id),
	CONSTRAINT document_source_length_check CHECK (source_length >= 0),
	CONSTRAINT document_source_units_check CHECK (source_units >= 0),
	CONSTRAINT document_input_line_check CHECK (input_line >= 0),
	CONSTRAINT document_boundary_rate_check CHECK (structural_boundary_rate BETWEEN 0 AND 1)
);

CREATE TABLE chunk (
	chunk_id TEXT NOT NULL,
	doc_id BIGINT NOT NULL,
	parent_id TEXT NOT NULL,
	chunk_order INTEGER NOT NULL,
	start_char BIGINT NOT NULL,
	end_char BIGINT NOT NULL,
	chunk_text TEXT NOT NULL,
	unit_count BIGINT,
	oversized_reason TEXT,
	boundary_type TEXT,
	short_chunk_reason TEXT,
	overlap_units BIGINT,
	overlap_exception TEXT,
	retrieval_eligible BOOLEAN,
	source_position INTEGER NOT NULL,
	source_fields JSONB NOT NULL,
	extra_data JSONB DEFAULT '{}' NOT NULL,
	PRIMARY KEY (chunk_id),
	CONSTRAINT chunk_document_position_key UNIQUE (doc_id, source_position),
	CONSTRAINT chunk_source_position_check CHECK (source_position >= 0),
	CONSTRAINT chunk_order_check CHECK (chunk_order >= 0),
	CONSTRAINT chunk_start_char_check CHECK (start_char >= 0),
	CONSTRAINT chunk_end_char_check CHECK (end_char >= start_char),
	CONSTRAINT chunk_unit_count_check CHECK (unit_count >= 0),
	CONSTRAINT chunk_overlap_units_check CHECK (overlap_units >= 0),
	FOREIGN KEY(doc_id) REFERENCES document (doc_id) ON DELETE RESTRICT
);

COMMIT;
