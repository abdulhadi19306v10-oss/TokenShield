# 🛰️ Representative Agent Trajectories & Interception Logs

> **Execution Traces & Event Telemetry for TokenShield**  
> *micro1 Agentic Workflows Hackathon (Deliverable 04)*

---

## 1. Overview of Trajectory Lifecycle

Every request routed through TokenShield progresses through four observable telemetry phases:
1. **Pre-Execution Ingestion & Compression** (Payload minification & system turn deduplication)
2. **In-Flight Stream Chunk Inspection** (Real-time SSE token velocity & $n$-gram / similarity evaluation)
3. **Circuit Interception Event** (Upstream socket severed upon threshold breach)
4. **Recovery Steering & State Persistence** (System prompt injection & SQLite metrics logging)

---

## 2. Trajectory Case 1: Infinite Web Scraper 403 Loop Interception

### 2.1 Initial Request Payload (Client Agent $\to$ TokenShield)
```json
{
  "model": "gpt-4o-mini",
  "stream": true,
  "messages": [
    {
      "role": "system",
      "content": "You are a research agent tasked with scraping https://enterprise.internal/api/data."
    },
    {
      "role": "user",
      "content": "Extract customer metrics from the endpoint."
    },
    {
      "role": "tool",
      "tool_call_id": "call_scrape_01",
      "content": "{\"status\": \"error\", \"code\": 403, \"message\": \"Access Denied: Cloudflare IP Block\"}"
    }
  ]
}
```

### 2.2 In-Flight SSE Streaming & Anomaly Progression
```
[Token 01] Upstream: "Web"              | Anomaly Score: 0.00 | Threshold: 0.70 | Status: PASS
[Token 02] Upstream: " scraper"        | Anomaly Score: 0.00 | Threshold: 0.70 | Status: PASS
[Token 05] Upstream: " failed with 403" | Anomaly Score: 0.15 | Threshold: 0.70 | Status: PASS
[Token 09] Upstream: " Retrying..."    | Anomaly Score: 0.25 | Threshold: 0.70 | Status: PASS
[Token 12] Upstream: "Web"              | Anomaly Score: 0.55 | Threshold: 0.70 | Status: WARN
[Token 14] Upstream: " scraper failed"  | Anomaly Score: 0.78 | Threshold: 0.70 | Status: TRIP!
```

### 2.3 Circuit Breaker Action & Interception Frame
```
>>> CIRCUIT BREAKER TRIPPED! Reason: TOOL_ERROR_LOOP (Anomaly Score: 0.78 >= 0.70)
>>> Closing Upstream Connection (socket.aclose())
>>> Yielding Stop Chunk to Client Agent:
```
```json
data: {
  "id": "chatcmpl-trip-8f4b1a2c",
  "object": "chat.completion.chunk",
  "created": 1756468800,
  "model": "gpt-4o-mini",
  "choices": [
    {
      "index": 0,
      "delta": {
        "content": "\n\n[TokenShield Circuit Intercept: Runaway loop halted to prevent token burn]"
      },
      "finish_reason": "stop"
    }
  ]
}

data: [DONE]
```

### 2.4 Injected Recovery Steering (Turn N+1)
```json
{
  "role": "system",
  "content": "[TokenShield Circuit Intercept] Repeated tool failure loop: The tool call failed or returned unchanged outputs. Do NOT retry with the same parameters. Handle the failure gracefully or return your final answer immediately."
}
```

### 2.5 Recorded SQLite Telemetry Row
```json
{
  "session_id": "sess_8f4b1a2c901e",
  "model": "gpt-4o-mini",
  "status": "TRIPPED",
  "total_prompt_tokens": 142,
  "total_completion_tokens": 14,
  "tokens_saved": 3986,
  "cost_saved_usd": 0.002392,
  "created_at": "2026-08-29 12:45:00"
}
```

---

## 3. Trajectory Case 2: 50KB Tabular JSON Tool Output Compression

### 3.1 Uncompressed Incoming Payload (50KB Database Output)
* **Raw Prompt Size**: 3,365 tokens (120 database user rows containing nested metadata and redundant keys).

### 3.2 Pre-Execution Pipeline Action (`ContextTrimmerNode` & `PayloadDeduplicationEngine`)
```
>>> Tool Output Size: 48,290 bytes (> 4,096 byte threshold)
>>> Parsing Tabular JSON: Identified 120 items with uniform schema ['id', 'uuid', 'username', 'email', 'metadata', 'timestamp']
>>> Condensing payload to sample of 3 items + schema summary
>>> Minifying whitespace and stripping nulls
```

### 3.3 Optimized Payload Dispatched to LLM (109 tokens)
```json
{
  "role": "tool",
  "tool_call_id": "call_db_dump",
  "content": "{\"_tokenshield_summary\":\"Showing 3 of 120 items (minified & compressed)\",\"schema_fields\":[\"id\",\"uuid\",\"username\",\"email\",\"metadata\",\"timestamp\"],\"sample\":[{\"id\":0,\"uuid\":\"usr-uuid-abcdef-0000\",\"username\":\"analyst_account_0\",\"email\":\"account_0@enterprise-corp.internal\",\"metadata\":{\"dept\":\"finance\",\"level\":\"senior\",\"permissions\":[\"read\",\"write\",\"audit\"]},\"timestamp\":\"2026-08-29T12:00:00Z\"},{\"id\":1,\"uuid\":\"usr-uuid-abcdef-0001\",\"username\":\"analyst_account_1\",\"email\":\"account_1@enterprise-corp.internal\",\"metadata\":{\"dept\":\"finance\",\"level\":\"senior\",\"permissions\":[\"read\",\"write\",\"audit\"]},\"timestamp\":\"2026-08-29T12:00:00Z\"},{\"id\":2,\"uuid\":\"usr-uuid-abcdef-0002\",\"username\":\"analyst_account_2\",\"email\":\"account_2@enterprise-corp.internal\",\"metadata\":{\"dept\":\"finance\",\"level\":\"senior\",\"permissions\":[\"read\",\"write\",\"audit\"]},\"timestamp\":\"2026-08-29T12:00:00Z\"}],\"total_count\":120}"
}
```
* **Net Reduction**: **96.76% of prompt tokens saved** (3,256 tokens saved on turn 1 alone).

---

## 4. Trajectory Case 3: Human Checkpoint Gate Suspension & Clearance

### 4.1 Safety-Critical Loop Detected with `ENABLE_HUMAN_CHECKPOINT = True`
```
>>> Loop detected in financial order execution agent.
>>> Suspending execution at HumanCheckpointGate (session_id: sess_fin_77a2).
>>> Waiting for operator decision via Streamlit Control Panel...
```

### 4.2 Streamlit Dashboard Action
* Operator inspects trajectory trace on the UI.
* Operator clicks `[Approve & Continue]` / sends `POST /v1/control/human-gate` (`{"session_id": "sess_fin_77a2", "approved": true}`).

### 4.3 Execution Resume Trace
```
>>> Human clearance signal received: APPROVED.
>>> Resuming stream generator with injected supervisor guidance.
>>> Session completed successfully with 0 lost state.
```
