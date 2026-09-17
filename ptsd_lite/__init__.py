"""
ptsd_lite — a self-contained, trimmed port of the deterministic parts of a
PTSD treatment-evidence pipeline, plus a Manus API client.

Only the pieces this experimental app needs are here: config, the BM25 evidence
index, the rule-based query builder + retrieval, the safety gate and compact
views, a JSON-repair helper, and the Manus client. The synthesis/appraisal step
that the original pipeline runs on TensorX is done here by the Manus agent
(see synthesis.py) - this package has no dependency on that original pipeline.
"""
