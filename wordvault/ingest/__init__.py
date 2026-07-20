"""
wordvault.ingest — importing a legacy .docx library (roadmap stage 4).

Implements Phases A and B of DESIGN.md section 6:

  Phase A (extract.py + pipeline.py)
      Walk a folder of .docx files, extract plain text, create one document
      + one snapshot revision per file (timestamped with the FILE's dates,
      so the library is ordered by when the material was actually written).
      Files whose text exactly duplicates an earlier file are collapsed —
      only their path is remembered.

  Phase B (similar.py + pipeline.py)
      Fingerprint every ingested document with MinHash and propose groups
      of near-duplicates / successive drafts, stored as 'pending'
      similarity groups for the author to review in Phase C (a later
      stage's review screen).

Nothing is ever discarded: every distinct text becomes a document, and
"distilling" is connecting and ordering, not deleting.
"""

from wordvault.ingest.pipeline import Ingestor, IngestStats

__all__ = ["Ingestor", "IngestStats"]
