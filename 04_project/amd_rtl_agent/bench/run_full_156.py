"""Run the 156-problem 27B evaluation through agent.py's protected benchmark.

An explicit output directory is required. Resume only with --resume and the
same configuration. --status reads benchmark.json without running any model.
Configure LLM_BASE_URL, LLM_MODEL and VIVADO_BIN for the evaluation machine.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import agent

DATASET = ROOT / "bench" / "verilog-eval" / "dataset_spec-to-rtl"
TOTAL = 156
DEFAULTS = {
    "LLM_BASE_URL": "https://ws-zx533vazjgfeshi6.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    "LLM_MODEL": "qwen3.6-27b",
    "LLM_ENABLE_THINKING": "false",
    "LLM_MAX_TOKENS": "2048",
    "LLM_TIMEOUT_SECONDS": "120",
    "LLM_TEMPERATURE": "0.2",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--dataset', default=str(DATASET))
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--samples', type=int, choices=range(1, 6), default=1)
    parser.add_argument('--repairs', type=int, choices=range(3), default=1)
    parser.add_argument('--seed', type=int, default=1)
    args = parser.parse_args(argv)
    if args.status:
        path = Path(args.output_dir) / 'benchmark.json'
        if not path.is_file():
            parser.error(f'no benchmark.json in {args.output_dir}; legacy progress.jsonl is not a resumable experiment')
        print(json.dumps(json.loads(agent.read_text(path)), ensure_ascii=False))
        return 0
    count = len(list(Path(args.dataset).rglob('*_prompt.txt')))
    if count != TOTAL:
        parser.error(f'expected {TOTAL} problems, found {count}')
    if os.environ.get('LLM_MOCK_FILE'):
        parser.error('LLM_MOCK_FILE is set; use agent.py benchmark explicitly for mock tests')
    for key, value in DEFAULTS.items():
        os.environ.setdefault(key, value)
    # Compatibility with the old launcher; credentials remain untracked.
    key_file = ROOT / 'outputs' / '.llm_api_key'
    if not os.environ.get('LLM_API_KEY') and key_file.is_file():
        os.environ['LLM_API_KEY'] = agent.read_text(key_file).strip()
    command = ['benchmark', '--dataset', args.dataset, '--output-dir', args.output_dir,
               '--samples', str(args.samples), '--repairs', str(args.repairs), '--seed', str(args.seed)]
    if args.resume:
        command.append('--resume')
    return agent.main(command)


if __name__ == '__main__':
    raise SystemExit(main())
