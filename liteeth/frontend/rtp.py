from liteeth.common import *

from litex.soc.interconnect.packet import Depacketizer, Packetizer


class LiteEthRTPPacketizer(Packetizer):
    def __init__(self, dw):
        Packetizer.__init__(self,
            eth_rtp_description(dw),
            eth_udp_user_description(dw),
            rtp_header)

class LiteEthRTPTX(Module):
    def __init__(self, ip_address, udp_port, pkt_size, fifo_depth=512):
        self.submodules.fifo = fifo = stream.SyncFIFO([("data", 8)], fifo_depth)
        self.submodules.rtp_packetizer = rtp_packetizer = LiteEthRTPPacketizer(8)

        seq_cnt = Signal(16)

        self.sink = fifo.sink
        self.source = rtp_packetizer.source

        self.comb += fifo.source.connect(rtp_packetizer.sink)

        self.comb += self.source.dst_port.eq(udp_port)
        self.comb += self.source.src_port.eq(udp_port)
        self.comb += self.source.ip_address.eq(ip_address)
        self.comb += self.source.length.eq(pkt_size+rtp_header_length)

        self.comb += [
            rtp_packetizer.sink.param.ver.eq(2),
            rtp_packetizer.sink.param.p.eq(0),
            rtp_packetizer.sink.param.x.eq(0),
            rtp_packetizer.sink.param.cc.eq(0),
            rtp_packetizer.sink.param.m.eq(0),
            rtp_packetizer.sink.param.pt.eq(0),
            rtp_packetizer.sink.param.sequence_number.eq(seq_cnt),
            rtp_packetizer.sink.param.timestamp.eq(0),
            rtp_packetizer.sink.param.ssrc.eq(12345678),
        ]

        self.sync += If(rtp_packetizer.sink.ready & rtp_packetizer.sink.valid & rtp_packetizer.sink.last, seq_cnt.eq(seq_cnt+1))

class LiteEthRTP(Module):
    def __init__(self, port, ip_address, udp_port, pkt_size):
        ip_address = convert_ip(ip_address)
        self.submodules.tx = tx = LiteEthRTPTX(ip_address, udp_port, pkt_size)
        # self.submodules.rx = rx = LiteEthRTPRX()

        self.comb += [
            tx.source.connect(port.sink),
            # port.source.connect(rx.sink),
        ]

        self.sink = tx.sink
        # self.source = rx.source
