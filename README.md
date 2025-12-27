# PM Decision OS — MVP

## Overview

**PM Decision OS** is a minimal, open framework for **walk-forward, audit-grade explanation of portfolio decisions**.

This repository is **not** a trading system, optimizer, or execution engine.  
Its purpose is to model and explain *why* portfolio positions and sizes change over time, using deterministic inputs, explicit clocks, and replayable state.

The MVP focuses on:
- Decision explainability over performance
- Time-correct (“as-of”) reasoning
- Clear separation between signals, prices, and portfolio state
- Human-readable explanations backed by structured data

This project is designed as a **skills and architecture demo**, illustrating how a professional PM-facing decision system can be built with modern Python tooling.

---

## What This Is (and Is Not)

### This **is**:
- A decision explanation framework
- A walk-forward replay system
- A canonical place to answer:  
  *“Why does this position exist, and why is it this size, today?”*
- An audit-friendly record of portfolio reasoning
- A foundation for PM review, post-mortems, and compliance narratives

### This is **not**:
- A backtesting engine
- A signal discovery system
- A performance optimizer
- An execution or OMS platform
- A proprietary trading strategy

No alpha, sizing parameters, or firm-specific logic are embedded in this repo.

---

## Design Intent

Most portfolio systems explain **what happened** (returns, attribution, risk).  
Very few explain **why decisions were made**, in a way that is:

- Walk-forward correct
- Deterministic
- Human-interpretable
- Reviewable months later
- Independent of execution infrastructure

PM Decision OS is designed to fill that gap.

Key design principles:
- **One clock per concept** (signal time ≠ price time ≠ evaluation time)
- **Anchors and resets are first-class concepts**
- **State is explicit and persisted**
- **Explanations are derived, not improvised**
- **Every output can be replayed from inputs**

---

## Data Model Philosophy

The database schema is designed to support:
- Time-stamped decision state
- Anchor events (e.g., trade initiation, resets)
- Portfolio snapshots
- Deterministic reconstruction of decisions

All tables are:
- Append-only or versioned
- Time-aware
- Safe to replay

The schema is migrated and managed via **Alembic** to reflect production-grade discipline.

---

## Setup

- python -m venv .venv
- source .venv/bin/activate
- pip install -r requirements.txt
- cp .env.example .env
- DATABASE_URL=postgresql://user:password@host:5432/pm_decision_os
- alembic upgrade head