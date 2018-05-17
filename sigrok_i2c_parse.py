import sys
import json


def get_txns():
    """Parse the output of sigrok-cli, yielding i2c transactions.

    Each transaction is just a list of bytes. We don't know which side was
    writing anyway so there's nothing lost here if we don't care about repeated
    starts (we don't).

    Used like:

        sigrok-cli \
            --input-file i2c_trace_sr.csv \
            --input-format csv -P i2c \
          | python analyse_trace.py  > i2c_trace.json
    """
    txn = []
    for line in sys.stdin.readlines():
        parts = line.strip().split()[1:]
        if parts[0] == "Start":
            txn = []
        elif parts[0] == "Stop":
            yield txn
        elif parts[0] == "Data":
            txn.append((parts[1].rstrip(":"), int(parts[2], 16)))
        elif parts[0] == "Address":
            txn.append((parts[1].rstrip(":"), int(parts[2], 16)))


if __name__ == "__main__":
    txns = list(get_txns())
    json.dump(txns, sys.stdout)
