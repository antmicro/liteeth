from liteeth.common import *

from litex.soc.interconnect.packet import Depacketizer, Packetizer


class LiteEthRTPPacketizer(Packetizer):
    def __init__(self, dw):
        Packetizer.__init__(self,
            eth_rtp_description(dw),
            eth_udp_user_description(dw),
            rtp_header)

class LiteEthRTPRAWPacketizer(Packetizer):
    def __init__(self, dw):
        Packetizer.__init__(self,
            eth_rtp_raw_description(dw),
            eth_rtp_description(dw),
            rtp_raw_header)

class LiteEthRTPJPEGPacketizer(Packetizer):
    def __init__(self, dw):
        Packetizer.__init__(self,
            eth_rtp_jpeg_description(dw),
            eth_rtp_description(dw),
            rtp_jpeg_header)

class PacketSplitter(Module):
    def __init__(self, pkt_size):
        self.sink   = sink   = stream.Endpoint([("data", 8)])
        self.source = source = stream.Endpoint([("data", 8)])

        self.last = Signal()
        self.len  = Signal(16)
        pkt_len   = Signal(16)

        self.submodules.fifo = fifo = stream.SyncFIFO([("data", 8)], 2048)

        self.submodules.fsm  = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE", 
            If(sink.valid,
                NextState("RX")
            )
        )
        fsm.act("RX",
            sink.connect(fifo.sink),
            fifo.sink.last.eq((pkt_len == pkt_size-1) | sink.last),
            If(sink.ready & sink.valid,
                NextValue(pkt_len, pkt_len+1),
                If(fifo.sink.last,
                    NextValue(pkt_len, 0),
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
                NextValue(self.last, 0),
                NextState("IDLE"),
            ),
        )

class LineSplitter(Module):
    def __init__(self, pkt_size, width, height, bpp):
        self.sink   = sink   = stream.Endpoint([("data", 8)])
        self.source = source = stream.Endpoint([("data", 8)])

        self.last    = Signal()
        self.len     = Signal(16)
        self.line_no = Signal(16)
        self.offset  = Signal(16)

        line_len     = Signal(16)
        line_cnt     = Signal(16)
        split_cnt    = Signal(16)

        self.submodules.splitter = splitter = PacketSplitter(pkt_size)

        self.comb += sink.connect(splitter.sink)

        self.submodules.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE",
            If(splitter.source.valid,
                NextValue(self.offset, line_len),
                NextValue(self.line_no, line_cnt),
                If(line_len+splitter.len <= (width*bpp),
                    NextValue(self.len, splitter.len),
                    NextState("PTHRU"),
                ).Else(
                    NextValue(self.len, (width*bpp)-line_len),
                    NextValue(split_cnt, 0),
                    NextState("SPLIT"),
                ),
            ),
        )
        fsm.act("PTHRU",
            splitter.source.connect(source),
            self.last.eq(splitter.last),
            If(splitter.source.valid & splitter.source.ready & splitter.source.last,
                NextState("IDLE"),
                If(splitter.last,
                    NextValue(line_len, 0),
                    NextValue(line_cnt, 0),
                ).Else(
                    If(line_len+splitter.len == (width * bpp),
                        NextValue(line_len, 0),
                        NextValue(line_cnt, line_cnt+1),
                    ).Else(
                        NextValue(line_len, line_len+splitter.len),
                    ),
                ),
            ),
        )
        fsm.act("SPLIT",
            self.last.eq(0),
            splitter.source.connect(source),
            If(split_cnt+line_len == (width*bpp-1), 
                source.last.eq(1),
            ),
            If(splitter.source.valid & splitter.source.ready,
                NextValue(split_cnt, split_cnt+1),
                If(source.last, 
                    NextValue(line_len, 0),
                    NextValue(line_cnt, line_cnt+1),
                    NextValue(self.len, (splitter.len+line_len)-(width*bpp)),
                    NextState("PTHRU"),
                ),
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
            source.param.seq.eq(seq),
            source.param.ts.eq(ts),
            source.param.ssrc.eq(ssrc),
        ]

class LiteEthRTPTXJPEG(Module):
    def __init__(self, ts, ssrc, pkt_size):
        self.submodules.splitter        = splitter        = PacketSplitter(pkt_size)
        self.submodules.rtp_packetizer  = rtp_packetizer  = LiteEthRTPPacketizer(8)
        self.submodules.jpeg_packetizer = jpeg_packetizer = LiteEthRTPJPEGPacketizer(8)
        self.submodules.params          = params          = RTPParams(ts=ts, ssrc=ssrc, pt=26)
        self.source                     = source          = stream.Endpoint(eth_udp_user_description(8))
        self.sink                       = sink            = stream.Endpoint([("data", 8)])

class LiteEthRTPTXRAW(Module):
    def __init__(self, ts, ssrc, pkt_size):
        # TODO: replace with CSR
        csr_pt     = Signal(7)
        csr_width  = Signal(16)
        csr_height = Signal(16)
        csr_bpp    = Signal(4)

        sequence     = Signal(32)
        rtp_sequence = Signal(32)

        self.comb += [
            csr_pt.eq(80),
            csr_width.eq(1280),
            csr_height.eq(720),
            csr_bpp.eq(2),
        ]

        self.submodules.splitter       = splitter       = LineSplitter(pkt_size, csr_width, csr_height, csr_bpp)
        self.submodules.rtp_packetizer = rtp_packetizer = LiteEthRTPPacketizer(8)
        self.submodules.raw_packetizer = raw_packetizer = LiteEthRTPRAWPacketizer(8)
        self.submodules.params         = params         = RTPParams(ts=ts, ssrc=ssrc, pt=csr_pt, m=splitter.last)
        self.source                    = source         = stream.Endpoint(eth_udp_user_description(8))
        self.sink                      = sink           = stream.Endpoint([("data", 8)])

        self.comb += [
            sink.connect(splitter.sink),
            raw_packetizer.sink.param.ext_seq.eq(sequence[16:32]),
            raw_packetizer.sink.param.length.eq(splitter.len),
            raw_packetizer.sink.param.line_no.eq(splitter.line_no),
            raw_packetizer.sink.param.offset.eq(splitter.offset),
            rtp_packetizer.sink.param.seq.eq(rtp_sequence[0:16]),
            splitter.source.connect(raw_packetizer.sink),
            raw_packetizer.source.connect(params.sink),
            params.source.connect(rtp_packetizer.sink),
            rtp_packetizer.source.connect(source),
            source.param.length.eq(splitter.len+rtp_header_length+rtp_raw_header_length),
        ]

        self.sync += If(raw_packetizer.source.ready & raw_packetizer.source.valid & raw_packetizer.source.last,
            sequence.eq(sequence+1),
        )
        self.sync += If(rtp_packetizer.source.ready & rtp_packetizer.source.valid & rtp_packetizer.source.last,
            rtp_sequence.eq(sequence),
        )

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
