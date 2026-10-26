"""The action registry: the ONLY things a digital employee is able to do.

Each action declares typed inputs/outputs, whether it changes the outside world (side effect),
whether it moves money, and which roles may use it (least privilege).
"""

from collections.abc import Callable
from dataclasses import dataclass, field


class PolicyError(Exception):
    """A rule was violated at run time (e.g. file outside sandbox). Never retried."""


class TransientError(Exception):
    """A temporary failure (timeout, injected chaos). Retried."""


@dataclass
class ActionSpec:
    name: str
    fn: Callable
    description: str
    inputs: dict[
        str, str
    ]  # param -> type ("str", "number", "bool", "date", "list", "dict", "any"); "?" suffix = optional
    outputs: dict[str, str]
    side_effect: bool = False
    money: bool = False
    roles: tuple[str, ...] = ("ap",)
    halts: bool = False  # ends the task and hands it to a human

    def allowed(self, role: str) -> bool:
        """'*' means a general skill any digital employee may use."""
        return "*" in self.roles or role in self.roles

    def required(self) -> set[str]:
        return {k for k, t in self.inputs.items() if not t.endswith("?")}

    def public(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "side_effect": self.side_effect,
            "money": self.money,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "roles": list(self.roles),
        }


REGISTRY: dict[str, ActionSpec] = {}


def action(
    name: str,
    *,
    description: str,
    inputs: dict[str, str],
    outputs: dict[str, str],
    side_effect: bool = False,
    money: bool = False,
    roles: tuple[str, ...] = ("ap",),
    halts: bool = False,
):
    def deco(fn: Callable) -> Callable:
        REGISTRY[name] = ActionSpec(name, fn, description, inputs, outputs, side_effect, money, roles, halts)
        return fn

    return deco


def catalog(role: str | None = None) -> list[dict]:
    return [s.public() for s in REGISTRY.values() if role is None or s.allowed(role)]


@dataclass
class ExecContext:
    """What an action can see while it runs."""

    task: dict
    employee: dict
    settings: dict
    mode: str  # live | shadow
    step_id: str = ""
    flags: list = field(default_factory=list)  # flags raised so far in this task
    outputs: dict = field(default_factory=dict)  # outputs of earlier steps
    seen: list | None = None  # invoices processed earlier in the same batch (duplicate check)

    def flag(self, type_: str, severity: str, message: str, evidence: str = "") -> dict:
        return {"type": type_, "severity": severity, "message": message, "evidence": evidence, "step_id": self.step_id}
