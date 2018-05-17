from serial import Serial
import sys
import numpy as np
from numpy.lib.stride_tricks import as_strided
import soundfile as sf

nch = 7
nbytes = 3
framelen = nch * nbytes + 1
syncword = 0x47


class RX(object):

    def __init__(self, port):
        self.serial = Serial(port=port)

    def sync(self):
        # try to clear out buffers
        self.serial.read(1024)

        while ord(self.serial.read()) != syncword:
            pass

    def read(self, nframes):
        data = self.serial.read(framelen * nframes)

        data_bytes = np.frombuffer(data, dtype=np.uint8)

        if np.any(data_bytes[framelen - 1::framelen] != syncword):
            raise Exception("lost sync")
        else:
            assert(nbytes == 3)
            # interpret as a 2d array with overlaps between the elements,
            # then clean up each element
            data_shaped = as_strided(data_bytes.view(np.dtype('>i4')),
                                     strides=(framelen, 3),
                                     shape=(nframes, nch))
            data_decoded = (data_shaped & np.int32(0xffffff00)) >> 8

            return data_decoded


def parse_args():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("outfile")
    parser.add_argument("-t", "--tty", default="/dev/ttyUSB2")
    parser.add_argument("-r", "--rate", type=int, default=16000)
    return parser.parse_args()


def main():
    args = parse_args()

    with sf.SoundFile(args.outfile, 'w', args.rate, nch, subtype="PCM_24") as wav_file:
        rx = RX(args.tty)

        rx.sync()

        print("recording")
        try:
            while True:
                wav_file.write(rx.read(512))
        except KeyboardInterrupt:
            pass
    print("done")


if __name__ == "__main__":
    main()
