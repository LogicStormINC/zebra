# Task Plan

## CTX-SEG-01 - Stable Task And Automatic Internal Segments

1. `completed` - Record ADR-013, supersede the explicit user handoff decision,
   and define the dependency-ordered Task/Segment implementation roadmap.
2. `completed` - Remove ordinary Desktop handoff rendering, navigation, and client
   creation actions without changing backend safety contracts.
3. `completed` - Add a deterministic regression that forbids stage handoff controls
   on the ordinary user surface.
4. `completed` - Run Desktop checks/build and repository validation, then update
   durable status, findings, and worklog evidence.
5. `in_progress` - Add Task/Segment domain and SQLite projection/migration contracts.
6. `pending` - Add Task API, monotonic cross-Segment stream, and active-Segment routing.
7. `pending` - Add deterministic lifecycle controller and automatic safe rollover.
8. `pending` - Bind Desktop to stable Task identity and add cross-Segment regressions.
9. `pending` - Run all gates, update closeout evidence, push, and open the PR.

### Errors Encountered

- None.
