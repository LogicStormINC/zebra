"""Controlled public source facts through the actual G3 producer; no model or business Run."""

import json
import runpy
from pathlib import Path

root = Path(__file__).resolve().parents[5]
helpers = runpy.run_path(str(root / "tests/agent_integrations/test_ag_ui_standard_projection.py"))
EventType = helpers["EventType"]
frames, _ = helpers["project"](
    [
        (EventType.HARNESS_ATTEMPT_STARTED, {}),
        (
            EventType.PLAN_UPDATED,
            {"steps": [{"step_id": "s", "content": "Inspect evidence", "status": "in_progress"}]},
        ),
        (
            EventType.TOOL_CALL_PROPOSED,
            {"tool_call_id": "t", "tool_name": "inspect", "arguments": {"path": "public"}},
        ),
        (EventType.TOOL_EXECUTION_STARTED, {"tool_call_id": "t", "tool_name": "inspect"}),
        (
            EventType.TOOL_EXECUTION_COMPLETED,
            {
                "tool_call_id": "t",
                "output": "Observed public evidence",
                "metadata": {
                    "delivery": True,
                    "schema_version": "2",
                    "content_parts": [
                        {
                            "id": "image-1",
                            "type": "image",
                            "state": "ready",
                            "artifactId": "00000000-0000-4000-8000-000000000001",
                            "mimeType": "image/png",
                            "alt": "Public evidence",
                            "width": 640,
                            "height": 480,
                            "thumbnailArtifactId": "00000000-0000-4000-8000-000000000003",
                        },
                        {
                            "id": "video-1",
                            "type": "video",
                            "state": "ready",
                            "artifactId": "00000000-0000-4000-8000-000000000004",
                            "mimeType": "video/mp4",
                            "title": "Public video",
                            "width": 1280,
                            "height": 720,
                            "durationMs": 1234,
                            "posterArtifactId": "00000000-0000-4000-8000-000000000003",
                            "captionsArtifactId": "00000000-0000-4000-8000-000000000005",
                            "transcriptArtifactId": "00000000-0000-4000-8000-000000000006",
                            "captionsLanguage": "en",
                        },
                        {
                            "id": "external-1",
                            "type": "external_video",
                            "state": "ready",
                            "sourceUrl": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                            "title": "External evidence",
                            "description": "Public source video",
                        },
                        {
                            "id": "chart-1",
                            "type": "chart",
                            "state": "ready",
                            "specType": "vega-lite",
                            "specVersion": "6",
                            "specArtifactId": "00000000-0000-4000-8000-000000000007",
                            "fallbackImageArtifactId": "00000000-0000-4000-8000-000000000003",
                            "title": "Evidence chart",
                            "description": "Public chart",
                        },
                        {
                            "id": "file-1",
                            "type": "file",
                            "state": "ready",
                            "artifactId": "00000000-0000-4000-8000-000000000002",
                            "mimeType": "text/plain",
                            "name": "Evidence file",
                        },
                    ],
                },
            },
        ),
        (
            EventType.PLAN_UPDATED,
            {"steps": [{"step_id": "s", "content": "Inspect evidence", "status": "completed"}]},
        ),
        (
            EventType.ANSWER_COMMITTED,
            {
                "assistant_message": "Public answer from actual producer",
                "delivery_assessment": {"status": "complete"},
            },
        ),
        (EventType.TURN_COMPLETED, {}),
    ]
)
print(json.dumps(frames))
