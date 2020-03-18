from liteeth.common import *

from litex.soc.interconnect.packet import Depacketizer, Packetizer


class LiteEthRTPRAWPacketizer(Packetizer):
    def __init__(self, dw):
        Packetizer.__init__(self,
            eth_rtp_raw_description(dw),
            eth_udp_user_description(dw),
            rtp_raw_header)

class LiteEthRTPJPEGPacketizer(Packetizer):
    def __init__(self, dw):
        Packetizer.__init__(self,
            eth_rtp_jpeg_description(dw),
            eth_udp_user_description(dw),
            rtp_jpeg_header)


class LiteEthRTPTXJPEG(Module):
    def __init__(self, ssrc, pkt_size=1024, width=1280, height=720, q=0):
        self.submodules.fifo       = fifo       = stream.SyncFIFO([("data", 8)], 2048)
        self.submodules.packetizer = packetizer = LiteEthRTPJPEGPacketizer(8)
        self.sink                  = sink       = fifo.sink
        self.source                = source     = packetizer.source

class LiteEthRTPTXRAW(Module):
    def __init__(self, ssrc, pkt_size=1024, width=1280, height=720, bpp=2):
        self.submodules.fifo       = fifo       = stream.SyncFIFO([("data", 8)], 2048)
        self.submodules.packetizer = packetizer = LiteEthRTPRAWPacketizer(8)
        self.submodules.fsm        = fsm        = FSM(reset_state="IDLE")
        self.sink                  = sink       = fifo.sink
        self.source                = source     = packetizer.source

        line_pos   = Signal(16)
        line_cnt   = Signal(16)
        target_len = Signal(16)
        rx_len     = Signal(16)
        tx_len     = Signal(16)
        frame_end  = Signal()

        cnt        = Signal(32)
        ts         = Signal(32)
        sequence   = Signal(32)

        self.comb += If(line_pos+pkt_size > width*bpp,
                         target_len.eq(width*bpp-line_pos)
                     ).Else(
                         target_len.eq(pkt_size)
                     )

        fsm.act("IDLE",
            If(sink.valid,
                NextState("RX"),
            )
        )
        fsm.act("RX",
            sink.connect(fifo.sink),
            fifo.sink.last.eq((rx_len == target_len-1) | sink.last)
            If(sink.valid & sink.ready,
                NextValue(rx_len, rx_len+1),
                If(fifo.sink.last,
                    NextValue(rx_len, 0),
                    NextValue(tx_len, rx_len+1),
                    NextValue(frame_end, sink.last),
                    NextState("TX"),
                ),
            ),
        )
        fsm.act("TX",
            fifo.source.connect(packetizer.sink),
            If(packetizer.sink.ready & packetizer.sink.valid & packetizer.sink.last,
                NextState("IDLE"),
            )
        )

        self.comb += [
            packetizer.sink.param.ver.eq(2),
            packetizer.sink.param.m.eq(frame_end),
            packetizer.sink.param.pt.eq(80),
            packetizer.sink.param.seq.eq(sequence[0:16]),
            packetizer.sink.param.ext_seq.eq(sequence[16:32]),
            packetizer.sink.param.length.eq(tx_len),
            packetizer.sink.param.ts.eq(ts),
            packetizer.sink.param.ssrc.eq(ssrc),
            
        ]

class LiteEthRTPTX(Module):
    def __init__(self, ip_address, udp_port, pkt_size, fifo_depth=512):
        self.submodules.fifo = fifo = stream.SyncFIFO([("data", 8)], fifo_depth)
        self.source          = stream.Endpoint(eth_udp_user_description(8))
        self.sink            = fifo.sink

        # TODO: replace with CSRs
        ssrc = Signal(32)
        mode = Signal()

        self.comb += [
            ssrc.eq(12345678),
            mode.eq(1),
        ]

        # JPEG & RAW
        self.submodules.jpeg = jpeg = LiteEthRTPTXJPEG(ssrc, pkt_size)
        self.submodules.raw  = raw  = LiteEthRTPTXRAW(ssrc, pkt_size)

        # TX path select
        self.comb += [
            If(mode, raw.source.connect(self.source), fifo.source.connect(raw.sink))
            .Else(jpeg.source.connect(self.source), fifo.source.connect(jpeg.sink)),
            self.source.dst_port.eq(udp_port),
            self.source.src_port.eq(udp_port),
            self.source.ip_address.eq(ip_address),
        ]

class LiteEthRTP(Module):
    def __init__(self, udp, udp_port=9000, pkt_size=1024, ip_address="192.168.100.200"):
        port = udp.crossbar.get_port(udp_port, 8)

        if isinstance(ip_address, str):
            ip_address = convert_ip(ip_address)

        self.submodules.tx = tx = LiteEthRTPTX(ip_address, udp_port, pkt_size)
        # self.submodules.rx = rx = LiteEthRTPRX()

        self.comb += [
            tx.source.connect(port.sink),
            # port.source.connect(rx.sink),
        ]

        self.sink = tx.sink
        # self.source = rx.source
