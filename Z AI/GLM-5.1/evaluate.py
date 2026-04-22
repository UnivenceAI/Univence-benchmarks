"""
LiveCodeBench Evaluator - Windows-compatible.
Evaluates solution files against the LiveCodeBench dataset by running
each solution in a subprocess against hidden test cases.
Uses temp files to avoid Windows command-line length limits.
"""

import sys
import os
import json
import zlib
import pickle
import base64
import subprocess
import tempfile

from datasets import load_dataset


def load_solutions(answers_dir):
    """Load all solution files from the answers directory."""
    solutions = {}
    for filename in os.listdir(answers_dir):
        if filename.endswith(".py"):
            question_id = filename[:-3]
            with open(os.path.join(answers_dir, filename), "r", encoding="utf-8") as f:
                solutions[question_id] = f.read()
    return solutions


def decode_private_test_cases(raw):
    """Decode private test cases - may be JSON or base64-encoded zlib pickle."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        try:
            return json.loads(
                pickle.loads(
                    zlib.decompress(
                        base64.b64decode(raw.encode("utf-8"))
                    )
                )
            )
        except Exception:
            return []


def build_input_output(problem):
    """Build the input_output dict expected by the test runner from public + private test cases."""
    public_tests = json.loads(problem["public_test_cases"]) if isinstance(problem["public_test_cases"], str) else problem["public_test_cases"]
    private_tests = decode_private_test_cases(problem["private_test_cases"]) if isinstance(problem["private_test_cases"], str) else problem["private_test_cases"]

    all_tests = public_tests + private_tests

    inputs = [t["input"] for t in all_tests]
    outputs = [t["output"] for t in all_tests]

    # Determine if it's stdin or functional (call-based)
    fn_name = None
    if all_tests and all_tests[0].get("testtype") == "functional":
        metadata = json.loads(problem["metadata"]) if isinstance(problem["metadata"], str) else problem["metadata"]
        fn_name = metadata.get("func_name", None)

    result = {
        "inputs": inputs,
        "outputs": outputs,
    }
    if fn_name:
        result["fn_name"] = fn_name

    return result


def generate_test_script(solution_code, test_data):
    """Generate a Python test script that runs the solution against test cases."""
    is_functional = "fn_name" in test_data
    fn_name = test_data.get("fn_name", "solve")

    # Write test data and solution to JSON for the subprocess to read
    # This avoids Windows command-line length limits

    if is_functional:
        script = f'''
import sys
import json
import io

# Load test data
test_data = json.loads({json.dumps(json.dumps(test_data))})

inputs = test_data["inputs"]
expected_outputs = test_data["outputs"]
fn_name = test_data.get("fn_name", "solve")

results = []

# Execute solution code to define the function
namespace = {{}}
solution_code = {json.dumps(solution_code)}
exec(solution_code, namespace)

# Find and instantiate Solution class, then get the method
sol_cls = namespace.get("Solution")
if sol_cls is not None:
    instance = sol_cls()
    fn = getattr(instance, fn_name, None)
    if fn is None:
        # fallback: first public method on the instance
        import inspect
        fn = next(
            (m for name, m in inspect.getmembers(instance, predicate=inspect.ismethod)
             if not name.startswith("_")),
            None
        )
else:
    # Not a class-based solution — look for a top-level function
    fn = namespace.get(fn_name)
    if fn is None:
        for name, obj in namespace.items():
            if callable(obj) and not name.startswith("_") and name not in ["json", "sys", "io", "inspect"]:
                fn = obj
                break

if fn is None:
    print(json.dumps([False] * len(inputs)))
    sys.exit(0)

# Parse inputs: split multi-line inputs by newline, parse each line as JSON
# This matches the official LiveCodeBench runner behavior
parsed_inputs = []
for inp in inputs:
    lines = inp.strip().split("\\n")
    args = [json.loads(line) for line in lines if line.strip()]
    parsed_inputs.append(args)

# Parse expected outputs as JSON values
parsed_outputs = [json.loads(out) for out in expected_outputs]

for i, (args, expected_val) in enumerate(zip(parsed_inputs, parsed_outputs)):
    try:
        result = fn(*args)

        # Handle tuples vs lists
        if isinstance(result, tuple):
            result = list(result)

        if result == expected_val:
            results.append(True)
        else:
            results.append(False)
    except Exception as e:
        results.append(False)

print(json.dumps(results))
'''
    else:
        # stdin-based: run each test case separately by executing the solution
        # with different stdin inputs
        script = f'''
import sys
import json
import io

solution_code = {json.dumps(solution_code)}
test_data = json.loads({json.dumps(json.dumps(test_data))})

inputs = test_data["inputs"]
expected_outputs = test_data["outputs"]

results = []

for i, (inp, expected) in enumerate(zip(inputs, expected_outputs)):
    try:
        old_stdin = sys.stdin
        old_stdout = sys.stdout
        sys.stdin = io.StringIO(inp)
        sys.stdout = io.StringIO()

        exec(solution_code, {{"__name__": "__main__"}})

        actual = sys.stdout.getvalue()
        sys.stdin = old_stdin
        sys.stdout = old_stdout

        actual_stripped = actual.strip()
        expected_stripped = expected.strip()
        if actual_stripped == expected_stripped:
            results.append(True)
        else:
            results.append(False)
    except Exception as e:
        try:
            sys.stdin = old_stdin
            sys.stdout = old_stdout
        except:
            pass
        results.append(False)

print(json.dumps(results))
'''

    return script


def run_solution_in_subprocess(solution_code, test_data, timeout=30):
    """Run a solution against test cases in a subprocess with timeout (Windows-compatible)."""
    script = generate_test_script(solution_code, test_data)

    # Write script to a temp file to avoid Windows command-line length limits
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".py", prefix="lcb_eval_")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(script)

        try:
            result = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tempfile.gettempdir(),
            )
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().split("\n")
                for line in reversed(lines):
                    try:
                        return json.loads(line), result.stderr
                    except json.JSONDecodeError:
                        continue
            return None, result.stderr[:500] if result.stderr else f"exit code {result.returncode}"
        except subprocess.TimeoutExpired:
            return None, "TIMEOUT"
        except Exception as e:
            return None, str(e)
    finally:
        try:
            os.unlink(tmp_path)
        except:
            pass


def main():
    answers_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "answers")
    solutions = load_solutions(answers_dir)
    print(f"Loaded {len(solutions)} solutions")
    print(f"Question IDs: {sorted(solutions.keys())}")
    print()

    # Load the LiveCodeBench dataset
    print("Loading LiveCodeBench code_generation_lite dataset from Hugging Face...")
    dataset = load_dataset(
        "livecodebench/code_generation_lite",
        split="test",
        trust_remote_code=True,
    )
    print(f"Total problems in dataset: {len(dataset)}")
    print()

    # Build a lookup by question_id
    dataset_by_id = {}
    for problem in dataset:
        dataset_by_id[problem["question_id"]] = problem

    # Match solutions to problems
    matched = []
    unmatched_ids = []
    for qid in sorted(solutions.keys()):
        if qid in dataset_by_id:
            matched.append((qid, dataset_by_id[qid], solutions[qid]))
        else:
            unmatched_ids.append(qid)

    if unmatched_ids:
        print(f"WARNING: {len(unmatched_ids)} solutions have no matching problem: {unmatched_ids}")
    print(f"Matched {len(matched)} solutions to dataset problems")
    print()

    # Evaluate each solution
    results = []
    easy_pass = 0
    easy_total = 0
    medium_pass = 0
    medium_total = 0
    hard_pass = 0
    hard_total = 0

    for idx, (qid, problem, code) in enumerate(matched):
        difficulty = problem.get("difficulty", "unknown")
        test_type = "functional" if "fn_name" in build_input_output(problem) else "stdin"
        print(f"[{idx+1}/{len(matched)}] Evaluating {qid} ({difficulty}, {test_type})...", end=" ", flush=True)

        try:
            test_data = build_input_output(problem)
            num_tests = len(test_data["inputs"])

            # Calculate timeout based on number of tests
            timeout = max(30, num_tests * 3)

            # DEBUG: Log test details for stdin-type problems
            if test_type == "stdin":
                print(f"[tests={num_tests}, timeout={timeout}s] ", end="", flush=True)
                # Save the generated script for first stdin problem for inspection
                debug_script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"debug_script_{qid}.py")
                debug_script = generate_test_script(code, test_data)
                with open(debug_script_path, "w", encoding="utf-8") as dbg_f:
                    dbg_f.write(f"# DEBUG: Generated test script for {qid}\n")
                    dbg_f.write(f"# test_type=stdin, num_tests={num_tests}, timeout={timeout}\n")
                    dbg_f.write(f"# First 200 chars of first input:\n")
                    first_input = test_data["inputs"][0] if test_data["inputs"] else ""
                    dbg_f.write(f"# {repr(first_input[:200])}\n\n")
                    dbg_f.write(debug_script)

            test_results, stderr = run_solution_in_subprocess(code, test_data, timeout=timeout)

            if test_results is None:
                err_msg = stderr[:100] if stderr else "Unknown error"
                print(f"RUN ERROR ({err_msg})")
                results.append({
                    "question_id": qid,
                    "difficulty": difficulty,
                    "passed": False,
                    "test_results": [],
                    "error": stderr[:200] if stderr else "Unknown error",
                })
            else:
                passed_count = sum(1 for r in test_results if r is True)
                all_passed = all(r is True for r in test_results) and len(test_results) == num_tests

                status = "PASS" if all_passed else f"FAIL ({passed_count}/{num_tests})"
                print(status)

                if all_passed:
                    if difficulty == "easy":
                        easy_pass += 1
                    elif difficulty == "medium":
                        medium_pass += 1
                    elif difficulty == "hard":
                        hard_pass += 1

                results.append({
                    "question_id": qid,
                    "difficulty": difficulty,
                    "passed": all_passed,
                    "test_results": test_results,
                    "num_tests": num_tests,
                    "passed_tests": passed_count,
                })

        except Exception as e:
            print(f"ERROR: {repr(e)}")
            results.append({
                "question_id": qid,
                "difficulty": difficulty,
                "passed": False,
                "test_results": [],
                "error": repr(e),
            })

        if difficulty == "easy":
            easy_total += 1
        elif difficulty == "medium":
            medium_total += 1
        elif difficulty == "hard":
            hard_total += 1

    # Summary
    total_pass = sum(1 for r in results if r["passed"])
    total_problems = len(results)

    print()
    print("=" * 60)
    print("EVALUATION RESULTS")
    print("=" * 60)
    if total_problems > 0:
        print(f"Total:   {total_pass}/{total_problems} passed ({100*total_pass/total_problems:.1f}%)")
    else:
        print("Total:   0/0 passed (no problems matched)")
    if easy_total > 0:
        print(f"Easy:    {easy_pass}/{easy_total} passed ({100*easy_pass/easy_total:.1f}%)")
    if medium_total > 0:
        print(f"Medium:  {medium_pass}/{medium_total} passed ({100*medium_pass/medium_total:.1f}%)")
    if hard_total > 0:
        print(f"Hard:    {hard_pass}/{hard_total} passed ({100*hard_pass/hard_total:.1f}%)")
    print("=" * 60)

    # Per-problem breakdown
    print()
    print("Per-problem breakdown:")
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        extra = ""
        if "passed_tests" in r:
            extra = f" ({r['passed_tests']}/{r['num_tests']} tests)"
        elif "error" in r:
            extra = f" (error: {r['error'][:60]})"
        print(f"  {r['question_id']:12s} [{r['difficulty']:6s}] {status}{extra}")

    # Save detailed results
    output_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_results.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nDetailed results saved to: {output_file}")


if __name__ == "__main__":
    main()
