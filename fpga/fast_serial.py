from migen import Module, Signal, If, run_simulation, ClockDomain, Cat, ClockSignal, ResetSignal, Instance
from migen.genlib.fsm import FSM, NextState, NextValue
from migen.genlib.resetsync import AsyncResetSynchronizer
from migen.genlib.cdc import ClockDomainsRenamer, MultiReg
from migen.genlib.fifo import AsyncFIFO
from migen.genlib.record import Record

from misoc.interconnect import stream


class FastSerialTX(Module):
    """Transmitter for ftdi 'fast' clocked serial."""

    def __init__(self, pads):
        self.sink = stream.Endpoint([
            ("data", 8),
            ("port", 1),
        ])

        ###

        cts = Signal()
        self.specials += MultiReg(pads.cts, cts)

        di = Signal(reset=1)
        self.comb += pads.di.eq(di)

        tx_reg = Signal(9)
        tx_bit = Signal(max=10)

        self.sync += [
            self.sink.ack.eq(0),
            If(self.sink.stb & cts & (tx_bit == 0) & ~self.sink.ack,
                tx_reg.eq(Cat(self.sink.payload.data, self.sink.payload.port)),
                tx_bit.eq(9),
                di.eq(0),
            ).Elif(tx_bit > 0,
                tx_bit.eq(tx_bit - 1),
                di.eq(tx_reg[0]),
                tx_reg.eq(tx_reg[1:]),
                If(tx_bit == 1,
                    self.sink.ack.eq(1),
                ),
            ).Else(
                di.eq(1),
            )
        ]

        self.comb += [
            pads.clk.eq(~ClockSignal()),
        ]


def test_fast_serial_tx():

    def feed_in(dut, pads, txns):
        for data, port in txns:
            yield dut.sink.payload.data.eq(data)
            yield dut.sink.payload.port.eq(port)
            yield dut.sink.stb.eq(1)
            yield
            while not (yield dut.sink.ack):
                yield
            yield dut.sink.stb.eq(0)

    def test_out(dut, pads, txns):
        for data, port in txns:
            while not (not (yield pads.di) and (yield pads.cts)):
                yield
            rx_data = 0
            for i in range(8):
                yield
                rx_data |= (yield pads.di) << i
            yield
            rx_port = (yield pads.di)
            yield

            assert rx_data == data
            assert rx_port == port

    def drive_cts(dut, pads):
        yield pads.cts.eq(0)
        for i in range(5): yield
        yield pads.cts.eq(1)

    txns = [
        (0b01010101, 0),
        (0x00, 1),
    ]

    pads = Record([("di", 1),
                   ("clk", 1),
                   ("di", 1),
                   ("cts", 1),
                   ])

    dut = FastSerialTX(pads)

    run_simulation(dut, [feed_in(dut, pads, txns),
                         test_out(dut, pads, txns),
                         drive_cts(dut, pads),
                         ],
                   vcd_name="serial_tx.vcd")


class Packager(Module):
    """Add a syncword between packets."""

    def __init__(self, syncword):
        self.sink = stream.Endpoint([
            ("data", 8),
        ])

        self.source = stream.Endpoint([
            ("data", 8),
        ])

        ###

        self.submodules.fsm = FSM(reset_state="DATA")

        self.fsm.act("DATA",
                     self.source.payload.data.eq(self.sink.payload.data),
                     self.source.stb.eq(self.sink.stb),
                     self.sink.ack.eq(self.source.ack),
                     If(self.sink.stb & self.sink.ack & self.sink.eop,
                         NextState("SYNC"),
                     ),
        )

        self.fsm.act("SYNC",
                     self.source.payload.data.eq(syncword),
                     self.source.stb.eq(1),
                     self.sink.ack.eq(0),
                     If(self.source.stb & self.source.ack,
                         NextState("DATA"),
                     ),
        )


def test_packager():
    syncword = 0x47

    def feed_in(dut, txns):
        for datas in txns:
            for i, data in enumerate(datas):
                yield dut.sink.payload.data.eq(data)
                yield dut.sink.stb.eq(1)
                yield dut.sink.eop.eq(i == len(datas) - 1)
                yield
                while not (yield dut.sink.ack):
                    yield
                yield dut.sink.stb.eq(0)

    def test_out(dut, txns):
        yield dut.source.ack.eq(1)

        for datas in txns:
            for data in datas + [syncword]:
                while not (yield dut.source.ack & dut.source.stb):
                    yield

                assert (yield dut.source.data) == data
                yield

    txns = [
        [0x00],
        [0x01, 0x02],
    ]

    dut = Packager(syncword)

    run_simulation(dut, [feed_in(dut, txns), test_out(dut, txns)], vcd_name="packager.vcd")


class Top(Module):
    def __init__(self, platform):
        serial = platform.request("fast_serial")

        clk12 = platform.request("clk12")

        self.clock_domains.cd_sys = ClockDomain()

        if True:
            self.specials.pll = Instance("pll_test",
                                         i_clock_in=clk12,
                                         o_clock_out=self.cd_sys.clk)
        else:
            self.comb += self.cd_sys.clk.eq(clk12)

        self.clock_domains.cd_por = ClockDomain(reset_less=True)
        reset_delay = Signal(max=1024)
        self.comb += [
            self.cd_por.clk.eq(self.cd_sys.clk),
            self.cd_sys.rst.eq(reset_delay != 1023)
        ]
        self.sync.por += If(reset_delay != 1023,
                            reset_delay.eq(reset_delay + 1))

        self.submodules.tx = FastSerialTX(serial)
        self.submodules.packager = Packager(0x47)
        self.comb += self.packager.source.connect(self.tx.sink)
        self.comb += self.tx.sink.payload.port.eq(1)

        counter = Signal(5)

        self.comb += [
            self.packager.sink.stb.eq(1),
            self.packager.sink.payload.data.eq(counter),
            self.packager.sink.eop.eq(counter == 2 ** counter.nbits - 1)
        ]

        self.sync += [
            If(self.packager.sink.stb & self.packager.sink.ack,
               counter.eq(counter + 1)
            ),
        ]

        debug = platform.request("debug")
        self.comb += [
            debug.eq(Cat(serial.clk, serial.di, serial.cts)),
        ]


if __name__ == "__main__":
    import sys
    if sys.argv[1] == "sim":
        pass
        # test_decoder()
    elif sys.argv[1] == "build":
        from migen.build.generic_platform import Pins, Subsignal, IOStandard
        from migen.build.platforms import ice40_hx8k_b_evn

        plat = ice40_hx8k_b_evn.Platform()

        # remove the -l option: auto-promote nets to globals
        plat.toolchain.build_template[1] = "arachne-pnr -r {pnr_pkg_opts} -p {build_name}.pcf {build_name}.blif -o {build_name}.txt"

        plat.add_extension([
            ("debug", 0, Pins("P16 N16 M16 K15")),
            ("mclk", 0, Pins("R15")),
            ("wck", 0, Pins("P15")),
            ("din", 0, Pins("M15")),
            ("bck", 0, Pins("L16")),
            ("fast_serial", 0,
             Subsignal("di", Pins("B10")),
             Subsignal("clk", Pins("B12")),
             Subsignal("do", Pins("B13")),
             Subsignal("cts", Pins("A15")),
             IOStandard("LVCMOS33"),
             ),
        ])

        plat.add_source("pll_test.v")

        plat.build(Top(plat))
        plat.create_programmer().load_bitstream("build/top.bin")
    elif sys.argv[1] == "prog":
        from migen.build.platforms import ice40_hx8k_b_evn
        plat = ice40_hx8k_b_evn.Platform()
        plat.create_programmer().load_bitstream("build/top.bin")
