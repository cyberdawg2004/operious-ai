"""Payload formatters for governed defect report dispatch."""

from __future__ import annotations

from typing import Any, Protocol


class DefectReportRecord(Protocol):
    @property
    def title(self) -> str: ...

    @property
    def executive_summary(self) -> str: ...

    @property
    def failure_pattern(self) -> str: ...

    @property
    def root_cause_hypothesis(self) -> str: ...

    @property
    def incident_count(self) -> int: ...

    @property
    def confidence(self) -> float: ...

    @property
    def evidence_quality(self) -> str: ...


def format_jira_payload(report: DefectReportRecord) -> dict[str, Any]:
    """Format a defect report as a Jira issue create request."""

    return {
        "fields": {
            "summary": report.title,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "Executive Summary:\n"
                                    f"{report.executive_summary}\n\n"
                                    "Failure Pattern:\n"
                                    f"{report.failure_pattern}\n\n"
                                    "Root Cause Hypothesis:\n"
                                    f"{report.root_cause_hypothesis}\n\n"
                                    f"Incidents: {report.incident_count} | "
                                    f"Confidence: {report.confidence:.0%} | "
                                    "Evidence Quality: "
                                    f"{report.evidence_quality}"
                                ),
                            }
                        ],
                    }
                ],
            },
            "issuetype": {"name": "Bug"},
            "priority": {"name": "High"},
        }
    }


def format_linear_payload(report: DefectReportRecord) -> dict[str, Any]:
    """Format a defect report as a Linear IssueCreate GraphQL mutation."""

    description = (
        f"## Executive Summary\n{report.executive_summary}\n\n"
        f"## Failure Pattern\n{report.failure_pattern}\n\n"
        f"## Root Cause Hypothesis\n{report.root_cause_hypothesis}\n\n"
        f"*Incidents*: {report.incident_count} | "
        f"*Confidence*: {report.confidence:.0%} | "
        f"*Evidence Quality*: {report.evidence_quality}"
    )
    return {
        "query": (
            "mutation IssueCreate($input: IssueCreateInput!) {"
            "  issueCreate(input: $input) { success } "
            "}"
        ),
        "variables": {
            "input": {
                "title": report.title,
                "description": description,
                "priority": 1,
            }
        },
    }


__all__ = ["DefectReportRecord", "format_jira_payload", "format_linear_payload"]
