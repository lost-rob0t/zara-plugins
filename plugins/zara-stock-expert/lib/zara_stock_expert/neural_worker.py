from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zara_stock_expert.neural import MAX_BYTES, canonical


def main() -> None:
    try:
        raw = sys.stdin.buffer.read(2 * MAX_BYTES + 1)
        if len(raw) > 2 * MAX_BYTES:
            raise ValueError('oversized input')
        request = json.loads(raw)
        import torch
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        from zara_stock_expert.neural_torch import forecast, train
        operation = {'train': train, 'forecast': forecast}[request['operation']]
        result = dict(ok=True, value=operation(**request['arguments']))
    except ImportError:
        result = dict(ok=False, error='optional_pytorch_dependency_missing')
    except (ValueError, KeyError, TypeError):
        result = dict(ok=False, error='invalid_neural_data_or_artifact')
    except Exception:
        result = dict(ok=False, error='neural_computation_failed')
    encoded = canonical(result)
    if len(encoded.encode('utf-8')) > MAX_BYTES:
        encoded = canonical(dict(ok=False, error='neural_output_bound'))
    sys.stdout.write(encoded)


if __name__ == '__main__':
    main()
