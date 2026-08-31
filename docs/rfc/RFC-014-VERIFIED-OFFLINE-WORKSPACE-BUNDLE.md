# RFC-014: Verified Offline Workspace Bundle

Status: IMPLEMENTED CANDIDATE — qualification not yet executed
Milestone: M6.2
Delivery profile: `workspace_bundle_v1`

## 1. Decision

RepoProof adds one new Product delivery topology without changing `cli_v2`:

```text
one local file or directory
        -> offline per-invocation builder
        -> one previously nonexistent directory
        -> structure + format + semantic + bounded runtime verification
        -> clean replay + Fresh audit
        -> operational release decision
```

The directory is the verified artifact. A ZIP is only a deterministic transport
copy and never replaces the directory manifest, semantic evidence, replay or
append-only release ledger.

This RFC does not add a sidecar, daemon, browser automation, credentialed action,
network runtime, long-lived service or general multi-step project integration.
The old host-adaptation research path remains frozen.

## 2. Public contract

`ToolSpec v4` binds `delivery_profile_id=workspace_bundle_v1` and a
`WorkspaceArtifactContractV1`. Versions 1–3 retain their historical meanings.

The profile has these fixed invariants:

- input is one local regular file or directory;
- output is one new directory, invoked as
  `bin/<tool> <input> --out-dir <new-directory>`;
- runtime is local CPU, credential-free, offline and per invocation;
- a successful exit requires atomic directory publication and all declared
  structure/format checks;
- failure removes the temporary directory and does not leave a partial output;
- existing output paths, path escape, symlink, hardlink, FIFO, socket and device
  entries are rejected;
- input defaults: 256 files / 256 MiB total;
- output defaults: 512 files / 256 MiB total;
- single-file limit: 64 MiB; depth: 12; relative path: 240 bytes;
- MCP returns `WORKSPACE_BUNDLE_MCP_NOT_SUPPORTED` in M6.2.

## 3. Evidence layers

The four layers are independent and later layers cannot manufacture an earlier
PASS:

1. Structure: path patterns, file roles, counts, sizes, modes, entry points and
   extras policy.
2. Generic format: UTF-8, CSV/TSV, JSON/YAML/TOML, Python compile, HTML/XML/SVG,
   SQLite quick check and ZIP/wheel integrity.
3. Task semantics: a frozen task-owned
   `verify(input_path, artifact_dir)` executed through one Core protocol.
4. Runtime: an optional frozen smoke/headless command with timeout, process-group
   cleanup and offline isolation.

`ArtifactManifestV1` is created outside the Agent workspace. Its tree hash binds
sorted relative paths, modes, sizes and content SHA-256 values. The Agent cannot
write or declare the trusted manifest.

`SemanticVerifierEvidenceV2` binds input identity, artifact tree and manifest,
workspace contract, confirmed intent, upstream commit, verifier identity and
observed upstream use. PASS requires three counterfactual controls:

- substituted input is rejected;
- substituted artifact directory is rejected;
- substituted upstream result is rejected.

Clean replay uses only the exported package and its lock/wheelhouse, then rebuilds
and rechecks structure, semantics and runtime evidence.

## 4. Human fixture flow

An LLM may propose three or four natural scenario blueprints. It never supplies
binary fixture bytes or a complete directory. A task-owned fixture builder turns
the blueprint into a real file/directory; the pinned-upstream reference produces
the expected workspace. Studio displays both trees and bounded text previews for
human confirmation.

The fixture builder, blueprints, public commitments, workspace contract,
reference and semantic verifier are frozen before an Agent run. Held-out data may
hide only input and expected artifact bytes, never an additional normative rule.

Fresh audit repeats the same trust split using a scenario not present in frozen
construction fixtures. Browser state carries only a token; Core reloads the
server-owned paths, task package, current registry/package identity and both tree
hashes before an audit can start.

## 5. Repair and incidents

Only a public `AGENT_ADAPTER` failure with an actual adapter diff may consume a
repair attempt. The total budget remains initial implementation plus two repairs.
No diff, repeated fingerprint without progress, scope drift, contract defects,
Harness/upstream failures, hidden failures and replay failures stop without blind
Agent repair.

Every failing workspace Agent round and every failed v4 Product action creates
append-only `ProductIncidentV1` evidence containing only public failure classes
and normalized identities. `AGENT_ADAPTER` ownership does not itself imply
repair eligibility.

A Core/Harness change requires `HarnessChangeEvidenceV1`: frozen incidents, a
stated generic invariant, an anonymous synthetic before/after control, regression
tests and a case-identifier scan. Its writer reloads the referenced append-only
incident files and checks their identity and normalized fingerprint. Non-safety
changes require two distinct task versions, not merely two incident-id strings.
False-success, evidence leakage, path escape and identity failures may use the
first incident, but still require the anonymous negative control.

## 6. Product UI

Studio keeps Worker, Pipeline, Operational and package health separate. Workspace
tasks additionally show structure, semantics, runtime, replay and release lines.
The main Journey supports scenario generation, tree preview, confirmation and
directory Fresh audit. The tool library shows the CLI topology, refuses MCP,
revalidates a generated directory, opens it in Finder and offers deterministic ZIP
download.

The UI never parses registry or release ledgers independently and never promotes
a stale action result to `ACTIVE`.

## 7. Qualification boundary

The preregistered batch is defined by
`docs/m6_2_workspace_bundle_qualification.yaml`. Real model execution is not
authorized by this RFC. The profile remains `EXPERIMENTAL` until both baseline
cases and at least four complex cases are `ACTIVE`, including one SQLite/binary
workspace and one runnable application workspace.

Recorded cases describe only those exact repositories, commits, contracts and
runs. They are not an arbitrary-repository success rate or a model benchmark.
