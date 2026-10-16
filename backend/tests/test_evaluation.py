"""Evaluation metric unit tests."""

from __future__ import annotations

from nexus.evaluation.runner import groundedness, keyword_recall, retrieval_relevance


def test_keyword_recall_perfect():
    assert keyword_recall("the cat sat on the mat", "the cat sat on the mat") == 1.0


def test_keyword_recall_partial():
    score = keyword_recall("cloud infrastructure costs rose sharply", "infrastructure costs were high")
    assert 0 < score < 1


def test_groundedness_high_when_supported():
    answer = "Infrastructure costs rose in Q3 and churn increased."
    evidence = ["Infrastructure costs rose in Q3 due to migration.", "SMB churn increased in Q3."]
    assert groundedness(answer, evidence) > 0.5


def test_groundedness_low_when_ungrounded():
    answer = "Unicorns manage our datacenter and quantum elves audit the ledger daily."
    evidence = ["Travel policy requires VP approval above 2000 dollars."]
    assert groundedness(answer, evidence) < 0.2


def test_retrieval_relevance():
    assert retrieval_relevance(["a.pdf", "b.pdf"], ["a.pdf", "c.pdf"]) == 0.5
    assert retrieval_relevance([], ["a.pdf"]) == 1.0
    # citation format includes locations: 'annual_report.pdf · p.1 · Page 1'
    assert retrieval_relevance(["annual_report.pdf"], ["annual_report.pdf · p.1 · Page 1"]) == 1.0
