import json


def get_regs(trace):
    """Get the status of registers on each device on the i2c bus."""
    regs = {}
    pages = {}
    for txn in trace:
        if len(txn) != 3:
            continue

        device = regs.setdefault(txn[0][1], {})

        if txn[1][1] == 0:
            pages[txn[0][1]] = txn[2][1]
        else:
            page = pages.get(txn[0][1], 0)
            device.setdefault(page, {})[txn[1][1]] = txn[2][1]

    return regs


def get_writes(regs):
    """Get i2c transactions to recreate register states."""
    for device_no in sorted(regs):
        device_regs = regs[device_no]

        for page_no in sorted(device_regs):
            page_regs = device_regs[page_no]

            yield (device_no, 0, page_no)

            for reg_no in sorted(page_regs):
                yield (device_no, reg_no, page_regs[reg_no])


def to_c_lines(writes):
    """Convert transactions to a C array."""
    for device_no, reg_no, value in writes:
        yield "{{{:#04x}, {:#04x}, {:#04x}}},\n".format(device_no, reg_no, value)


if __name__ == "__main__":
    trace = json.load(open("i2c_trace.json"))
    regs = get_regs(trace)
    adc_regs = {d: r for d, r in regs.items() if d in range(24, 28)}

    with open("micro/src/i2c_txns.inc", "w") as f:
        f.writelines(to_c_lines(get_writes(adc_regs)))
