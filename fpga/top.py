from migen import Module, Signal, If, run_simulation, ClockDomain, Cat, ClockSignal, ResetSignal, Instance
from migen.genlib.fsm import FSM, NextState, NextValue
from migen.genlib.resetsync import AsyncResetSynchronizer
from migen.genlib.cdc import ClockDomainsRenamer
from migen.genlib.fifo import AsyncFIFO
from misoc.interconnect import stream

from fast_serial import Packager, FastSerialTX


class Decoder(Module):
    def __init__(self, n_bits, n_words):
        self.n_bits = n_bits
        self.n_words = n_words

        self.data = Signal()
        self.wck = Signal()

        self.source = stream.Endpoint([
            ("data", n_bits),
        ])

        ###

        self.word = Signal(n_bits)
        self.bit = Signal(max=n_bits)
        self.word_num = Signal(max=n_words + 1)

        self.last_bit = (self.bit == 0) & (self.word_num > 0)

        self.sync += self.word.eq(self.word << 1 | self.data)
        self.sync += self.source.stb.eq(self.last_bit)
        self.sync += self.source.eop.eq(self.word_num == 1)

        self.comb += self.source.payload.data.eq(self.word)

        self.sync += \
            If(self.wck,
                self.bit.eq(n_bits - 2),
                self.word_num.eq(n_words),
            ).Elif(self.last_bit,
                self.bit.eq(n_bits - 1),
                self.word_num.eq(self.word_num - 1),
            ).Else(
                self.bit.eq(self.bit - 1),
            )


class SyncDecoder(Module):
    def __init__(self, n_bits, n_words):
        self.data = Signal()
        self.wck = Signal()
        self.bck = Signal()

        layout = [("data", n_bits)]

        self.clock_domains.cd_decode = ClockDomain()
        self.specials += AsyncResetSynchronizer(self.cd_decode, ResetSignal("sys"))

        decoder = ClockDomainsRenamer("decode")(Decoder(n_bits, n_words))
        self.submodules.decoder = decoder

        cdr = ClockDomainsRenamer({"read": "sys", "write": "decode"})
        self.submodules.fifo = cdr(stream.AsyncFIFO(layout, 8))

        self.source = self.fifo.source

        self.comb += [
            self.cd_decode.clk.eq(self.bck),
            decoder.wck.eq(self.wck),
            decoder.data.eq(self.data),
            decoder.source.connect(self.fifo.sink),
        ]


def test_decoder():

    def feed_in(dut, tests):
        for test in tests:
            if test is None:
                yield
                continue

            yield dut.wck.eq(1)
            for word in test:
                for bit in range(dut.n_bits)[::-1]:
                    yield dut.data.eq((word >> bit) & 1)
                    yield
                    yield dut.wck.eq(0)

    def test_out(dut, tests):
        for test in tests:
            if test is None:
                continue

            for i, word in enumerate(test[:dut.n_words]):
                while not (yield dut.source.stb):
                    yield
                assert (yield dut.source.payload.data) == word
                assert (yield dut.source.eop) == (i == dut.n_words - 1)

                yield

    tests = [
        None, None, None, None,
        [0x81, 0xff],
        [0x00, 0xff],
        None, None, None, None,
        [0x00, 0xff, 0x81],
        [0x00, 0xff],
    ]

    dut = Decoder(8, 2)
    dut.clock_domains.cd_sys = ClockDomain("sys")
    run_simulation(dut, [feed_in(dut, tests), test_out(dut, tests)], vcd_name="decoder.vcd")


class Top(Module):
    def __init__(self, platform):

        clk12 = platform.request("clk12")
        self.clock_domains.cd_por = ClockDomain(reset_less=True)
        self.clock_domains.cd_sys = ClockDomain()
        reset_delay = Signal(max=1024)
        self.comb += [
            self.cd_por.clk.eq(clk12),
            self.cd_sys.clk.eq(clk12),
            self.cd_sys.rst.eq(reset_delay != 1023)
        ]
        self.sync.por += \
            If(reset_delay != 1023,
                reset_delay.eq(reset_delay + 1)
            )

        self.submodules.dec = SyncDecoder(8, 3 * 7)
        self.comb += [
            self.dec.data.eq(platform.request("din")),
            self.dec.wck.eq(platform.request("wck")),
            self.dec.bck.eq(platform.request("bck")),
        ]

        self.submodules.packager = Packager(0x47)

        serial = platform.request("fast_serial")
        self.submodules.tx = FastSerialTX(serial)
        self.comb += self.tx.sink.payload.port.eq(1)

        self.comb += [
            self.dec.source.connect(self.packager.sink),
            self.packager.source.connect(self.tx.sink),
        ]

        # 96.000 MHz pll and /10 for mclk
        self.mclk = platform.request("mclk")
        pll_out = Signal()
        self.specials.pll = Instance("pll",
                                     i_clock_in=ClockSignal("sys"),
                                     o_clock_out=pll_out)
        self.clock_domains.cd_pll = ClockDomain(reset_less=True)
        self.comb += self.cd_pll.clk.eq(pll_out)

        self.counter = Signal(max=5)

        self.sync.pll += [
            If(self.counter >= 4,
                self.counter.eq(0),
                self.mclk.eq(~self.mclk),
            ).Else(
                self.counter.eq(self.counter + 1),
            )
        ]


if __name__ == "__main__":
    import sys
    from migen.build.generic_platform import Pins, Subsignal, IOStandard
    from migen.build.platforms import ice40_hx8k_b_evn

    plat = ice40_hx8k_b_evn.Platform()

    # remove the -l option: auto-promote nets to globals
    plat.toolchain.build_template[1] = "arachne-pnr -r {pnr_pkg_opts} -p {build_name}.pcf {build_name}.blif -o {build_name}.txt"

    plat.add_extension([
        ("debug", 0, Pins("P16 N16 M16")),
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

    plat.add_source("pll.v")

    plat.build(Top(plat))
    plat.create_programmer().load_bitstream("build/top.bin")
