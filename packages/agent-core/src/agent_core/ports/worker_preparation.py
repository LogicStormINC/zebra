"""A durable preparation slice is progress, not a failed execution attempt."""

from agent_core.ports.task_projection_checkpoints import CheckpointNotReady


class PreparationAdvanced(CheckpointNotReady):
    """Continue under the same lease only after committing a bounded prefix.

    Missing dependencies use CheckpointNotReady instead: claiming progress for a
    missing prerequisite would spin forever and hide an actionable configuration
    failure. Coordinates refer to one versioned checkpoint and captured source.
    Equality means the prefix reached that source but readiness verification
    exceeded its budget; the next slice must verify again before execution.
    """

    def __init__(self, checkpoint_key: str, through_sequence: int, highwater: int) -> None:
        if (
            not isinstance(checkpoint_key, str)
            or not checkpoint_key.strip()
            or len(checkpoint_key) > 512
            or type(through_sequence) is not int
            or type(highwater) is not int
            or not 0 <= through_sequence <= highwater
        ):
            raise ValueError("invalid durable preparation progress")
        self.checkpoint_key = checkpoint_key
        self.through_sequence = through_sequence
        self.highwater = highwater
        super().__init__("Worker preparation committed a bounded prefix")
