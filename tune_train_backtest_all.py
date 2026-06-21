"""
Run the full tune -> train -> backtest pipeline for multiple symbols in one command.

Intended for an unattended overnight run:
    python tune_train_backtest_all.py
    python tune_train_backtest_all.py --symbols EURUSD USDJPY --trials 500 --gpu

Each step's output is streamed to the console AND appended to a timestamped log file,
so progress can be checked the next morning even if the terminal was closed.
"""
import argparse
import subprocess
import sys
from datetime import datetime

DEFAULT_SYMBOLS = ['EURUSD', 'USDJPY', 'XAUUSD', 'GBPUSD']


def run(cmd, log):
    header = f"\n=== {datetime.now().isoformat(timespec='seconds')} === {' '.join(cmd)} ===\n"
    print(header, end='')
    log.write(header)
    log.flush()

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in proc.stdout:
        print(line, end='')
        log.write(line)
        log.flush()
    proc.wait()
    return proc.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Tune, train, and backtest all symbols in one run.")
    parser.add_argument('--symbols', nargs='+', default=DEFAULT_SYMBOLS)
    parser.add_argument('--trials', type=int, default=200,
                         help='Optuna trials per symbol. Kept low by default: see optimize_pipeline.py '
                              '--trials help for why more trials raise overfitting risk on this little data.')
    parser.add_argument('--gpu', action='store_true', help='Pass --gpu through to optimize_pipeline.py')
    parser.add_argument('--skip-tune', action='store_true',
                         help='Skip optimize_pipeline.py, reuse existing best_params_<symbol>.json')
    args = parser.parse_args()

    log_path = f"pipeline_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    succeeded, failed = [], []

    with open(log_path, 'w') as log:
        for sym in args.symbols:
            if not args.skip_tune:
                cmd = [sys.executable, 'optimize_pipeline.py', '--symbol', sym, '--trials', str(args.trials)]
                if args.gpu:
                    cmd.append('--gpu')
                if not run(cmd, log):
                    print(f"[WARN] Tuning failed for {sym}; skipping training for this symbol.\n")
                    failed.append(sym)
                    continue

            if not run([sys.executable, 'train_and_save.py', '--symbol', sym], log):
                print(f"[WARN] Training failed for {sym}.\n")
                failed.append(sym)
                continue

            succeeded.append(sym)

        run([sys.executable, 'backtest_single_symbol.py'], log)

    print(f"\n=== Pipeline finished. Trained: {succeeded}. Failed: {failed}. Full log: {log_path} ===")


if __name__ == "__main__":
    main()
