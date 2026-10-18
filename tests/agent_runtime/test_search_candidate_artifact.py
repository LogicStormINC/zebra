import json
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256

import pytest
from agent_core.domain.identifiers import new_session_id, new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_core.domain.web import parse_web_target
from agent_runtime import LocalToolGateway
from agent_runtime.tool_output_projection import project_tool_output
from agent_runtime.web_search import _normalize_response
from agent_storage.artifact_payload_reads import LocalArtifactPayloadReader
from agent_storage.artifact_payloads import SQLiteArtifactPayloadStore
from agent_tools import ToolOutputProjector
from agent_tools.builtin.artifacts import ArtifactReadTool
from agent_tools.web_search import WebSearchRequest, WebSearchResponse, WebSearchTool
from pydantic import TypeAdapter

NOW = datetime(2026, 10, 18, tzinfo=UTC)


def call(name='web.search', **arguments):
    return ToolCall(tool_call_id=new_tool_call_id(), name=name,
                    arguments=arguments or {'query': 'bounded query', 'limit': 5}, created_at=NOW)


def response(items=None):
    request = WebSearchRequest(tool_call_id='test',
                endpoint=parse_web_target('https://search.example.org/search'), query='q', limit=5)
    items = items if items is not None else [
        {'url': f'https://example.org/{i}', 'title': f'result {i}', 'content': f'evidence {i}'}
        for i in range(7)]
    body = json.dumps({'results': items}).encode()
    return _normalize_response(body, request, len(body))


class SavedTransport:
    def __init__(self, saved):
        self.saved = saved
        self.requests = 0

    def execute(self, _request):
        self.requests += 1
        return self.saved


def test_same_response_extra_candidates_are_authorized_artifact_not_inline(tmp_path):
    transport = SavedTransport(response())
    sid = new_session_id()
    store = SQLiteArtifactPayloadStore(tmp_path / 'payloads.sqlite')
    gateway = LocalToolGateway(tmp_path, current_session_id=str(sid), artifact_payload_store=store,
                web_search_endpoint='https://search.example.org/search',
                web_search_transport=transport)
    result = gateway.execute(call())
    uri = result.metadata['artifact_uri']
    inline = result.output.split('\n\n[Complete output:', 1)[0]
    assert 'result 4' in inline and 'result 5' not in inline
    assert result.metadata['result_count'] == 5
    assert result.metadata['total_count'] == 7
    assert '_search_candidate_output' not in result.metadata
    reader = LocalArtifactPayloadReader(store)
    complete = reader.read_payload_bytes(sid, uri).decode()
    assert complete.startswith(inline) and 'result 6' in complete
    assert result.metadata['output_sha256'] == sha256(complete.encode()).hexdigest()
    assert result.metadata['output_coverage'] == {
        'included_ranges': [[0, len(inline)]], 'total_characters': len(complete)}
    read_call = call('artifacts.read', uri=uri, query='result 6', max_characters=1000)
    read = ArtifactReadTool(reader, sid).handle(read_call)
    assert read.status is ToolCallStatus.EXECUTED and 'result 6' in read.output
    foreign = ArtifactReadTool(reader, new_session_id()).handle(read_call)
    assert foreign.status is ToolCallStatus.FAILED
    assert transport.requests == 1  # reading candidates never executes another search.
    gateway.close()


def test_candidate_filtering_order_caps_and_native_wire_roundtrip():
    items = [{'url': 'http://unsafe.example/', 'title': 'bad', 'content': 'bad'},
             {'url': 'https://127.0.0.1/x', 'title': 'private', 'content': 'private'}]
    items += [{'url': f'https://example.org/{i}#fragment', 'title': f' title {i} ',
               'content': ' bounded  snippet '} for i in range(30)]
    items.insert(4, dict(items[3]))
    result = response(items)
    assert len(result.results) == 5 and len(result.candidates) == 20
    assert result.results == result.candidates[:5]
    assert result.candidates_truncated is True
    assert all('#' not in x.url and '127.0.0.1' not in x.url for x in result.candidates)
    assert result.candidates[0].title == 'title 0'
    assert TypeAdapter(WebSearchResponse).validate_python(asdict(result)) == result
    huge = response([{'url': f'https://example.org/{i}', 'title': 't' * 200,
                      'content': 's' * 1000} for i in range(25)])
    assert sum(len(x.url) + len(x.title) + len(x.snippet) for x in huge.candidates) <= 20_000
    assert huge.candidates_truncated


def test_large_snapshot_preview_never_leaks_candidates_beyond_inline_prefix():
    saved = response()
    transport = SavedTransport(saved)
    tool = WebSearchTool(parse_web_target('https://search.example.org/search'), transport)
    raw = tool.handle(call())
    persisted = []
    projector = ToolOutputProjector(lambda text, _name: persisted.append(text) or 'artifact://proof',
                                    max_model_characters=256)
    projected = project_tool_output(projector, call(), raw)
    assert 'result 5' not in projected.output and 'result 6' not in projected.output
    assert 'result 6' in persisted[0]
    assert all(0 <= a <= b <= len(raw.output)
               for a, b in projected.metadata['output_coverage']['included_ranges'])
    no_artifact = project_tool_output(None, call(), raw)
    assert no_artifact.output == raw.output
    assert '_search_candidate_output' not in no_artifact.metadata
    assert 'has_more' not in no_artifact.metadata
    assert 'total_count' not in no_artifact.metadata


def test_no_extra_candidates_keep_existing_body_and_invalid_response_is_rejected():
    saved = response([{'url': 'https://example.org/one', 'title': 'one', 'content': 'one'}])
    raw = WebSearchTool(parse_web_target('https://search.example.org/search'),
                        SavedTransport(saved)).handle(call())
    projected = project_tool_output(ToolOutputProjector(lambda *_: 'artifact://one'), call(), raw)
    assert projected.output == raw.output
    assert projected.metadata['output_truncated'] is False
    with pytest.raises(ValueError, match='candidate snapshot'):
        WebSearchResponse(results=saved.results, provider='test', byte_count=1,
                          candidates=(saved.results[0], saved.results[0]))
