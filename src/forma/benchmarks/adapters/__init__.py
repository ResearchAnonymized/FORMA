"""Source adapters.

The AWS mortgage adapter reads a local snapshot. Importing this package does
not open a network connection. Other source ids stay unimplemented.
"""

from __future__ import annotations

NOT_IMPLEMENTED = (
    "ted",
    "ocds",
    "medagentboard",
    "synthea",
    "fhir",
    "state_bench",
    "entcollabbench",
    "agentleak",
    "a2asecbench",
    "agentdojo",
)
IMPLEMENTED = ("aws_macs_mortgage",)


def adapter_status() -> dict:
    return {
        "implemented": list(IMPLEMENTED),
        "not_implemented": list(NOT_IMPLEMENTED),
        "note": (
            "aws_macs_mortgage loads the pinned local snapshot into candidate "
            "inventory records. It does not select anchors or generate cases."
        ),
    }


def load_source(source_id: str) -> dict:
    if source_id == "aws_macs_mortgage":
        from forma.benchmarks.adapters.aws_multiagent import inventory_document

        document = inventory_document()
        return {
            "source_id": source_id,
            "records": document["records"],
            "qualification_scope": document["qualification_scope"],
        }
    raise NotImplementedError(
        f"{source_id} has no adapter. This loader does not download benchmark corpora."
    )
