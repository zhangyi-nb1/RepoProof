from rag_ingest.ingest import IngestError, ingest_documents
from rag_ingest.loader import health, load_documents

# v2 schema — the ambiguous has_frontmatter of v1 is SPLIT into two
# booleans with a public truth table (see /consumer/public_examples/):
#   frontmatter_present: the pinned upstream recognised (and stripped)
#       a front-matter block — true even when the block is empty
#   metadata_nonempty:   the parsed metadata has at least one key
INGEST_RECORD_FIELDS = ("doc_id", "frontmatter_present", "metadata_nonempty", "metadata", "content")

__all__ = ["INGEST_RECORD_FIELDS", "IngestError", "health", "ingest_documents", "load_documents"]
