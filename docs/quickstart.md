# Quick start

## Installation

```bash
pip install "nest-core[plugins]"
```

## Your first run

```bash
# Run the marketplace scenario with all defaults
nest run scenarios/marketplace.yaml

# Inspect the trace
nest inspect traces/marketplace.jsonl
```

## Check your setup

```bash
nest doctor
```

## Writing a scenario

```yaml
name: my-experiment
tier: 1
agents:
  count: 10
  brain: state-machine
layers:
  transport: in_memory
  comms: nest_native
  # ... all 12 layers
task:
  type: marketplace
  config:
    rounds: 10
duration: ticks: 1000
```

## Writing a plugin

See [writing-a-plugin.md](writing-a-plugin.md).
