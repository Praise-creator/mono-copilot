from dataclasses import dataclass, field

@dataclass
class Message:
    role: str
    content: str

@dataclass
class CopilotState:
    messages: list[Message] = field(default_factory=list)
    active_project: str | None = None
    workflow_stage: str | None = None
    run_conunt: int = 0
    loading: bool = False
    current_document: str | None = None