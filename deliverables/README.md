<div align="center">
  <img src="../assets/logo.svg" alt="TokenShield Logo" width="350"/>
  <h2>TokenShield — Hackathon Deliverables Index</h2>
  <p><em>micro1 Agentic Workflows Hackathon (Official Deliverables Package)</em></p>
</div>

---

## 📁 Deliverables Directory Overview

This directory contains all formal deliverables, specifications, reproduction guides, and telemetry trajectories for **TokenShield**:

| Deliverable | File | Description |
| :--- | :--- | :--- |
| **Deliverable 01: Project Overview & Architecture** | [`README.md`](../README.md) | Full repository README, problem statement, changelog story, benchmark scorecard, and quick start. |
| **Deliverable 02: Reproduction Manual** | [`REPRODUCTION.md`](./REPRODUCTION.md) | Step-by-step reproduction instructions, clean environment setup, and verification suite for judges. |
| **Deliverable 03: Representative Agent Trajectories** | [`AGENT_TRAJECTORIES.md`](./AGENT_TRAJECTORIES.md) | Execution traces demonstrating pre-flight compression, in-flight SSE loop interception, and circuit trip recovery. |
| **Deliverable 04: Technical Architecture & Design Blueprint** | [`DESIGN.md`](./DESIGN.md) | In-depth engineering specification, mathematical formulas, state machine transitions, and database schema. |
| **Deliverable 05: Project Specification** | [`PROJECT_SPEC.md`](./PROJECT_SPEC.md) | High-level requirements, component topology, evaluation framework, and milestones. |
| **Hackathon Brief** | [`hackathon_brief.pdf`](./hackathon_brief.pdf) | Original hackathon requirements and evaluation criteria document. |

---

## 🚀 Quick Navigation for Evaluators

1. **Verify All 44 Automated Tests:**
   ```bash
   pytest tests/ -v
   ```
2. **Run 16-Scenario Benchmark Evaluation:**
   ```bash
   python tests/scenarios/benchmark_runner.py
   ```
3. **Launch Control Dashboard:**
   ```bash
   streamlit run tokenshield/dashboard/app.py
   ```
4. **Start Proxy Middleware:**
   ```bash
   uvicorn tokenshield.proxy.server:app --host 0.0.0.0 --port 8000 --reload
   ```
