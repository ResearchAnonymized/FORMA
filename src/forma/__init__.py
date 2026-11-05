"""FORMA classifier and deterministic tactic evaluation."""

from forma.classifier import classify_invariant
from forma.inference import infer_verification_structure
from forma.tactics import applyTactic, evaluateScenario, suggestTactics
from forma.world_oracle import world_oracle as worldOracle

classifyInvariant = classify_invariant
inferVerificationStructure = infer_verification_structure

__all__ = [
    "applyTactic",
    "classify_invariant",
    "classifyInvariant",
    "evaluateScenario",
    "infer_verification_structure",
    "inferVerificationStructure",
    "suggestTactics",
    "worldOracle",
]
