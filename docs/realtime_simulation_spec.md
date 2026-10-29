# Real-Time Simulation Specification

## 1. Purpose

Build a real-time contact center simulation integrated into the Airline Contact Center AI Platform. The simulation must support operational monitoring, SLA risk detection, forecasting, and Real-Time Management (RTM) decisions.

## 2. Simulation Controls

The interface must provide:
- Run
- Pause
- Resume
- Stop
- Simulation speed control
- Simulation date and time
- Channel selection: Voice, WhatsApp, Webchat, Email, and Social Media

## 3. Contact Simulation

The simulation engine generates synthetic contact arrivals based on configurable demand patterns.

Each simulated contact should track, where applicable:
- Simulation session
- Arrival timestamp
- Channel
- Market
- Language
- Queue
- Handling status
- Waiting time
- Handling time
- Outcome

All simulated contacts must be clearly identified as synthetic data and must not be mixed with genuine historical observations used for model training or evaluation.

## 4. Agent State Simulation

Simulated agent states should include:
- Available
- Busy
- Break
- Lunch
- Training
- Offline

Agent availability must account for queue assignment and relevant skills.

## 5. Queue and SLA Engine

Calculate interval-level metrics using the centralized KPI definitions and calculation rules.

Required metrics include:
- Offered contacts
- Handled contacts
- Answered contacts
- Abandoned contacts
- Average Handle Time (AHT)
- Average Speed of Answer (ASA)
- Service Level (SLA)
- Forecast demand
- Actual demand
- Forecast error

The SLA target must be configurable through centralized configuration. Changing the target must not change the underlying SLA calculation formula.

## 6. Real-Time Management (RTM)

The RTM engine should:
- Detect current and projected SLA risk
- Identify demand and staffing gaps
- Generate recommendations
- Record the reason for each recommendation
- Record the expected operational impact
- Track whether a recommendation was accepted, rejected, or applied

Recommendations must not silently change real operational systems. Any action that affects external systems requires explicit authorization.

## 7. Simulation Results

Persist simulation results so that a completed or paused session can be inspected later.

The platform should support:
- Interval KPI history
- Contact-level event history
- Agent state transitions
- RTM alerts and recommendations
- Comparison between simulated and historical scenarios

## 8. Architecture Boundaries

Keep these responsibilities separate:
- Simulation engine
- Agent state engine
- Queue and SLA calculation engine
- Forecasting engine
- RTM decision engine
- Streamlit presentation layer
- MySQL persistence layer

All KPI formulas must be centralized. Modules must reuse the same definitions rather than implementing competing versions.

## 9. Testing and Data Integrity

Tests must verify:
- Simulation controls and session lifecycle
- Contact and agent state transitions
- KPI calculation consistency
- Separation of synthetic and historical data
- RTM recommendation auditability
- Persistence and retrieval of simulation results
