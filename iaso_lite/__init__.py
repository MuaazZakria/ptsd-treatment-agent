"""
iaso_lite — a self-contained, trimmed port of the deterministic parts of the
IASO PTSD pipeline (iaso-ptsd-agent/iaso/), plus a Manus API client.

Only the pieces this experimental app needs are here: config, the BM25 evidence
index, the rule-based query builder + retrieval, the safety gate and compact
views, a JSON-repair helper, and the Manus client. The synthesis/appraisal step
that the real pipeline runs on TensorX is done here by the Manus agent
(see synthesis.py). NO dependency on the `iaso` package.
"""
