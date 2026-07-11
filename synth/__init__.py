"""Reproducible synthetic marketing-asset generation for evaluation.

The gold (6) and silver (30) corpora are far too small to measure NLP /
rule-engine improvements without overfitting. This package generates
labeled, schema-shaped assets *programmatically* from general marketing
and regulatory language patterns (never copied from the gold/silver
surface text), so held-out synthetic validation catches regressions and
credits real generalization rather than memorization.

Everything is seeded and reproducible: same seed -> byte-identical
corpus. See ``synth/generator.py``.
"""
