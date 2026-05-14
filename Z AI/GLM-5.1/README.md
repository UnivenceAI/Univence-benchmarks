# Univence Benchmarks: GLM-5.1 Autonomous Agent

This directory contains the raw generated code, trajectory logs, and custom evaluation scripts for our autonomous coding agent framework, currently powered by Z.ai's GLM-5.1 model. 

## Benchmark Results (LiveCodeBench Lite - Python)
On a blind run of 369 competitive programming problems, the agent achieved a **94.0%% Pass@1 rate**.
| Tier | Pass Rate | Fraction |
| :--- | :--- | :--- |
| **Overall** | **94.0%** | 347 / 369 |
| Easy | 97.9% | 138 / 141 |
| Medium | 97.4% | 152 / 156 |
| Hard | 79.2% | 57 / 72 |

## Reproducing the Results
Because the official LiveCodeBench evaluator relies heavily on Linux/Docker sandboxing, this repository includes a custom, Windows-compatible grading script (`evaluator.py`) to easily verify the agent's generated code locally.

1. Clone the `Univence-benchmarks` repository.
2. Navigate to this directory (`/Z AI/GLM-5.1/`).
3. Install the required Hugging Face dataset library:
   ```bash
   pip install datasets
4. Ensure all generated agent solution files (.py) are located in the local answers/ directory.

5. Run the evaluation script:
```bash
python evaluator.py
```

6. The script will output the pass/fail metrics directly to your console and generate a detailed eval_results.json file containing the per-problem test breakdowns and any error tracebacks.
