# CA-P5-03 evidence

[Contract and limits](../../CA-P5-03_worker_process_binding.md),
[artifact](../../contracts/runtime-worker-process-v1/contract.json),
[composition source hashes](source-manifest.json). Delivery commit is the Git commit containing this file;
consumer pins that published commit separately. Historical v1 gate source manifests are unchanged.

Focused config/Worker/domain/API repeat passed31 tests. Initial full run retained one historical fingerprint
expectation failure (new process-only field was inadvertently included by the test's reconstruction), plus18
setup errors from one disposable PostgreSQL fixture: invalid SSL-negotiation response H. The implementation
already excluded the new field; the regression now excludes that transport-only input too. Isolated repeat
passed; transient fixture cause is unconfirmed. No broad Docker cleanup, data repair or test skip was added.
Final full gate receipts are stored separately after exit statuses are collected. No production acceptance.
