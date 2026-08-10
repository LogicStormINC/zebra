from zebra_agent_api import RouteAdapter, RouteRequest, create_app


def test_task_plan_requirement_is_explicit_durable_and_defaults_false(tmp_path) -> None:
    adapter = RouteAdapter(create_app(tmp_path / "tasks.sqlite"))
    required = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "Goal task",
                "prompt": "Investigate the durable goal",
                "workspace": str(tmp_path),
                "plan_required": True,
            },
        )
    )
    ordinary = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={"title": "Simple", "prompt": "Answer", "workspace": str(tmp_path)},
        )
    )
    followed = adapter.handle(
        RouteRequest(
            "POST",
            f"/tasks/{required.body['task_id']}/messages",
            body={"content": "Continue without changing the contract"},
        )
    )

    assert required.status_code == 201
    assert required.body["plan_required"] is True
    assert ordinary.body["plan_required"] is False
    assert followed.status_code == 201
    assert adapter.handle(
        RouteRequest("GET", f"/tasks/{required.body['task_id']}")
    ).body["plan_required"] is True


def test_task_plan_requirement_rejects_non_boolean_input(tmp_path) -> None:
    response = RouteAdapter(create_app(tmp_path / "tasks.sqlite")).handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={"prompt": "Goal", "workspace": str(tmp_path), "plan_required": "yes"},
        )
    )

    assert response.status_code == 400
    assert response.body["reason"] == "plan_required must be a boolean when provided"
