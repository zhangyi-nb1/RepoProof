# Architecture — four planes, one agent loop

```mermaid
flowchart TB
    subgraph TA["1 · Task Authoring Plane (human + deterministic tools)"]
        TC[TaskContract + sha sidecar]
        RS[RequirementSpec<br/>owner / severity / public_text / oracle bindings]
        RM[Responsibility Matrix]
        CAG{{ContractAdequacyGate<br/>13 deterministic checks}}
        TP[TaskPackage freeze<br/>collection · wheelhouse · image digest ·<br/>spec sha · PromptManifest · controls]
        TC --> RS --> RM
        TC --> CAG
        RS --> CAG
        CAG -->|ADEQUATE| TP
        CAG -->|INVALID_TASK_SPEC| STOP([refuse: agent never starts,<br/>zero model calls])
    end

    subgraph AE["2 · Agent Execution Plane (the ONLY autonomous loop)"]
        AG[mini-swe-agent DefaultAgent]
        ENV[RepoProofEnvironment]
        POL[Policy · argv denylist · causality]
        BUD[Budgets · steps / commands / tokens]
        DOCK[Docker container<br/>non-root · cap-drop ALL · network=none]
        TR[(Append-only Trace<br/>SHA-256 hash chain)]
        AZ[/Adaptation Zone<br/>only persistent writable dir/]
        AG -->|command| ENV --> POL --> DOCK
        ENV --> BUD
        ENV --> TR
        DOCK --> AZ
    end

    subgraph VP["3 · Verification Plane (no LLM calls)"]
        CAP[CapabilityVerifier<br/>frozen oracle + held-out]
        REG[HostRegressionVerifier]
        PV[PolicyVerifier]
        REP[ReplayVerifier<br/>fresh container, agent NOT re-run]
        CG{{Completion Gate<br/>decision table over verifier results;<br/>agent claims ignored by construction}}
        CAP --> CG
        REG --> CG
        PV --> CG
        REP --> CG
        CG -->|C ∧ R ∧ P ∧ clean_adoption| PASS([PASS_ADAPTED])
        CG -->|otherwise| FAIL([honest FAIL / BLOCKED])
    end

    subgraph EP["4 · Evidence Plane"]
        RMF[RunManifest<br/>package root · prompt sha · provider hash]
        AS[(Content-addressed Artifact Store)]
        TH[Trace hash chain + final sha]
        VH[VerificationResult hashes]
        AB[Adoption / Evidence Bundle<br/>redaction-scanned]
    end

    TP --> AG
    AZ -->|frozen AdaptationManifest| CAP
    TR --> TH
    CG --> RMF
    CAP & REG & PV & REP --> VH
    RMF & AS & TH & VH --> AB
```

## Plane invariants (all pinned by tests)

1. **Task Authoring Plane** — everything normative is structured and
   hash-frozen; YAML comments cannot carry rules (adequacy check);
   the runner only VERIFIES frozen packages, never regenerates them.
2. **Agent Execution Plane** — contains the **single autonomous agent
   loop** in the whole system (`DefaultAgent.run`, called once per
   run; a static guard test forbids a second loop). Every command
   passes policy + budget and lands in the tamper-evident trace.
3. **Verification Plane** — pure programs; **no LLM anywhere**. The
   Completion Gate never reads agent claims. Replay re-executes the
   frozen adaptation in a fresh container — it does **not** re-run
   the agent.
4. **Evidence Plane** — every public number traces to a committed,
   redaction-scanned bundle; `verify-bundle` re-derives gate verdicts
   from hashes.

## Trust-zone summary

| Zone | Mount | Writable | Agent-visible |
|---|---|---|---|
| upstream (pinned commit) | `/upstream` | no | yes |
| consumer + guard + public tests | `/consumer` | no | yes |
| adaptation | `/adaptation` | **yes** | yes |
| oracle + held-out fixtures | verification containers only | no | **no** |
| scratch | `/tmp` | yes (ephemeral) | yes |
