from liteeth.common import *

from litex.soc.interconnect.packet import Depacketizer, Packetizer


class LiteEthRTPPacketizer(Packetizer):
    def __init__(self, dw):
        Packetizer.__init__(self,
            eth_rtp_description(dw),
            eth_udp_user_description(dw),
            rtp_header)

class PacketSplitter(Module):
    def __init__(self, pkt_size):
        self.sink   = sink   = stream.Endpoint([("data", 8)])
        self.source = source = stream.Endpoint([("data", 8)])

        self.last = Signal()
        self.len  = Signal(max=pkt_size)
        pkt_len   = Signal(max=pkt_size)

        self.submodules.fifo = fifo = stream.SyncFIFO([("data", 8)], 2048)

        self.submodules.fsm  = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE", 
            If(sink.ready,
                NextState("RX")
            )
        )
        fsm.act("RX",
            sink.connect(fifo.sink),
            fifo.sink.last.eq((pkt_len == pkt_size-1) | sink.last),
            If(sink.ready & sink.valid,
                NextValue(pkt_len, pkt_len+1),
                If(fifo.sink.last,
                    NextValue(self.len, pkt_len+1),
                    NextState("TX"),
                    If(sink.last,
                        NextValue(self.last, 1),
                    ),
                ),
            ),
        )
        fsm.act("TX",
            fifo.source.connect(source),
            If(source.ready & source.valid & source.last,
                NextValue(self.len, 0),
                NextValue(self.last, 0),
                NextState("IDLE"),
            ),
        )

class RTPParams(Module):
    def __init__(self, m=0, pt=0, seq=0, ts=0, ssrc=0):
        self.sink   = sink   = stream.Endpoint(eth_rtp_description(8))
        self.source = source = stream.Endpoint(eth_rtp_description(8))

        self.comb += [
            sink.connect(source),
            source.param.ver.eq(2),
            source.param.p.eq(0),
            source.param.x.eq(0),
            source.param.cc.eq(0),
            source.param.m.eq(m),
            source.param.pt.eq(pt),
            source.param.sequence_number.eq(seq),
            source.param.timestamp.eq(ts),
            source.param.ssrc.eq(ssrc),
        ]

class LiteEthRTPTXJPEG(Module):
    def __init__(self, ts, ssrc, pkt_size):
        self.submodules.splitter   = splitter   = PacketSplitter(pkt_size)
        self.submodules.packetizer = packetizer = LiteEthRTPPacketizer(8)
        self.submodules.params     = params     = RTPParams(ts=ts, ssrc=ssrc, pt=26)
        self.source                = source     = stream.Endpoint(eth_udp_user_description(8))
        self.sink                  = sink       = stream.Endpoint([("data", 8)])

class LiteEthRTPTXRAW(Module):
    def __init__(self, ts, ssrc, pkt_size):
        # TODO: replace with CSR
        pt = Signal(7)
        self.comb += pt.eq(80)

        self.submodules.splitter   = splitter   = PacketSplitter(pkt_size)
        self.submodules.packetizer = packetizer = LiteEthRTPPacketizer(8)
        self.submodules.params     = params     = RTPParams(ts=ts, ssrc=ssrc, pt=pt, m=splitter.last)
        self.source                = source     = stream.Endpoint(eth_udp_user_description(8))
        self.sink                  = sink       = stream.Endpoint([("data", 8)])

        self.comb += [
            sink.connect(splitter.sink),
            splitter.source.connect(params.sink),
            params.source.connect(packetizer.sink),
            packetizer.source.connect(source),
            source.length.eq(splitter.len+rtp_header_length),
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

        # Timestamp generator
        cnt  = Signal(32)
        ts   = Signal(32)

        self.sync += [
            cnt.eq(cnt+1),
            If(fifo.source.ready & fifo.source.valid & fifo.source.last, ts.eq(cnt)),
        ]

        # JPEG & RAW
        self.submodules.jpeg = jpeg = LiteEthRTPTXJPEG(ts, ssrc, pkt_size)
        self.submodules.raw  = raw  = LiteEthRTPTXRAW(ts, ssrc, pkt_size)

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
