# SWE-bench Benchmark for coding-agent

Benchmark the coding agent against [SWE-bench Lite](https://www.swebench.com/lite.html) (300 real GitHub issues) using free LLM providers.

## Cost: $0

All LLM calls use free-tier APIs. No credit card required.

## Quick Start

### 1. Install dependencies

```bash
pip install -r benchmarks/swebench/requirements.txt
pip install -e .  # install coding-agent
```

### 2. Set API keys (at least one)

```bash
# Primary — 14,400 requests/day free
export GOOGLE_API_KEY=your_key    # https://aistudio.google.com/apikey

# Fallbacks — 1,000 requests/day each
export GROQ_API_KEY=your_key      # https://console.groq.com/keys
export CEREBRAS_API_KEY=your_key  # https://cloud.cerebras.ai
export OPENROUTER_API_KEY=your_key  # https://openrouter.ai/keys
```

### 3. Run a test (3 instances)

```bash
cd benchmarks/swebench
python -m benchmarks.swebench.run --max-instances 3 --output preds.json -v
```

### 4. Run full benchmark

```bash
python -m benchmarks.swebench.run --dataset lite --output preds.json
```

### 5. Submit to SWE-bench

```bash
pip install sb-cli
sb-cli gen-api-key your@email.com
sb-cli verify-api-key YOUR_CODE
sb-cli submit swe-bench_lite dev --predictions_path preds.json
```

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--dataset` | Dataset: `lite`, `verified`, `full` | `lite` |
| `--split` | Dataset split: `dev`, `test` | `dev` |
| `--max-instances` | Limit number of instances (0=all) | `0` |
| `--instance-id` | Run single instance | — |
| `--output` | Predictions output file | `preds.json` |
| `--max-turns` | Max agent turns per instance | `15` |
| `--model` | Override model name | provider default |
| `-v` | Verbose logging | off |

## Examples

```bash
# Test with 5 instances
python -m benchmarks.swebench.run --max-instances 5 -v

# Run a single known instance
python -m benchmarks.swebench.run --instance-id sympy__sympy-20590

# Run all 300 instances
python -m benchmarks.swebench.run --dataset lite --output results/preds.json
```

## Provider Rotation

The runner rotates across available providers to maximize throughput:

| Provider | Free RPD | Model |
|----------|----------|-------|
| Google AI Studio | 14,400 | Gemini 2.5 Flash |
| Groq | 1,000 | Llama 3.3 70B |
| Cerebras | 1,000 | Llama 3.3 70B |
| OpenRouter | 1,000 | Llama 3.3 70B (free) |

With all 4 providers: ~17,400 requests/day. Full 300-instance run completes in <1 day.

## Output Format

The `preds.json` file is in sb-cli format:

```json
{
  "sympy__sympy-20590": {
    "model_patch": "diff --git a/sympy/...",
    "model_name_or_path": "coding-agent"
  }
}
```

## Architecture

```
run.py              → CLI entry point, loads dataset, orchestrates
├── providers.py    → Multi-provider LLM rotation with rate tracking
├── runner.py       → Per-instance agent execution and patch capture
├── repo_utils.py   → Git clone, checkout, diff utilities
└── config.py       → Provider definitions and configuration
```
