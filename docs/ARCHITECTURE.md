# Architecture

A single-process Python CLI. A thin command layer verifies input and gates
spend; an orchestrator then fans work across a thread pool. Each module owns one
responsibility and talks to exactly one external service.

> This public repo includes the **infrastructure layer** (`cost`, `ledger`,
> `reliability`). The discovery/enrichment/audit modules are proprietary and not
> published — they're shown here only as design.

## Component diagram

```mermaid
flowchart LR
    subgraph ENTRY [Entry]
        CLI["cli / __main__<br/>flags + prompts + budget menu"]
    end
    subgraph ORCH [Orchestration]
        PIPE["pipeline<br/>discover → process → write"]
    end
    subgraph LOGIC [Domain logic — proprietary]
        TGT["targeting<br/>input verification"]
        SRC["sources<br/>multi-source discovery + competitors"]
        ENR["enrich<br/>contact enrichment"]
        AUD["audit<br/>3-tier marketing audit"]
        VAL["validate<br/>email / phone / URL"]
    end
    subgraph INFRA [Infrastructure — included in this repo]
        COST["cost<br/>per-key budget cap"]
        LED["ledger<br/>per-niche dedup"]
        REL["reliability<br/>retry + checkpoint"]
    end
    subgraph EXT [External services]
        GP[("Google Places")]
        CH[("Company registry")]
        RE[("Email verifier")]
    end

    CLI --> TGT
    CLI --> PIPE
    CLI --> COST
    CLI --> LED
    PIPE --> SRC
    PIPE --> ENR
    PIPE --> AUD
    PIPE --> VAL
    PIPE --> REL
    SRC --> GP
    ENR --> CH
    VAL --> RE
```

## Pipeline flow

```mermaid
flowchart TD
    U([CLI / interactive]) --> V{"Verify niche + location<br/>(zero spend)"}
    V -- "typo / unknown" --> VX[Reject + suggest]
    V -- ok --> B{"Budget gate<br/>per-key $ cap"}
    B -- cancel --> BX[Exit, no spend]
    B -- continue --> D[Discover across multiple sources]
    D --> M[Merge + dedup]
    M --> L{"Seen before?<br/>per-niche ledger"}
    L -- yes --> LX[Skip — no spend]
    L -- no --> P[Process leads in parallel — thread pool]
    P --> P1[Enrich: contact details]
    P1 --> P2[Verify email]
    P2 --> P3[Audit: 3 problem tiers]
    P --> P4[Nearest competitors]
    P3 --> K{"Keep?<br/>valid email OR phone"}
    K -- neither --> KX[Drop]
    K -- yes --> W[Write Excel + ledger + cost summary]
```

## Modules

| Module | Responsibility | In this repo |
|---|---|---|
| `cli` / `__main__` | Flags, interactive prompts, budget menu, dependency wiring | — |
| `targeting` | Verify niche + location **before any spend** | — |
| `sources` | Multi-source discovery + nearest-competitor geometry | — |
| `enrich` | Contact enrichment (website + company registry + work-email derivation) | — |
| `audit` | 3-tier marketing audit (verifiable facts only) | — |
| `validate` | Email verification, phone E.164, URL liveness | — |
| `pipeline` | Orchestration, concurrency, output | — |
| `config` | Keys, output schema, tunables | — |
| **`cost`** | Per-key, per-month spend tracking with a hard graceful stop | ✅ |
| **`ledger`** | Per-niche dedup memory; checked before any paid call | ✅ |
| **`reliability`** | Retry/backoff + within-run checkpoint resume | ✅ |

See **[DESIGN-DECISIONS.md](DESIGN-DECISIONS.md)** for the *why* behind these choices.
