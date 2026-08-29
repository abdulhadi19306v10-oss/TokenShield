# 🔬 TokenShield Reproduction Guide

> **Official Reproduction Manual for Judges & Independent Reviewers**  
> *micro1 Agentic Workflows Hackathon*

---

## 1. System Requirements & Environment Specifications

| Component | Specification / Version | Notes |
| :--- | :--- | :--- |
| **Operating System** | Linux (Ubuntu 20.04+), macOS 12+, or Windows 10/11 | Verified on Windows & Linux |
| **Python Runtime** | Python 3.11+ (CPython) | Verified on Python 3.11.9 |
| **Hardware** | Any modern multi-core CPU, $\ge 4\text{GB RAM}$ | Runs locally with zero GPU requirements |
| **Disk Space** | $< 250\text{MB}$ (including virtual environment) | Lightweight SQLite database |
| **Approximate Test Runtime** | $\approx 2.5\text{ seconds}$ for full 44-test suite | Fast asynchronous execution |
| **Execution Cost** | **$0.00** (Local deterministic test suite) | Uses built-in mock streaming server |

---

## 2. Step-by-Step Clean Environment Setup

### Step 2.1: Clone the Repository
```bash
git clone https://github.com/abdulhadi19306v10-oss/TokenShield.git
cd TokenShield
```

### Step 2.2: Create and Activate Virtual Environment
```bash
# On Linux / macOS:
python3 -m venv .venv
source .venv/bin/activate

# On Windows (PowerShell):
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Step 2.3: Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 2.4: Configure Environment Variables
```bash
# Linux / macOS:
cp .env.example .env

# Windows PowerShell:
Copy-Item .env.example .env
```

---

## 3. Running the Verification & Benchmark Suite

### Step 3.1: Execute Full 44-Test Automated Suite
```bash
pytest tests/ -v
```
**Expected Output:**
```
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.1, pluggy-1.6.0
collected 44 items

tests/scenarios/scenario_10_control_case.py::test_scenario_10_control_case_no_false_positives PASSED
tests/scenarios/scenario_1_3_tool_loops.py::test_scenario_1_web_scraper_403_loop PASSED
tests/scenarios/scenario_1_3_tool_loops.py::test_scenario_2_sql_syntax_error_loop PASSED
tests/scenarios/scenario_1_3_tool_loops.py::test_scenario_3_file_search_empty_loop PASSED
tests/scenarios/scenario_4_6_circular_reasoning.py::test_scenario_4_repetitive_thought_chain PASSED
tests/scenarios/scenario_4_6_circular_reasoning.py::test_scenario_5_paraphrased_loop PASSED
tests/scenarios/scenario_4_6_circular_reasoning.py::test_scenario_6_repeating_markdown_bullets PASSED
tests/scenarios/scenario_7_9_payload_bloat.py::test_scenario_7_large_json_table_compression PASSED
tests/scenarios/scenario_7_9_payload_bloat.py::test_scenario_8_raw_html_noise_stripping PASSED
tests/scenarios/scenario_7_9_payload_bloat.py::test_scenario_9_multi_turn_system_prompt_bloat PASSED
tests/scenarios/scenario_complex_and_false_positives.py::test_complex_scenario_11_ping_pong_tool_oscillation PASSED
tests/scenarios/scenario_complex_and_false_positives.py::test_complex_scenario_12_mutating_parameter_exhaustion_loop PASSED
tests/scenarios/scenario_complex_and_false_positives.py::test_complex_scenario_13_meta_reflection_stall_loop PASSED
tests/scenarios/scenario_complex_and_false_positives.py::test_false_positive_challenge_1_repetitive_test_suite_generation PASSED
tests/scenarios/scenario_complex_and_false_positives.py::test_false_positive_challenge_2_legal_contract_boilerplate_anaphora PASSED
tests/scenarios/scenario_complex_and_false_positives.py::test_false_positive_challenge_3_breadth_first_search_simulation_trace PASSED
...
============================= 44 passed in 2.69s ==============================
```

### Step 3.2: Run the 16-Scenario Comparative Scorecard
```bash
python tests/scenarios/benchmark_runner.py
```
**Expected Output Table:**
```
==========================================================================================================
                      TOKENSHIELD COMPREHENSIVE 16-SCENARIO BENCHMARK SCORECARD                   
==========================================================================================================

| Scenario | Category | Baseline Tokens | TokenShield Tokens | Tokens Saved | Reduction % | Interception Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Scenario 1: Web Scraper 403 Loop** | Tool Loop | 4,000 | 2 | 3,998 | **99.95%** | INTERCEPTED |
| **Scenario 2: SQL Syntax Error Loop** | Tool Loop | 4,000 | 2 | 3,998 | **99.95%** | INTERCEPTED |
| **Scenario 3: File Search Empty Loop** | Tool Loop | 3,500 | 2 | 3,498 | **99.94%** | INTERCEPTED |
| **Scenario 4: Repetitive Thought Chain** | Circular Reasoning | 2,500 | 2 | 2,498 | **99.92%** | INTERCEPTED |
| **Scenario 5: Paraphrased Circular Loop** | Circular Reasoning | 3,000 | 6 | 2,994 | **99.8%** | INTERCEPTED |
| **Scenario 6: Repeating Markdown Bullets** | Circular Reasoning | 4,000 | 2 | 3,998 | **99.95%** | INTERCEPTED |
| **Scenario 7: 50KB JSON Table Bloat** | Payload Bloat | 3,365 | 109 | 3,256 | **96.76%** | COMPRESSED |
| **Scenario 8: 100KB HTML Noise Bloat** | Payload Bloat | 835 | 30 | 805 | **96.41%** | STRIPPED |
| **Scenario 9: Duplicate System Turn Bloat** | Payload Bloat | 380 | 67 | 313 | **82.37%** | PRUNED |
| **Scenario 10: Math Reasoning & DP Code (Control)** | Control Case | 9 | 9 | 0 | **0.0%** | PASSED (0% False Positive) |
| **Scenario 11: Ping-Pong Tool Oscillation** | Complex Runaway | 4,000 | 4 | 3,996 | **99.9%** | INTERCEPTED |
| **Scenario 12: Mutating Pagination Exhaustion** | Complex Runaway | 3,500 | 2 | 3,498 | **99.94%** | INTERCEPTED |
| **Scenario 13: Self-Reflection Stall Loop** | Complex Runaway | 3,000 | 3 | 2,997 | **99.9%** | INTERCEPTED |
| **Scenario 14: Repetitive Unit Test Suite** | FP Challenge | 6 | 6 | 0 | **0.0%** | PASSED (0% False Positive) |
| **Scenario 15: Legal NDA Boilerplate Clauses** | FP Challenge | 5 | 5 | 0 | **0.0%** | PASSED (0% False Positive) |
| **Scenario 16: BFS Search Execution Trace** | FP Challenge | 5 | 5 | 0 | **0.0%** | PASSED (0% False Positive) |

----------------------------------------------------------------------------------------------------------
TOTAL TOKENS SAVED ACROSS SUITE:     35,849 tokens
NET TOKEN REDUCTION (RUNAWAY SUITE): 99.29% (Target > 75%)
FALSE POSITIVE RATE (4/4 CHALLENGES):0 / 4 (0.0%)
==========================================================================================================
```

---

## 4. Launching the Live Proxy & Streamlit Dashboard

### Step 4.1: Start the TokenShield Proxy Server
```bash
uvicorn tokenshield.proxy.server:app --host 0.0.0.0 --port 8000 --reload
```
Test health endpoint:
```bash
curl http://localhost:8000/health
```

### Step 4.2: Launch the Streamlit Live Dashboard
In a second terminal window:
```bash
streamlit run tokenshield/dashboard/app.py
```
Open your browser at `http://localhost:8501` to view live session metrics, Plotly trajectory graphs, and circuit trip logs.

---

## 5. Integrating with Client LLM Agents

### Drop-in OpenAI SDK Example (Python):
```python
from openai import OpenAI

# Simply route base_url through TokenShield
client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-openai-api-key",
)

# Standard streaming completion - protected automatically by TokenShield!
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "You are a research agent."},
        {"role": "user", "content": "Analyze the web scraper output."},
    ],
    stream=True,
)

for chunk in response:
    content = chunk.choices[0].delta.content
    if content:
        print(content, end="", flush=True)
```
