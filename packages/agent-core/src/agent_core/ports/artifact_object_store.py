from typing import Protocol

from agent_core.domain.artifact_objects import (
    ArtifactObjectDeleteRequest,
    ArtifactObjectDeleteResult,
    ArtifactObjectExpectation,
    ArtifactObjectPutRequest,
    ArtifactObjectReceipt,
    ArtifactObjectVerification,
)
from agent_core.ports.artifact_payload_read import ArtifactPayloadObjectReadPort


class ArtifactObjectStorePort(ArtifactPayloadObjectReadPort, Protocol):
    def put_if_absent(self, request: ArtifactObjectPutRequest) -> ArtifactObjectReceipt: ...

    def verify(self, expectation: ArtifactObjectExpectation) -> ArtifactObjectVerification: ...

    def read_verified(self, expectation: ArtifactObjectExpectation) -> bytes: ...

    def delete_if_version(
        self,
        request: ArtifactObjectDeleteRequest,
    ) -> ArtifactObjectDeleteResult: ...
